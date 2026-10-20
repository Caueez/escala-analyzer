# Contrato das regras — 2026.10.0

A constante `domain/rules/version.py` identifica o comportamento do motor desta candidata. O número é gravado nos jobs. Um worker de outra versão não executa silenciosamente um job antigo: registra `rules_version_changed`; o usuário deve solicitar novo cálculo.

As regras são **parâmetros configuráveis da empresa**. O sistema não fornece aprovação automática de uma escala nem atualização automática de legislação. Alterar os valores de um projeto não muda a versão do algoritmo, mas fica no snapshot utilizado pelo job.

| Tema | Comportamento estabilizado | Cobertura de regressão |
| --- | --- | --- |
| Ciclo | Blocos positivos alternam trabalho/folga; fases negativas e blocos ímpares repetem continuamente | `test_composite_cycles.py`, `test_schedule_calendar.py` |
| Prioridade diária | Jornada semanal zero é folga, mesmo diante de exceção de trabalho; depois valem exceções por data e ciclo | `test_group_hours.py`, `test_schedule_calendar.py` |
| Demanda | Exceção por data prevalece sobre demanda semanal | `test_coverage_analyzer.py` |
| Pessoas | Equipes fixas alocadas em turnos distintos são somadas; uma equipe rotativa conta uma vez | `test_analyzer.py`, `test_schedule_rules_analyzer.py` |
| Horas efetivas | Jornada do grupo substitui a do turno; `None` herda. O intervalo não é descontado duas vezes | `test_group_hours.py`, `test_schedule_rules_analyzer.py` |
| Capacidade | Pessoas e horas-pessoa são verificadas por turno/data. Não há simulação de cobertura minuto a minuto | `test_coverage_analyzer.py`, `test_group_hours.py` |
| Vigência | A última regra iniciada prevalece; datas iniciais duplicadas são recusadas | `test_schedule_rules_analyzer.py` |
| Janelas móveis | Sete dias, incluindo a transição de ano; usa a regra do último dia da janela | `test_schedule_rules_analyzer.py` |
| Mínimos mensais | Usa o maior mínimo ativo no mês, sem proporcionalidade | `test_schedule_rules_analyzer.py` |
| Pausa e interjornada | Alertas dependem das verificações ativas. Falta de horário impede validar descanso | `test_schedule_rules_analyzer.py` |
| Orçamento/padrões | Limites operacionais são obrigatórios nas novas propostas; baseline preservada mostra suas violações | `test_business_constraints.py` |
| Otimização | Baseline sempre presente; prioridades configuráveis; proposta reanalisada independentemente; sem prova de ótimo global | `test_schedule_optimizer.py`, `test_composite_cycles.py` |
| Permissões de alteração | Horas/ciclos/quantidades mudam somente conforme as permissões da busca e dos grupos | `test_group_hours.py`, `test_composite_cycles.py` |

A ordem inicial dos oito critérios de minimização é: déficit de pessoas, déficit de horas-pessoa, violações de regras, quantidade de tipos de escala, custo mensal estimado, quantidade de grupos, excedente de pessoas e total de funcionários. O projeto pode reordená-los. A prioridade de custo/pessoas antes da cobertura pode admitir faltas, que permanecem visíveis.

## Processo de mudança

1. Escrever o caso de negócio e um exemplo de entrada/saída que reproduza o problema.
2. Adicionar um teste que falhe antes da correção, mantendo a separação entre parâmetros da empresa e semântica do algoritmo.
3. Alterar o motor e sua versão quando houver mudança de interpretação/cálculo; documentar antes/depois e impacto em resultados antigos.
4. Executar a suíte de domínio, API e jobs e validar a migração de dados se o formato mudar.
5. Não reaplicar resultados antigos automaticamente. Preservar o snapshot e a versão que produziram cada resultado até sua expiração.
