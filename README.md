# Escala Visual

Editor web local de escalas de trabalho. Foi pensado inicialmente para ajudar a visualizar grupos por turno, ciclos de trabalho/folga e os efeitos desses ciclos sobre a cobertura de uma operação 24 horas por dia.

> **Importante:** os números do projeto inicial são demonstrativos. A análise verifica os parâmetros que estiverem configurados; não é parecer jurídico nem certificação de conformidade trabalhista. Antes de aprovar uma escala, confirme a legislação vigente, a convenção/acordo coletivo aplicável e as regras específicas da categoria com o RH, sindicato ou assessoria jurídica.

## Requisitos

- Python 3.13 ou superior
- [`uv`](https://docs.astral.sh/uv/)
- Navegador moderno

## Executar

Abra o terminal dentro da pasta do projeto e rode:

```bash
uv sync
uv run escala-visual
```

A aplicação ficará disponível em **http://127.0.0.1:8765**. Como o servidor escuta somente em `127.0.0.1`, por padrão ele não fica exposto à rede local.

Alternativa para desenvolvimento:

```bash
uv sync --extra dev
uv run uvicorn escala_visual.main:app --reload --host 127.0.0.1 --port 8765
```

Para executar os testes:

```bash
uv run pytest
```

Para encerrar, use `Ctrl+C` no terminal.

## O que já funciona

- **Linha do tempo mensal:** cada turno contém uma faixa por grupo, com cada dia marcado como trabalho ou folga.
- **Ciclos configuráveis:** por exemplo, 3x1, 5x2, 4x2 ou outra combinação de dias trabalhados e de descanso.
- **Fase do ciclo:** a data de referência é o primeiro dia trabalhado do ciclo. Mudar a data desloca o padrão no calendário.
- **Ajustes manuais:** clique num dia para alternar trabalho/folga. Também é possível arrastar uma célula de folga sobre um dia de trabalho do mesmo grupo para deslocar uma folga. O ajuste é pontual e fica guardado no projeto.
- **Demanda por turno e dia da semana:** configure quantas pessoas devem estar trabalhando em cada turno, inclusive demandas diferentes aos sábados e domingos.
- **Análise anual:** expande os ciclos em todos os dias do ano e informa, entre outros itens, déficits por turno/dia, quantidade de folgas por mês, domingos de folga, sequências de trabalho e janelas móveis de sete dias.
- **Dados locais:** os dados são gravados em `data/project.json` por padrão. O arquivo é criado na primeira execução.
- **Importar/exportar projeto:** backup completo em JSON; exportação da cobertura anual em CSV, que pode ser aberta no Excel ou em outro editor de planilhas.

## Fluxo sugerido

1. Abra **Configurações** e informe o ano que deseja avaliar.
2. Corrija o nome do projeto, as horas efetivas por dia e a demanda de cada turno/dia da semana.
3. Confira os grupos de exemplo. Edite, exclua ou crie grupos com a quantidade real de pessoas, ciclo e data inicial corretos.
4. Na **Linha do tempo**, mude de mês e clique/arraste para fazer ajustes pontuais. Toda alteração é salva automaticamente.
5. Abra **Análise anual** e filtre os achados de cobertura ou de regras.
6. Exporte o CSV ou um backup JSON quando quiser guardar uma versão do planejamento.

## Regras e perfis

Os perfis são apenas pontos de partida para o cálculo:

- **Referência base:** 44 horas e um dia de descanso por janela móvel de sete dias.
- **Transição proposta:** 42 horas e dois dias de descanso por janela móvel de sete dias.
- **Meta proposta:** 40 horas e dois dias de descanso por janela móvel de sete dias.

Os números e condições de cada perfil podem ser editados. Os parâmetros “domingos de folga por mês” e “folgas mínimas no mês” também são configuráveis. A exigência de oito folgas mensais e a frequência de domingos foram colocadas como premissas de planejamento a confirmar para o caso concreto; o aplicativo não as declara automaticamente como uma interpretação jurídica definitiva.

**Status legislativo na data desta versão (16/10/2026):** a PEC 221/2019 foi aprovada em dois turnos no Senado em 14/10/2026, mas as notícias consultadas em 15/10/2026 informavam que ainda faltava promulgação e publicação oficial. Portanto, o cenário de transição fica identificado como proposto, não como regra definitivamente vigente. Consulte as publicações oficiais mais recentes antes de definir a data de implementação.

Referências para acompanhamento:

- Agência Brasil — [Senado aprova o fim da escala 6x1 e redução da jornada](https://agenciabrasil.ebc.com.br/politica/noticia/2026-10/senado-aprova-fim-da-escala-6x1-e-reducao-da-jornada-de-trabalho)
- Agência Brasil — [Fim da 6x1: saiba quando entra em vigor a nova jornada](https://agenciabrasil.ebc.com.br/politica/noticia/2026-10/fim-da-6x1-saiba-quando-entra-em-vigor-nova-jornada-de-trabalho)
- UOL — [Prazos previstos para a proposta](https://economia.uol.com.br/noticias/redacao/2026/10/15/senado-aprova-fim-da-escala-6x1-entenda-quando-comeca-a-valer-a-5x2.ghtm)

## Como o cálculo funciona

Para cada grupo, o motor calcula a posição do dia dentro do ciclo de `dias de trabalho + dias de folga`, usando a data de referência. Uma alteração manual substitui o estado calculado apenas naquela data. Depois, o sistema soma as pessoas dos grupos em trabalho em cada turno e compara o resultado com a demanda configurada.

Os critérios de descanso são conferidos individualmente por grupo, porque todos os trabalhadores do mesmo grupo compartilham o mesmo padrão de datas. Isso permite localizar problemas de calendário, mas não avalia regras individuais que não estejam representadas no modelo — por exemplo, acordos particulares, férias, afastamentos, feriados específicos, limites de intervalo entre jornadas por horário real, funções com regime diferenciado ou restrições sindicais adicionais.

## Estrutura do projeto

```text
src/escala_visual/
├── main.py                       # API e servidor web local
├── domain/
│   ├── models.py                 # Modelos e validação de dados
│   ├── sample_data.py            # Projeto inicial demonstrativo
│   └── analyzer.py               # Cálculo dos ciclos e análise anual
├── infrastructure/
│   └── json_repository.py        # Persistência local em JSON
└── web/
    ├── index.html                # Interface
    ├── styles.css                # Estilos responsivos
    └── app.js                    # Interações da interface

tests/
└── test_analyzer.py              # Testes do motor de cálculo
```

## Limitações deliberadas da primeira versão

- Não gera automaticamente a melhor escala nem recomenda contratações; mostra a cobertura da escala que foi desenhada manualmente.
- Os ajustes arrastados são exceções por data; ainda não são uma regra recorrente automática do tipo “sempre no último domingo do mês”.
- Não importa a planilha atual automaticamente.
- Não faz validação jurídica oficial e não substitui a aprovação sindical.
- A análise de horas trata os dias trabalhados como blocos de `horas/dia` configurados por turno. Não calcula ainda horários de entrada/saída, intervalo intrajornada ou intervalo interjornada a partir de horários reais.

Essas limitações ficam separadas do núcleo do cálculo para permitir evoluir o projeto sem acoplar as regras específicas da fiação ao programa.
