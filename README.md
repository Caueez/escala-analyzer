# Escala Visual — 0.2.0rc1

Editor de escalas anuais com análise de cobertura, regras configuráveis e otimização por OR-Tools. Esta é uma **versão candidata para homologação SaaS**, com empresas isoladas, usuários e permissões, sessões seguras, persistência PostgreSQL e trabalhos assíncronos com RabbitMQ/Celery.

O domínio usa dataclasses e depende apenas da biblioteca padrão. Banco, autenticação, transporte HTTP e solucionadores ficam nas camadas externas. Resultados de otimização são propostas: não representam aprovação da escala e não alteram automaticamente o projeto.

## Desenvolver localmente com Docker

Todos os serviços rodam na sua máquina, sem provedor, domínio ou HTTPS. O comando abaixo prepara o `.env` para HTTP em `localhost`, incluindo as credenciais do banco e da mensageria. Execute a geração apenas na primeira configuração.

```bash
python3 scripts/generate_env.py --development
docker compose up --build -d
docker compose exec app python -m escala_analyzer.cli provision \
  --organization "Minha empresa" --email admin@suaempresa.com.br --name "Administrador"
```

Informe a senha interativamente e abra [http://localhost:8000/login](http://localhost:8000/login). O script recusa sobrescrever `.env` e gera segredos exclusivos. Não há credenciais padrão nem cadastro público.

O Compose inicia PostgreSQL, RabbitMQ, migrações, API, dispatcher e workers separados de análise e otimização. O usuário SQL da aplicação tem apenas permissões de dados; migrações usam outra credencial. Dados ficam em volumes próprios. **Não use `down -v` para atualizar um ambiente que contém dados.**

Para HTTPS público e critérios antes de atender clientes, siga o [runbook](docs/runbook.md) e o [checklist de liberação](docs/release.md). O modo de desenvolvimento não deve ser exposto na internet.

## Documentação

- [Arquitetura, responsabilidades e decisões](docs/architecture.md)
- [Regras estabilizadas e processo de alteração](docs/rules.md)
- [API, autenticação, revisões e jobs](docs/api.md)
- [Implantação, backup, restauração e incidentes](docs/runbook.md)
- [Escopo e critérios da versão candidata](docs/release.md)
- [Guia funcional preservado do editor local](docs/legacy-user-guide.md)

## Desenvolvimento e verificações

```bash
uv sync --extra dev
uv run pytest
uv run ruff check src tests migrations scripts
uv run ruff format --check src tests migrations scripts
uv run pyright --pythonpath .venv/bin/python src
```

Os testes unitários de persistência usam SQLite isolado por teste; isso não substitui os testes reais de migração, concorrência e mensageria em PostgreSQL/RabbitMQ. O smoke de integração está em `scripts/smoke_saas.py`; execute apenas contra uma implantação Compose de teste, com o env-file e o nome de projeto correspondentes.

Para executar a API fora de containers, configure as conexões acessíveis ao host, execute `uv run alembic upgrade head` com a conexão da role de migrações e inicie `uv run uvicorn escala_analyzer.main:app` com a conexão da role de execução. Os comandos de dispatcher e workers estão no Compose/runbook.

## Compatibilidade local e migração

O editor anterior continua disponível explicitamente com `ESCALA_MODE=local uv run uvicorn escala_analyzer.main:app --host 127.0.0.1`. Esse modo não possui autenticação, usa JSON e é recusado quando `ESCALA_ENVIRONMENT=production`. Não é montado junto com os endpoints SaaS.

Os arquivos locais não são migrados automaticamente nem apagados. Importe o backup na empresa correta pela interface ou pela CLI documentada. A importação SaaS acrescenta cópias com IDs novos, preservando os documentos anteriores.
