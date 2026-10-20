> Guia preservado do editor local 0.1.0. Para persistência, autenticação e execução SaaS, prevalecem o README e o runbook da versão 0.2.0rc1.

# Escala Visual

Editor de escalas de trabalho por grupos, com calendário anual, configurações de projeto, verificação das regras cadastradas e busca opcional de grupos para cobrir a demanda. Os turnos e grupos são criados pelo usuário; um projeto novo começa vazio.

## Executar

Requisitos: Python 3.13+ e [uv](https://docs.astral.sh/uv/).

```bash
uv sync
uv run uvicorn escala_analyzer.main:app --reload --host 127.0.0.1 --port 8765
```

Abra **http://127.0.0.1:8765**.

## Docker e dados persistentes

```bash
docker compose up --build -d
```

Abra **http://localhost:8000**. O Compose monta o diretório `./data` do computador em `/app/data` no container e define `ESCALA_DATA_DIR=/app/data`. Os projetos ficam em **`./data/project.json`**, permanecendo disponíveis quando o container é recriado. O diretório precisa permitir escrita pelo container.

A execução local usa o mesmo `data/project.json` por padrão. Para escolher outro local, configure `ESCALA_DATA_DIR` com o caminho do diretório desejado. O arquivo é criado no primeiro acesso com um projeto vazio, sem carregar dados demonstrativos. Arquivos existentes são preservados; o formato antigo de projeto único continua sendo aceito e passa ao formato com múltiplos projetos no próximo salvamento.

As alterações são gravadas em JSON com substituição atômica do arquivo. Faça backups copiando `data/project.json`; também é possível importar e exportar projetos pela interface. Ao restaurar um backup diretamente no diretório, pare o serviço antes da substituição para evitar que uma sessão aberta sobrescreva os dados. Use uma única instância da aplicação por diretório de dados.

Redefinir um projeto limpa seus turnos, grupos e configurações, mantendo seu identificador. Outros projetos salvos permanecem disponíveis. Um arquivo inválido gera erro de leitura e não é substituído por dados de exemplo.

## Configurar a escala

Em **Configurações**, informe os dados da empresa, ano e parâmetros do projeto. Crie os turnos com horário inicial, duração informada e pausa. Escolha se a duração inclui a pausa (8 h de turno com 45 min de pausa = 7h15 efetivas) ou se já representa trabalho efetivo (8 h efetivas com 45 min de pausa = 8h45 no turno). Backups antigos preservam a segunda interpretação. A interface mostra a conta antes de salvar.

Cadastre grupos e suas alocações, ciclo de trabalho e folga, data de referência e ajustes por data. A linha do tempo permite editar os dias de trabalho e folga, deslocar os ciclos e organizar a ordem dos grupos.

As verificações consideram os parâmetros cadastrados de horas, folgas, domingos, sequências de trabalho e intervalos. As verificações de descanso entre jornadas e pausa intrajornada são opcionais e precisam estar ativadas nas regras para gerar alertas. Configure os horários dos turnos para analisar o descanso entre jornadas. Sem horário inicial, não é possível determinar esse descanso com precisão. A pausa é contabilizada mesmo com a validação de mínimo desativada. Essa validação apenas compara a pausa cadastrada com o mínimo configurado e não cria ou prolonga intervalos automaticamente. O término do turno usa a duração total calculada, sem somar a pausa duas vezes. Horários e pausas pertencem ao turno e são herdados pelos grupos alocados nele.

Os detalhes mensais e anuais mostram folgas por dia da semana e horas por pessoa, incluindo trabalho, pausas e descanso. Leia a base de cálculo apresentada: o saldo de horas de um período e o intervalo entre duas jornadas são medidas diferentes. A ausência de alertas significa apenas que as verificações ativas não encontraram conflito com os parâmetros fornecidos; a avaliação humana depende de horários completos, parâmetros corretos e regras aplicáveis à empresa.

### Regras com vigência

O conjunto principal vale até ser substituído por uma vigência cadastrada. Cada vigência contém data inicial, identificação, fonte e um conjunto completo de parâmetros. A última vigência iniciada em uma data prevalece; não há duas vigências com a mesma data.

- Janelas móveis de sete dias usam o parâmetro vigente no último dia da janela, incluindo dias do ano anterior.
- Dias consecutivos e intervalos usam a regra da data de trabalho.
- Mínimos mensais usam o maior mínimo ativo durante o mês, sem proporcionalidade.

A análise verifica os parâmetros informados; regras setoriais e instrumentos coletivos precisam ser traduzidos para essas configurações. Não há atualização automática das regras.

## Buscar equipes complementares

A busca usa OR-Tools CP-SAT para propor novas equipes que complementem a escala atual. Identificadores, nomes, tamanhos, turnos, ciclos, fases e ajustes por data dos grupos existentes são preservados. As horas semanais só podem mudar quando houver autorização no grupo e na busca; sem essas duas permissões, os grupos ficam integralmente preservados.

Informe os ciclos permitidos, o tamanho máximo das novas equipes e os limites de pessoas e grupos. Um grupo representa uma linha do calendário com ciclo e fase estáveis durante o ano e pode reunir equipes fixas em vários turnos. Essas equipes compartilham os dias de trabalho e folga do grupo, mas cada equipe permanece em seu turno; suas quantidades são somadas no total de pessoas. A busca não cria revezamento entre turnos nem ajustes pontuais por data. Os limites configurados não autorizam reduzir ou excluir grupos existentes: se a escala atual já exceder um limite, essa situação precisa aparecer explicitamente na comparação e não é corrigida silenciosamente.

A escala atual aparece como referência (**baseline**), com seus grupos, cobertura, violações e eventuais limites já ultrapassados. Regras e cobertura são objetivos flexíveis: uma alternativa pode conter violações e falta de pessoas, que devem permanecer visíveis. Resultado disponível não significa escala aprovada. Os horários, horas efetivas e pausas cadastrados nos turnos entram nas verificações; descanso entre jornadas e pausa intrajornada só geram violações quando suas respectivas verificações estão ativadas. Horários ausentes impedem concluir que os descansos atendem às regras.

Cada alternativa encontrada passa por uma análise independente das regras e da cobertura reais. A ordenação final usa os resultados dessa reavaliação, conforme a ordem salva em **Configurações → Prioridade de aceitação**. A mesma ordem orienta os objetivos da busca. A ordem inicial é:

1. Atender à quantidade mínima de pessoas em cada dia e turno: menor déficit acumulado em pessoa-dia. Uma sobra em outro dia ou turno não compensa uma falta.
2. Menor falta de horas-pessoa, considerando a duração efetiva requerida pelo turno.
3. Menos violações das regras verificadas.
4. Menor quantidade de grupos.
5. Menor excedente acumulado em pessoa-dia, somando as pessoas acima da demanda em cada turno e data.
6. Menor quantidade total de pessoas.

Violações dos grupos preservados permanecem no resultado. Acrescentar equipes pode melhorar a cobertura; violações internas só podem ser corrigidas pelo ajuste de horas explicitamente autorizado e viável nos limites cadastrados. Compare o total e a origem das violações entre a referência e cada alternativa antes de escolher.

A busca procura até **10 alternativas por padrão**, com configuração de até **30**, dentro do orçamento de tempo. A enumeração termina ao alcançar esse limite ou o prazo e não é exaustiva. O modelo de busca usa uma aproximação para orientar a geração; depois, as alternativas são reavaliadas e ordenadas pelas medidas reais. Por isso, a aplicação não apresenta prova de ótimo global (`optimal=false`), mesmo quando o solver resolve seu modelo interno até o ótimo. A melhor alternativa exibida é a melhor entre as encontradas e reavaliadas, sem garantia de que não exista outra superior. Uma solução do modelo flexível pode conter violações ou déficit. Encerrar sem solução dentro do prazo não comprova inviabilidade.

Gerar alternativas não altera a escala salva. Confira a referência e os detalhes de cada opção e aplique explicitamente a escolhida para acrescentar equipes complementares e aplicar ajustes autorizados de jornada, preservando os demais dados dos grupos atuais. Se alterar grupos, turnos, demanda ou regras, gere novamente antes de aplicar. Exportar o projeto permite guardar uma cópia da configuração anterior.

## Desenvolvimento

```bash
uv sync --extra dev
uv run pytest
uv run ruff check src tests
uv run pyright src
```

Domínio em `src/escala_analyzer/domain`, API em `main.py`, interface em `web/` e persistência em `infrastructure/`.


## Jornada do grupo por dia da semana

Em **Grupos → Editar → Jornada por dia da semana**, configure as horas efetivas (sem pausa) de segunda a domingo:

- Vazio: herda as horas efetivas do turno, mantendo compatibilidade com projetos anteriores.
- Valor positivo: substitui as horas de trabalho naquele dia da semana, em todos os turnos alocados ao grupo. O início e a pausa continuam vindo do turno.
- Zero: folga fixa naquele dia, inclusive se existir um ajuste manual de trabalho nessa data. Nos demais dias, o ciclo e as exceções continuam valendo.

A linha do tempo exibe as horas líquidas nas células de trabalho. Relatórios mensais/anuais, limites de horas em janelas móveis, intervalos, fim de jornada e descanso usam a jornada resolvida por grupo e data. Uma pausa não é descontada duas vezes: os valores do grupo já representam trabalho efetivo, e a pausa soma tempo para determinar a saída.

Para permitir ajustes, marque **Permitir ao otimizador ajustar as horas deste grupo**, informe mínimo/máximo por dia e habilite **Otimizar jornadas** em Buscar escala. Mínimo e máximo iguais travam um dia; ambos zero mantêm a folga. A busca permite configurar o passo em minutos e os limites dos novos grupos. Sem autorização, nada muda nas jornadas existentes.

O ajuste usa OR-Tools para escolher sete durações, respeitando os limites de cada dia e avaliando as regras vigentes por data: horas móveis, descanso, domingos, folgas mensais, sequência de trabalho e pausas. Prioriza cobertura de pessoas e horas-pessoa, depois reduz violações e alterações das horas atuais. Cada proposta é reanalisada pelo motor independente; incompatibilidades continuam visíveis. Há no máximo um perfil ajustado por combinação de grupos encontrada, sem enumeração de todos os perfis nem prova de ótimo global.

**Cobertura de horas:** a análise também compara `pessoas requeridas × horas efetivas do turno` com a soma de `pessoas do grupo × horas efetivas do grupo` na data. Ter pessoas suficientes com jornadas muito curtas gera alerta de horas-pessoa faltantes, incluído na ordenação e no CSV. Essa medida é capacidade diária agregada: não comprova a cobertura simultânea em cada minuto nem posiciona pausas ou realoca entradas/saídas.

## Ciclos compostos e otimização do projeto atual

No editor de grupo, **Ciclo em blocos** aceita qualquer quantidade de blocos positivos, alternando trabalho e folga desde o primeiro bloco de trabalho: `5x2x3x1x2` tem 13 dias. Se o último bloco for de trabalho, ele se une ao primeiro bloco na repetição; as verificações consideram essa continuidade. Deixe vazio para usar o ciclo simples. **Total de dias do ciclo** é opcional: quando definido, a soma deve coincidir e o otimizador mantém esse total. Não há limite de 31 dias por bloco nem limite de quantidade de blocos.

Na linha do tempo, **Otimizar projeto atual** permite autorizar alterações de quantidades e de ciclos/fases separadamente. Considera os ciclos candidatos e o padrão atual, demanda por data e dia da semana, jornadas semanais, pausas e regras com vigência. Preserva nomes, identificadores, turnos, modo de revezamento, camadas e exceções manuais. Uma equipe rotativa continua com o mesmo tamanho em todos os seus turnos. Grupos com zero pessoas continuam cadastrados. Esse modo não cria grupos novos; **Buscar escala** continua buscando complementos.

As prioridades são critérios de minimização: se colocar total de funcionários antes da cobertura, o resultado pode reduzir equipes mesmo causando falta de pessoas. Todos os indicadores e achados continuam disponíveis. O resultado mostra os grupos ajustados, quantidades, ciclos, fases e jornadas antes da aplicação. A referência original sempre participa da comparação; gerar propostas não salva o projeto. A busca tem prazo, pode examinar apenas parte das fases de ciclos longos e não garante ótimo global. A otimização das jornadas usa etapas adicionais dentro do tempo disponível.

### Projetos, subdivisões e reutilização

O seletor superior escolhe o projeto (por exemplo, **Fiação 2027**); o segundo
seleciona a subdivisão. Cada escala anteriormente salva passa a ser uma subdivisão
do projeto inicial, sem alterar ano, turnos, equipes, regras ou ajustes por data.
**＋ Projeto** cria um projeto vazio e **＋ Subdivisão** cria outra escala no projeto
selecionado, herdando turnos e regras, sem duplicar funcionários. Em Configurações,
o nome do projeto é compartilhado entre suas subdivisões; o nome da subdivisão é local.
Excluir uma subdivisão não exclui as demais. O sistema mantém ao menos uma subdivisão.

**Reutilizar grupo salvo** permite escolher grupos de qualquer projeto e criar uma
cópia independente ou um vínculo. Grupos vinculados compartilham o ciclo, as fases,
as alocações, jornadas e ajustes por data ao salvar. As regras e demandas da subdivisão
continuam locais. Turnos ausentes são importados; configurações conflitantes com o
mesmo identificador são recusadas. **Desvincular grupo** preserva o grupo local e
interrompe a propagação de mudanças. Excluir um grupo local não exclui suas outras
ocorrências. Os dados continuam em `data/project.json`, escritos por substituição atômica.

### Busca automática e mistura de escalas

A busca gera automaticamente todos os padrões periódicos de trabalho/folga até a
duração máxima configurada (padrão: 7 dias, máximo: 14), incluindo ciclos compostos.
Rotações e repetições do mesmo período são deduplicadas, e as fases são consideradas.
Desligue a geração automática para informar ciclos manualmente. Chamadas antigas à
API que informam `cycles` sem `automatic_cycles` continuam usando os ciclos informados.
A opção **Permitir tipos de escala diferentes no mesmo turno** controla a mistura
nas propostas novas e na otimização de grupos existentes. Na busca de complementos,
grupos existentes são preservados, mesmo se já misturarem ciclos; um aviso informa isso.
As opções são salvas por subdivisão em `search_options`.

**Passo das horas** é a resolução das jornadas quando a otimização de horas está
habilitada: passo de 15 minutos admite 6h, 6h15, 6h30 etc., respeitando os limites
configurados. Jornadas são múltiplos do passo em minutos. Passos menores ampliam
o espaço de busca; o campo não altera o ciclo de dias trabalhados e folgas.

O universo de escalas não tem limite natural. A geração cobre os ciclos dentro do
limite configurado; a preparação e a busca de alternativas respeitam o prazo,
o número de soluções e os limites de pessoal/grupos. Não há garantia de enumerar
todas as combinações ou obter o ótimo global. A cobertura ainda é diária agregada.

O backup JSON exporta todas as subdivisões do projeto selecionado. A importação
aceita esse formato e arquivos antigos de uma única escala, preservando os outros
projetos. O backup anterior à migração desta instalação está em
`data/project.before-hierarchy-20261019.json`.

## Previsibilidade e orçamento da busca

Em **Configurações → Previsibilidade e orçamento**, ou no formulário de busca, configure limites obrigatórios para novas propostas:

- **Máximo de tipos de escala diferentes** (padrão: 2): vale para todos os turnos da subdivisão analisada. Fases diferentes, rotações equivalentes dos blocos e repetições do mesmo período contam como um tipo, não como escalas adicionais. A opção de misturar ciclos por turno continua disponível.
- **Trabalho mínimo no ciclo (%)** (padrão: 50% dos dias) e **máximo de dias consecutivos de folga** (padrão: 3): filtram ciclos automáticos e manuais, inclusive compostos. Assim, `1x4` não é aceito com os limites iniciais. Os percentuais se referem ao padrão do ciclo, não à folha ou à duração da jornada.
- **Custo mensal completo por funcionário** e **orçamento mensal máximo**, em reais: o custo estimado é o total de funcionários multiplicado pelo custo informado. Equipes fixas em vários turnos são somadas; a mesma equipe rotativa conta uma vez. O teto é obrigatório mesmo que a cobertura tenha prioridade maior. O orçamento pode ficar vazio; para ativá-lo, informe custo por funcionário positivo. Não há cálculo automático de encargos, folha, adicionais ou horas extras: inclua-os na estimativa informada.

Os limites de tipos, folgas e orçamento podem ficar vazios. Alterações no formulário da busca são salvas na subdivisão. Eles valem tanto para complementar a escala quanto para otimizar os grupos existentes. A escala original continua na comparação mesmo fora dos limites, identificada como não aceitável, com aplicação bloqueada; novas propostas passam por nova conferência dos limites após a análise. Se o teto não comportar a demanda, as faltas continuam visíveis: a busca não ultrapassa o orçamento para escondê-las.

**Prioridade de aceitação** agora inclui **Previsibilidade: menos tipos de escala** e **Menor custo mensal estimado**. Estes critérios orientam o solver e ordenam as propostas que atendem aos limites obrigatórios. Backups com a ordem antiga mantêm sua sequência e recebem os dois critérios adicionais ao final.

O campo **Ciclos candidatos** permanece editável mesmo com geração automática ligada. Digitar nele seleciona automaticamente o modo manual; marcar a geração automática volta a gerar candidatos dentro da duração máxima e dos limites da empresa.
