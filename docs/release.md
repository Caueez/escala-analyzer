# Liberação 0.2.0rc1

## Objetivo

Estabilizar uma primeira base de SaaS com dados isolados por empresa, autenticação, usuários, persistência transacional, execução assíncrona e regras de cálculo versionadas. A designação RC significa **candidata para homologação**, não serviço já publicado ou homologação operacional concluída.

## Incluído

- Preservação da suíte de regressão das regras e editor local.
- Dataclasses e isolamento de dependências da camada de domínio.
- PostgreSQL com Alembic, snapshots JSONB e revisões de edição.
- Empresas, administradores, editores e usuários de leitura.
- Sessões opacas, Argon2id, expiração, revogação, CSRF, origem/host restritos e limite de tentativas.
- API sem processamento anual/OR-Tools nas requisições SaaS.
- Outbox transacional, RabbitMQ durável, Celery, idempotência, quotas, leases e recuperação.
- Editor com login, gestão básica de conta/usuários, polling dos jobs e tratamento de revisões.
- Logs sem credenciais, request IDs, saúde, auditoria persistente e retenção de resultados.
- Docker Compose, execução sem root nos serviços de aplicação, testes e pipeline CI.
- Migração explícita por importação aditiva dos arquivos locais.

## Evidência de validação

O pipeline executa lint, formatação, tipagem, regressões e testes de segurança/isolamento, migrações em PostgreSQL real, smoke HTTP com RabbitMQ e workers reais, concorrência de gravação e backup/restauração em banco novo. Os testes de banco SQLite são complementados por esses testes reais; não substituem locks/transações do PostgreSQL.

`scripts/smoke_saas.py` é restrito a URLs loopback e cria uma empresa descartável. `scripts/check_restore.sh` restaura em um banco novo e verifica contagens e versão de migração. São ferramentas de verificação controlada, não scripts de carga para ambientes de clientes.

Validação local da candidata: 136 testes de regressão/segurança passaram, Ruff e Pyright sem erros; migração sem divergência em PostgreSQL; fluxo HTTP real com análise/otimização em workers e exportação CSV concluído; concorrência por revisão validada; role PostgreSQL de execução sem superusuário, criação de bancos/roles/tabelas ou escrita na versão de migração verificada; reinício do broker com job aceito durante a indisponibilidade e concluído após recuperação; dump restaurado em banco separado com contagens e revisão conferidas; auditoria das 66 distribuições Python do ambiente sem vulnerabilidades conhecidas após a atualização. Os serviços foram exercitados em um projeto Compose isolado, sem importar os dados locais da empresa.

O [registro de validação](validation-0.2.0rc1.md) detalha os comandos, resultados e limites da evidência.

## Critérios antes de disponibilizar a clientes

- [ ] Hospedagem e domínio reais definidos; HTTPS, DNS e certificado verificados no ambiente final.
- [ ] Segredos fora do repositório, acesso operacional restrito e credenciais com privilégio mínimo; revisar uso de TLS nas conexões de serviços externos.
- [ ] Imagens registradas e fixadas por digest; resultado da auditoria de dependências e de imagens revisado.
- [ ] Backup externo criptografado, rotina automatizada e restauração comprovada no ambiente escolhido; RPO/RTO aprovados.
- [ ] Monitoramento e alertas de disponibilidade, filas, workers, outbox, disco e memória conectados a responsáveis por incidentes.
- [ ] Teste de carga com projetos representativos, concorrência e tempos de fila; limites de recursos e quotas dimensionados.
- [ ] Política de retenção, privacidade, atendimento, recuperação de conta e operação aprovada pelo responsável pelo produto.
- [ ] Revisão independente de segurança/autorização antes de tráfego público.
- [ ] Regras e exemplos reais validados pelo responsável de negócio; nenhuma proposta é tratada como aprovação automática.

Esses itens dependem do ambiente e dos responsáveis finais; não são preenchidos apenas porque a suíte local passou. Não há implantação pública automática neste trabalho.

## Limites conhecidos e evolução posterior

- Compose de um nó; sem failover/alta disponibilidade do banco, broker ou API.
- Sem faturamento/assinaturas, convites por email, email de recuperação, MFA, SSO ou múltiplas empresas por usuário nesta candidata.
- Isolamento por empresa é aplicado na aplicação/repositórios; PostgreSQL RLS não está habilitado.
- Rate limit por IP precisa de política adequada no ingress: a API não confia em forwarded headers arbitrários.
- Cancelamento invalida resultados, mas pode aguardar limite do processo para parar CPU nativa.
- Não há garantia de ótimo global, cobertura minuto a minuto ou adequação automática a legislação.
- Alterações futuras de schema/algoritmo precisam de migração e testes; não há promessa de rolling upgrade sem manutenção.
- O ambiente definitivo ainda precisa de prova de capacidade, backup externo e operação contínua.

## Revisão de dependências nesta candidata

A auditoria detectou o advisory [GHSA-6q48-6c7w-9gw2 de certifi](https://github.com/advisories/GHSA-6q48-6c7w-9gw2). O lock foi atualizado para `certifi 2026.10.19`. O build/CI usa `uv 0.13.4`, corrigido para o [advisory do bundle de CAs do uv](https://github.com/advisories/GHSA-hq85-5cpj-mr62). Os advisories foram consultados na base oficial; uma auditoria precisa ser repetida a cada liberação, pois novos problemas podem ser publicados depois.

As imagens de Python, PostgreSQL, RabbitMQ e Caddy e a action de checkout estão fixadas por digest/SHA nesta candidata. A imagem da aplicação ainda deve ser publicada no registry escolhido e promovida por seu digest após a homologação.
