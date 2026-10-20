# Operação e recuperação

## Inicialização em homologação local

Requisitos: Docker Engine e Docker Compose v2, Python 3.13 e `uv` para testes fora de containers. Reserve aproximadamente 4 GB de RAM para a configuração inicial; confirme os limites com carga representativa.

```bash
python scripts/generate_env.py --development
# Cria .env com permissão 0600 e segredos aleatórios; recusa sobrescrever arquivo existente.
docker compose up --build -d
docker compose exec app python -m escala_analyzer.cli provision \
  --organization "Minha empresa" --email admin@suaempresa.com.br --name "Administrador"
```

A senha é lida interativamente, duas vezes. Acesse `http://localhost:8000/login`. O modo de desenvolvimento desliga Secure **apenas** para permitir HTTP local. Não publique esse modo na internet.

Na criação de um volume novo, o banco provisiona roles SQL distintas para aplicação e migrações. A API recebe somente credenciais de execução; o serviço `migrate` recebe a conexão de migrações. A primeira execução executa `alembic upgrade head` antes de iniciar a API, workers e dispatcher. O banco e o broker possuem volumes próprios, não têm portas publicadas e não são gravados no diretório JSON antigo.

## Implantação com HTTPS

```bash
python scripts/generate_env.py --origin https://escala.suaempresa.com.br
docker compose --profile edge up --build -d
# Provisionar o primeiro administrador como acima.
```

Aponte DNS para a máquina e permita 80/443 para o Caddy emitir o certificado. A API fica publicada apenas em loopback. É possível usar um proxy/ingress gerenciado em vez do perfil `edge`; preserve o host público e mantenha a API fora da internet direta.

Produção recusa modo local, SQLite, cookies sem Secure, origem sem HTTPS, credenciais de banco/broker com menos de 32 caracteres e host `*`. Essas verificações não substituem revisão da infraestrutura. Em serviços gerenciados, use TLS para banco/broker e credenciais com privilégio mínimo. Provisione previamente as roles `escala` (dados) e `escala_migrator` (DDL), usando `deploy/postgres/001_roles.sh` como referência; a migração inicial espera a role de execução `escala`. Use a conexão de migrações somente no serviço/ambiente de migração, nunca nos workers ou na API. A configuração Compose é uma implantação de um nó, não fornece alta disponibilidade.

A API não confia em `X-Forwarded-For` arbitrário. O limite de login por endereço usa a conexão efetiva; atrás de proxy, ele é compartilhado por conexões daquele proxy. Antes de tráfego público, configure limitação por IP no ingress e dimensione essa política; não habilite confiança irrestrita em cabeçalhos enviados por clientes.

O container de aplicação roda como UID 10001, sem capabilities, filesystem somente leitura nos serviços contínuos, `/tmp` limitado e processos com limites de memória. Os workers têm desligamento gracioso de 200 s, acima do limite duro de tarefa. Ajuste RAM/concorrência após medir dados reais; aumentar workers sem redimensionar o banco e as quotas não garante mais capacidade.

## Atualizar

1. Validar backup recente e restauração em banco separado; registrar a imagem/revisão em operação.
2. Construir a imagem com o lockfile; em um registry de produção, registrar e usar seu digest, inclusive os digests das imagens base/de serviços.
3. Parar a entrada de novas buscas durante manutenção, aguardar os workers ou permitir recuperação de leases.
4. Aplicar migrações em um job único. API/worker não executam `create_all` nem migrações automáticas concorrentes.
5. Reiniciar serviços da mesma versão de código/regras e verificar `/health/ready`, login, leitura/gravação e um job por fila.
6. Em mudança incompatível, usar janela de manutenção. O esquema inicial não promete rolling upgrade entre versões futuras.

Rollback de aplicação exige compatibilidade com o esquema. Não use `alembic downgrade` como restauração de produção: a reversão da migração inicial remove tabelas. Em falha incompatível, restaure o backup validado em banco separado e faça a troca controlada da conexão.

## Backups

```bash
mkdir -p backups
chmod 700 backups
docker compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > backups/escala.dump
chmod 600 backups/escala.dump
```

Copie backups criptografados para armazenamento externo ao host e teste a recuperação regularmente. O dump inclui identidades e hashes de senha e deve ser protegido como dado sensível. Não basta manter o volume Docker ou uma cópia no mesmo disco.

Teste em banco **novo**, sem apontar a aplicação para ele:

```bash
docker compose exec -T db sh -c 'createdb -U "$POSTGRES_USER" escala_restore_check'
docker compose exec -T db sh -c 'pg_restore -U "$POSTGRES_USER" --no-owner --no-acl -d escala_restore_check' < backups/escala.dump
docker compose exec -T db sh -c 'psql -U "$POSTGRES_USER" -d escala_restore_check -c "SELECT version_num FROM alembic_version;"'
```

Após um restore com `--no-acl`, reaplique as permissões da role `escala` ao schema/tabelas, revogue escrita em `alembic_version` e confira acesso da aplicação antes de promover o banco. `scripts/check_restore.sh` inclui essa etapa no teste isolado. Verifique contagens por empresa, integridade referencial e projetos de amostra. Para uma recuperação real, revogue sessões restauradas antes de reabrir o serviço e considere os efeitos de dados posteriores ao backup. Metas iniciais propostas: RPO 24 h e RTO 4 h; precisam ser aprovadas e comprovadas no ambiente de hospedagem, não são garantias desta versão.

## Migrar os projetos locais

Faça uma cópia do JSON original e mantenha o editor local fechado durante a exportação. Importe o backup pela interface autenticada ou pela CLI:

```bash
# O arquivo precisa existir dentro do container ou de um volume montado para a operação.
python -m escala_analyzer.cli import-json --email admin@suaempresa.com.br --file /caminho/project.json
```

O comando requer acesso operacional ao ambiente do banco e um administrador existente. A importação é aditiva e remapeia IDs/vínculos; não se apropria dos dados de outra empresa. Confirme turnos, grupos, totais e regras antes de considerar a migração concluída. O original não é apagado.

## Saúde, logs e incidentes

- `/health/live`: processo HTTP responde.
- `/health/ready`: revisão do schema e conexão ao broker; retorna 503 quando indisponíveis.
- Logs HTTP incluem request ID, método, caminho, status e duração. Não incluem corpo, senha, cookies, URL de conexão ou resultados.
- Jobs têm estados `queued`, `running`, `succeeded`, `failed`, `cancelled` e código de falha seguro.
- Alertar externamente para: 503/5xx persistentes, idade do job mais antigo em fila, ausência de workers, crescimento da outbox, falhas de publicação, leases expirados, falhas repetidas e uso de disco/memória do PostgreSQL/RabbitMQ.

```bash
docker compose ps
docker compose logs --tail 100 app dispatcher analysis-worker optimization-worker
docker compose exec app alembic current
docker compose exec app alembic check
```

Broker fora: aceite de jobs permanece transacional, a outbox tenta publicar novamente; não apague os jobs nem purgue a fila. Worker morto: aguarde a expiração do lease e a recuperação pelo dispatcher. Falha de cálculo: examine o código e reproduza com dados controlados; não reexecute indefinidamente um job com o mesmo erro. Um erro HTTP 412 exige recarregar e reaplicar a edição, nunca sobrescrever automaticamente.

Troca de senha de recuperação:

```bash
docker compose exec app python -m escala_analyzer.cli reset-password --email usuario@suaempresa.com.br
```

A senha não aparece em argumentos e todas as sessões do usuário são revogadas. Controle o acesso a essa CLI por permissões operacionais do host.

A limpeza de resultados/sessões expiradas ocorre a cada hora pelo dispatcher. Pode ser antecipada com `python -m escala_analyzer.cli cleanup`. Auditoria e projetos não são apagados automaticamente. Não execute `docker compose down -v` em produção: isso remove os volumes de dados.
