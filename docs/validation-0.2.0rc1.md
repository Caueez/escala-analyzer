# Registro de validação — 0.2.0rc1

Validação local realizada em 20/10/2026, em recursos Docker isolados, com empresas e usuários fictícios. Os dados JSON locais não foram usados na implantação de teste.

| Verificação | Resultado |
| --- | --- |
| `pytest -q` | 136 testes passaram |
| Ruff: lint e formatação | Sem erros |
| Pyright em `src` | Sem erros |
| Sintaxe de `app.js` e `auth.js` com Node | Aprovada |
| Scripts de operação com `bash -n` / `sh -n` | Aprovados |
| Alembic em PostgreSQL real | `0001_saas` aplicada; `alembic check` sem divergências |
| Login, CSRF e revogação pela API real | Aprovados |
| Gravações simultâneas com a mesma revisão | Uma aceita e outra recusada com 412 |
| Análise via outbox → RabbitMQ → worker | Concluída |
| Otimização pela fila própria | Concluída, com baseline e sem aplicação automática |
| Exportação CSV assíncrona | Concluída e baixada pela sessão autenticada |
| Broker parado durante aceitação de job | Job aceito e mantido no banco; concluído após reinício do broker |
| Usuário SQL da aplicação | Sem superusuário, criação de bancos/roles/tabelas e sem escrita em `alembic_version` |
| Segredos administrativos nos containers de aplicação | Ausentes |
| Backup/restauração | Dump restaurado em banco novo, permissões reaplicadas, contagens de tabelas e versão conferidas |
| Auditoria das dependências Python | Sem vulnerabilidades conhecidas após atualização de certifi; uv do build/CI atualizado conforme advisory |
| Configuração de produção gerada | Validação de HTTPS, cookies, hosts e credenciais aprovada sem exibir segredos |

Os testes de falhas, duplicação de entrega, leases, cancelamento, isolamento por empresa, quotas, importação aditiva, propagação de vínculos e validação sem reflexão de senhas fazem parte da suíte.

O smoke de integração é reproduzível com `scripts/smoke_saas.py --check-broker-restart`; restauração com `scripts/check_restore.sh`. Ambos devem ser executados somente em ambiente isolado.

Não houve teste de carga representativo, validação de DNS/TLS em domínio real, implantação pública, comprovação de alta disponibilidade ou revisão independente de segurança. Os critérios operacionais restantes estão em [release.md](release.md).
