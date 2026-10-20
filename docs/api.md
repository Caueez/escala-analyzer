# Contrato HTTP da candidata

A origem da interface e da API é a mesma. Não há CORS permissivo. No ambiente de desenvolvimento, o contrato OpenAPI está em `/docs`; em produção não é publicado automaticamente.

## Sessão

1. `POST /api/auth/login`: JSON `{email, password}`, com `Origin` igual à origem pública configurada. Recebe cookies de sessão e CSRF.
2. `GET /api/auth/me`: usuário e permissão atuais.
3. Todos os POST/PUT/PATCH/DELETE autenticados enviam `X-CSRF-Token` com o cookie `escala_csrf`, além de `Origin`.
4. `POST /api/auth/logout`: revoga a sessão.
5. `POST /api/auth/password`: `{current_password, new_password}`; revoga todas as sessões e exige novo login.

Erros de login não distinguem conta ausente/inativa de senha incorreta. Contas são criadas por administradores com `POST /api/users`; `PATCH /api/users/{id}` altera `{role, active}`. Não se pode remover o último administrador ativo. Recuperação por email, SSO, MFA e convites não fazem parte desta candidata.

## Escalas

- `GET /api/project`: escala selecionada pelo usuário, com `ETag`.
- `GET /api/projects`: subdivisões da própria empresa.
- `GET /api/projects/{id}`: lê e seleciona a subdivisão, com `ETag`.
- `PUT /api/project`: salva o documento de escala com `If-Match: "<revisão>"`. Use `If-Match: "0"` somente para criação.
- `DELETE /api/projects/{id}` e `POST /api/project/reset`: exigem revisão; preservam ao menos uma subdivisão.
- `POST /api/projects/{id}/reuse-group`: cópia ou vínculo transacional, com revisão do destino.
- `POST /api/projects/import`: backup `{schema_version, active_id, projects}`. Acrescenta projetos com IDs novos; não sobrescreve projetos existentes.

Resultados de jobs nunca são aplicados implicitamente. O cliente mantém a revisão do projeto analisado e precisa tratar 412 ao aplicar uma proposta sobre uma escala que mudou.

## Jobs

`POST /api/analyze` e `POST /api/export` recebem um projeto; `POST /api/optimize` recebe `{project, options}`. Exigem `Idempotency-Key` de 8–128 caracteres e retornam 202:

```json
{"id":"uuid","kind":"analysis","state":"queued","rules_version":"2026.10.0","status_url":"/api/jobs/uuid","result_url":"/api/jobs/uuid/result"}
```

A mesma chave por usuário/empresa com o mesmo conteúdo retorna o mesmo job; outro conteúdo retorna 409. Quotas são verificadas antes da aceitação; rejeição não deixa mensagem ou job parcial.

- `GET /api/jobs/{id}`: estado, versão e código de erro seguro.
- `GET /api/jobs/{id}/result`: resultado somente quando concluído; caso contrário, 409.
- `POST /api/jobs/{id}/cancel`: autor ou administrador; invalida resultados futuros.
- Exportação concluída retorna `download_url`, protegido pela sessão e empresa. CSV é gerado a partir do resultado calculado pelo worker; nomes iniciados por fórmulas são neutralizados.

Faça polling com intervalo/backoff, não uma requisição em loop sem espera. A interface usa 750 ms e interrompe a espera após cinco minutos. Um job pode continuar disponível no servidor; timeout do navegador não é cancelamento do trabalho.

## Status relevantes

| Status | Significado |
| --- | --- |
| 401 | Sessão ausente, expirada ou revogada |
| 403 | Origem/CSRF/permissão não atendidos |
| 404 | Recurso inexistente ou de outra empresa |
| 409 | Idempotência conflitante, resultado pendente ou operação incompatível |
| 412 | Revisão de edição obsoleta |
| 413 | Corpo acima de 2 MB |
| 422 | Entrada ou invariantes inválidas |
| 428 | `If-Match` obrigatório ausente |
| 429 | Tentativas de login ou capacidade de jobs excedidas |
| 503 | Banco ou dependência temporariamente indisponível |

Erros operacionais incluem request ID para correlação. Nenhuma resposta deve incluir senha, token de sessão, connection string ou traceback.
