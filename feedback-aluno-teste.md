# Feedback do aluno-teste: "Acesso na medida: a esteira de acessos da Nimbus"

Enunciado testado: `README.md` da `main` no hash `e0d00135bfbe3cac9bbd5111efc21eca2783fd8f`. Solução na branch `aluno-teste`.

Aviso sobre os tempos: quem fez o teste foi um agente de IA com acesso ao código-fonte do ADK e sem pausas. Os tempos abaixo são os reais desta execução e não valem para um aluno humano. Ao lado de cada etapa ponho uma estimativa para um aluno que acabou de sair do módulo.

## Tempo

| Etapa | Início | Fim | Duração | Estimativa para um aluno |
|---|---|---|---|---|
| Leitura do enunciado e do repositório base | 09:38:29 | 09:38:59 | 0,5 min | 1 h a 1 h 30 |
| Desenho da arquitetura, incluindo pesquisa no código-fonte do ADK 2.9.2 e dois protótipos sem modelo (paralelo + junção + RequestInput + retomada em outro processo; laço de perguntas ao RH) | 09:38:59 | 09:44:31 | 5,5 min | 6 h a 10 h |
| Implementação (pacote `esteira/`, API, trilha, README), com testes locais dos passos 2 a 11 intercalados entre 09:48 e 09:53 | 09:44:31 | 09:54:47 | 10,3 min | 12 h a 20 h |
| Testes extras (404, 409, 422, pedido incompleto, redação ambígua de time) | 09:54:47 | 09:55:24 | 0,6 min | 1 h a 2 h |
| Execução do fluxo do avaliador (quatro tentativas em clones limpos, com as correções entre elas) | 09:55:24 | 10:30:03 | 34,7 min | 2 h a 4 h, mais o que a cota custar |
| **Total** | 09:38:29 | 10:30:03 | **51,6 min** | **22 h a 38 h** |

Detalhe da última etapa, que foi a que mais consumiu tempo, e quase todo ele por causa de modelo e cota:

| Tentativa | Horário | Resultado |
|---|---|---|
| 1 | 09:55:24 a 09:57:17 | Parou no passo 3: `429 RESOURCE_EXHAUSTED`, cota diária de 20 requisições do `gemini-2.5-flash` gasta no desenvolvimento. |
| (correção) | 09:57 a 09:59 | Troca do modelo padrão para `gemini-2.5-flash-lite`. |
| 2 | 09:59:30 a 10:00:09 | Parou no passo 4: o `flash-lite` devolveu resposta vazia (`MODEL_RETURNED_NO_CONTENT`) depois de chamar `listar_cargos`, de forma determinística para aquele texto. |
| (correção) | 10:00 a 10:08 | Rota `reler` no grafo, instrução de fechamento no texto do agente, testes de outros modelos e troca para `gemini-3.5-flash`. |
| 3 | 10:08:59 a 10:24:17 | Correto, mas inviável: `gemini-3.5-flash` levou de 1 a 4 minutos por chamada no plano gratuito, e o cliente HTTP estourou o tempo no passo 4. Abortada. |
| (correção) | 10:22 a 10:24 | Medição de latência de mais modelos e troca para `gemini-3-flash-preview`. |
| 4 | 10:24:59 a 10:30:03 | Passos 1 a 9 passaram de primeira (10:24:59 a 10:27:47). No passo 10, a cota diária do `gemini-3-flash` (também 20/dia) acabou às 10:28:24 e o pedido terminou `falhou`, sem revogar nada. Refiz o passo 10 às 10:29:14 com `ESTEIRA_MODELO=gemini-3.6-flash` no `.env` do clone (variável documentada no README) e ele passou. O passo 11 rodou em seguida. |

## Resultado do fluxo do avaliador

Tentativa válida: a 4ª, num clone limpo da `aluno-teste` (commit `a288eb4`) feito em pasta temporária fora do repositório. Segui só o README: `cp .env.example .env`, chave copiada com `cp` do `.env` da pasta de trabalho, `uv sync`, `uv run nimbus-sistemas`, `uv run nimbus-diretorio`, `uv run esteira-api`. Os pedidos foram abertos com um cliente HTTP simples (`httpx`), equivalente a `curl`.

| Passo | Resultado | Evidência (comando e trecho da saída) |
|---|---|---|
| 1 | Passou | `uv sync` → `exit=0`; `uv run esteira-api` → `Esteira de acessos em http://localhost:8000`; `POST /admin/reset` → `estado inicial restaurado`; `GET /admin/estado?email=marcos.vieira@nimbus.dev` → `email:true, times_github:[pagamentos], canais avisos/geral/pagamentos, papeis deploy-homolog/deploy-producao/leitura-basica/pagamentos-leitura` |
| 2 | Passou | `POST /pedidos` Carla → `201 situacao: concluido, pendencia: null`; `nimbus-verificar ... --time risco --cargo engenheiro-de-software --nivel pleno` → `exit=0 (CONFORME)`; análise de `GET /admin/registro` → `22 pares de sistemas diferentes com intervalos sobrepostos` (as 8 escritas nos 4 sistemas começaram entre 13:25:22.875 e 13:25:22.884 UTC e terminaram entre 13:25:23.676 e 13:25:23.684) |
| 3 | Passou | `POST /pedidos` Rodrigo → `201 situacao: aguardando_resposta, pendencia.tipo: dado_faltante, mensagem: "Qual é o time de Rodrigo Salles?"`; `GET /admin/estado?email=rodrigo.salles@...` → `{"email":false,"times_github":[],"canais":[],"papeis_nuvem":[]}` |
| 4 | Passou | resposta "É do time Jurídico" → `200 aguardando_resposta, dado_faltante, "Não existe o time Jurídico no diretório (times: Pagamentos, Risco, Plataforma, Dados)..."`, estado ainda vazio; resposta "É do time de Dados" → `concluido`; verificador Rodrigo `dados/engenheiro-de-dados/pleno` → `exit=0 (CONFORME)` |
| 5 | Passou | `POST /pedidos` Beatriz → `aguardando_resposta, tipo: aprovacao, gestor: {nome: "Sofia Arantes", email: sofia.arantes@nimbus.dev}, acessos_sensiveis: [github:infraestrutura, nuvem:deploy-producao]`; `GET /admin/estado` → `times_github:[plataforma]` (sem `infraestrutura`), papéis `deploy-homolog, infra-leitura, leitura-basica` (sem `deploy-producao`), 3 canais |
| 6 | Passou | resposta `{"aprovado": false}` → `concluido`; verificador Beatriz `--sem-sensiveis` → `exit=0 (CONFORME)` |
| 7 | Passou | Tiago → `aguardando_resposta` (aprovação); API parada com SIGINT (porta 8000 fechada) e subida de novo com `uv run esteira-api`; `GET /pedidos/{id}` → mesma pendência `69bd1b2d-...`; `{"aprovado": true}` → `concluido`; verificador sem flag → `exit=0`; segunda resposta igual → `409 "não existe pendência com esse id nesse pedido"`; `GET /admin/registro` com 51 chamadas antes e 51 depois, e `/admin/estado` idêntico; verificador de novo → `exit=0` |
| 8 | Passou | `POST /admin/falhas` (chat indisponível ×3, nuvem grava_e_falha ×1); Renata → `concluido`; registro: `chat adicionar_membro geral/pagamentos/avisos 503 nenhum` e `nuvem atribuir_papel leitura-basica 504 criado`, seguidos das inclusões com 201 e nenhum segundo POST de `leitura-basica`; verificador → `exit=0`; `/admin/estado` → `registros: 1` nos 3 canais e `atribuicoes: 1` nos 2 papéis |
| 9 | Passou | falhas desligadas; Marcos → `concluido, revogados: [email, chat x3, nuvem x4, github:pagamentos]`; `nimbus-verificar --pessoa marcos.vieira@nimbus.dev --desligado` → `exit=0`; `/admin/estado` da Priscila idêntico antes e depois (`priscila intacta? sim`) e verificador dela com o perfil ativo → `exit=0` |
| 10 | Passou na 2ª tentativa | 1ª: `situacao: falhou` por `429 ... limit: 20, model: gemini-3-flash` (cota diária), nada revogado e a falha de e-mail ainda armada. 2ª, com `ESTEIRA_MODELO=gemini-3.6-flash`: `concluido`; registro `email remover_conta 503 nenhum`, `503 nenhum`, `204 removido`; verificador `--desligado` → `exit=0` |
| 11 | Passou | `GET /pedidos/{tiago}/trilha` (depois de 2 reinícios da API) → etapas `pedido_recebido, agente_consultou_diretorio, pedido_extraido_pelo_agente, pedido_estruturado, acessos_calculados_pela_politica, aprovacao_solicitada, chamada_sistema x15, decisao_do_gestor, pedido_concluido`; exemplo de chamada `{"sistema":"email","metodo":"POST","caminho":"/email/contas","status":201,"resultado":"criado","duracao_ms":825}`; `var/diretorio-consultas.log` com 24 linhas (`listar_cargos`, `consultar_time`, `consultar_colaborador`) |
| 12 | Passou | `pyproject.toml`: `"google-adk==2.9.2"` (o `uv.lock` resolve 2.9.2); `git diff --stat origin/main HEAD -- dados nimbus testes` vazio; `.env` fora do `git ls-files`; nenhuma chave no `git log -p` da branch; `.env.example` com `GOOGLE_GENAI_USE_VERTEXAI`, `GOOGLE_API_KEY` e opcionais; `grep diretorio.json esteira/` só acha a docstring que diz que ele não é lido; política em `esteira/politica.py:acessos_da_politica`; README com Arquitetura, Garantias e Como rodar e com as linhas citadas conferidas; `uv run pytest` → `10 passed` |

Critérios de aceite:

| Critério | Resultado | Evidência |
|---|---|---|
| `uv sync` sem erro, ADK exato, série 2, ≥ 2.2.0 | Passou | passo 1 (`exit=0`) e passo 12 (`google-adk==2.9.2`) |
| Comandos do README sobem a API em :8000 com os serviços no ar | Passou | passo 1 |
| `dados/`, `nimbus/`, `testes/` idênticos | Passou | passo 12, diff vazio |
| Nenhuma chave versionada; `.env` fora; `.env.example` lista as variáveis | Passou | passo 12 |
| Pedido completo vira estruturado e conclui sem pendência | Passou | passo 2 |
| Pedido sem time gera pendência e nada é criado | Passou | passo 3 |
| Time inexistente gera nova pergunta em vez de chute | Passou | passo 4 (Jurídico) |
| Consultas em `var/diretorio-consultas.log` | Passou | passo 11 (24 linhas) |
| Diretório consultado pelo MCP, não pelo arquivo | Passou | passo 12 (`esteira/diretorio.py` e `McpToolset` em `esteira/agente.py`) |
| Verificador `exit=0` ao final de cada admissão (2, 4, 7, 8) | Passou | passos 2, 4, 7 e 8 |
| Lista de acessos calculada em código a partir da política | Passou | passo 12 |
| Perfil sensível aguarda gestor, com não sensíveis criados e sensíveis ausentes | Passou | passo 5 |
| Pendência identifica o gestor | Passou | passo 5 (Sofia Arantes) |
| Recusa conclui sem sensíveis; `--sem-sensiveis` `exit=0` | Passou | passo 6 |
| Pendência sobrevive ao reinício e a aprovação depois cria os sensíveis | Passou | passo 7 |
| Resposta repetida recebe 409 e não muda nada | Passou | passo 7 (51 → 51 chamadas, estado igual) |
| Com chat indisponível e nuvem gravando antes de falhar, a admissão conclui | Passou | passo 8 |
| Um registro por canal e uma atribuição por papel | Passou | passo 8 |
| Chamadas a sistemas diferentes com intervalos sobrepostos | Passou | passo 2 (22 pares) |
| Desligamento sem nenhum acesso, `--desligado` `exit=0` | Passou | passo 9 |
| Acessos de outras pessoas intactos | Passou | passo 9 |
| Com um sistema fora do ar, o desligamento conclui sem sobra | Passou, com ressalva | passo 10, na 2ª tentativa: a 1ª falhou por cota do modelo, não pela lógica de repetição |
| Trilha com pedido estruturado, decisão do gestor e cada chamada com resultado | Passou | passo 11 |
| Trilha disponível depois do reinício | Passou | passos 7 e 11 (a trilha do Tiago foi lida depois de 2 reinícios) |
| Rotas seguem o contrato (caminhos, campos, formatos, status) | Passou, com a ressalva do "mesmo formato" (ver Contradições 2) | passos 2 a 11; 404 e 409 conferidos nos testes extras |
| README com Arquitetura, Garantias e Como rodar, apontando trechos que existem | Passou | passo 12 |

Tentativas anteriores, pelo mesmo roteiro e registradas por transparência: a 1ª parou no passo 3 (cota do `gemini-2.5-flash`); a 2ª parou no passo 4 (resposta vazia do `gemini-2.5-flash-lite`); a 3ª foi abortada no passo 4 (latência de minutos do `gemini-3.5-flash`). Em todas, os passos anteriores ao ponto de parada passaram.

## Contradições

1. **"Algumas dezenas de chamadas" contra a cota real do plano gratuito.** O enunciado diz: "Como ordem de grandeza, o fluxo do avaliador faz algumas dezenas de chamadas ao modelo" e "consulte os limites ativos do seu projeto no próprio Google AI Studio". Nesta chave, o plano gratuito tem **20 requisições por dia por modelo** (`GenerateRequestsPerDayPerProjectPerModel-FreeTier`, `quotaValue: 20`) e **5 por minuto** no `gemini-3-flash` (`GenerateRequestsPerMinutePerProjectPerModel-FreeTier`, `quotaValue: 5`). Com um agente que consulta o diretório por MCP (exigência do requisito 1), cada leitura custa pelo menos 2 chamadas (ferramenta e resposta estruturada), e o fluxo do avaliador tem 9 leituras: cerca de 18 chamadas. Não dá para desenvolver e rodar o fluxo do avaliador no mesmo dia com o mesmo modelo. Cumprir "consulte o diretório pelo MCP" e "caiba no plano gratuito" ao mesmo tempo exige trocar de modelo no meio do trabalho.
2. **"Mesmo formato da rota de pedidos" contra os exemplos.** O exemplo de `POST /pedidos` mostra só `pedido_id`, `situacao` e `pendencia`, o de `GET /pedidos/{id}` acrescenta `pedido` e `acessos`, e `POST /respostas` diz "mesmo formato da rota de pedidos". Não fica claro se "rota de pedidos" é o `POST` (três campos) ou o `GET` (cinco). Não é bem uma contradição, mas "a API segue exatamente o contrato" não se sustenta quando o contrato tem dois formatos para a mesma coisa. Devolvi o formato completo em todas as rotas.
3. **"Nenhuma chave de API versionada: o `.env.example` é versionado com os nomes das variáveis, sem valores"** contra o passo 1, "copia o `.env.example` para `.env`, preenche a chave". Se `GOOGLE_GENAI_USE_VERTEXAI` precisar de valor, "sem valores" obriga o avaliador a saber que vazio equivale a `FALSE`. Funciona com a biblioteca atual, mas é frágil. Deixei vazio e documentei.

## Pontos vagos

| Ponto | Interpretações possíveis | O que adotei |
|---|---|---|
| "Time, cargo e nível são conferidos no diretório": quem confere, o agente ou o código? | (a) o agente, com as ferramentas MCP; (b) o código, depois do agente. | As duas coisas: o agente usa `listar_cargos`, e o nó `conferir` revalida tudo por MCP em código. Só (a) deixaria o requisito 5 ("sem chute") dependendo do modelo. |
| "Um agente que ... consulta o diretório pelo servidor MCP": a consulta precisa ser do agente? | Se o código consultar e o agente só receber o resultado, conta? | Mantive a ferramenta com o agente, o que custa uma chamada a mais por leitura (ver Contradições 1). |
| Quais acessos revogar no desligamento: os que a política daria à pessoa, ou tudo que existe nos sistemas? | "Revoga todos os acessos da pessoa" sugere descobrir o que existe. Mas GitHub e chat não têm rota "listar os times/canais de uma pessoa". | Varri todos os times e canais que aparecem em `politica.json` e as atribuições da nuvem filtradas por e-mail. Um canal fora da política não seria encontrado, e o enunciado não diz se isso importa. |
| "Da área de dados" é citar o time? | Sim (área = time) ou não (só descreve o cargo). | O modelo leu como time Dados. O enunciado só fixa o caso "engenheiro de dados" sem time. |
| O que fica em `acessos.criados` enquanto a aprovação está pendente | Vazio até concluir, ou o que já foi criado. | O que já foi criado. |
| Formato de `acessos.criados` e `revogados` | Não especificado. | `sistema:recurso` (`github:risco`, `email:carla.mendes@nimbus.dev`). |
| Resposta com formato errado (`{"aprovado": "sim"}`) | 409? 422? 400? | `422`, fora do contrato. |
| Situação durante o processamento | O contrato só tem três situações. | `em_andamento` interno. A chamada só devolve nas três do contrato, mas um `GET` concorrente veria o valor interno. |
| O que é "a pendência sobrevive ao reinício" quando o reinício acontece *durante* a criação | Declarado fora de escopo, mas a admissão com aprovação cria os comuns *enquanto* espera. | Os comuns terminam antes de a chamada devolver, então o reinício do passo 7 sempre pega o pedido parado só na aprovação. |
| Readmissão e mudança de time estão fora de escopo, mas o que fazer quando alguém pede a admissão de quem já está ativo? | Recusar, perguntar ao RH ou seguir. | Segui sem checar. O passo 4 do enunciado não cobre isso. |

## Travas

| Trava | Duração | Causa | Como destravei |
|---|---|---|---|
| Cota diária do `gemini-2.5-flash` (20/dia) esgotada no passo 3 da 1ª tentativa, às 09:57 | ~2 min | Cota | Troca de modelo (a cota é por modelo). |
| `gemini-2.5-flash-lite` devolvendo `MODEL_RETURNED_NO_CONTENT` depois da chamada de ferramenta, sempre para o mesmo texto longo (pergunta e resposta do RH repetidas), e trocando o cargo "engenheiro de dados" por `engenheiro-de-software` em outro teste | ~8 min | Modelo | Rota `reler` no grafo (defesa em código) e troca de modelo. A releitura sozinha não bastaria: a falha era determinística. |
| `gemini-3.5-flash` levando de 1 a 4 minutos por chamada, 104 s até para responder "ok" | ~15 min | Cota/ambiente (latência do plano gratuito) | Medi a latência de 5 modelos e fiquei com `gemini-3-flash-preview`. `gemini-flash-latest` e `gemini-3.1-flash-lite` responderam 503 naquele momento. |
| O pedido extraído pelo agente não aparecia na trilha | ~2 min | ADK | O Runner limpa `event.output` do `LlmAgent` quando a saída é a própria mensagem (`message_as_output`) antes do `on_event_callback` do plugin. Passei a registrar a extração pela saída do nó seguinte. |
| Cota diária do `gemini-3-flash` (20/dia) esgotada no passo 10 da 4ª tentativa, às 10:28:24 | ~1 min | Cota | `ESTEIRA_MODELO=gemini-3.6-flash` no `.env` do clone, reinício da API e o passo refeito. Pedido que falha por cota fica `falhou` e não é retomável: um limite da minha solução, aceitável porque o enunciado não pede retomada de pedido falho. |
| `pkill -f esteira-api` matou o meu próprio shell (o comando continha o texto) | 1 min | Ambiente (meu) | Script para parar pela porta. Não é problema do enunciado. |

Nenhuma trava veio do enunciado em si. As três maiores vieram da escolha de modelo no plano gratuito, e o enunciado joga essa escolha no aluno sem dar nenhum número.

## Pesquisa

O que precisei buscar além das aulas listadas, e onde:

- **Ramos paralelos, junção e política de repetição no grafo** (o enunciado avisa que isso passa das aulas). Fonte: código-fonte do ADK 2.9.2 (`google/adk/workflow/_workflow.py`, `_join_node.py`, `_retry_config.py`, `utils/_graph_parser.py`). Aprendi que uma tupla no encadeamento de arestas faz o leque, `JoinNode` espera todos os predecessores, `RetryConfig` vai no `FunctionNode`, e um nó que pede `RequestInput` fica `WAITING` enquanto os ramos irmãos seguem até o fim. **Este último ponto é o que viabiliza a garantia 2, e nada no enunciado sugere que o framework se comporta assim.**
- **Retomada de `RequestInput` pela API.** Como montar a resposta: `FunctionResponse` com `name="adk_request_input"` e `id` igual ao `interrupt_id`. Descobri que a retomada funciona em outro processo com `SqliteSessionService` e sem `ResumabilityConfig`, porque o workflow reconstrói o estado dos nós a partir dos eventos. Fonte: `runners.py`, `workflow/_node_runner_utils.py` e `cli/cli.py` (que monta essa resposta no `adk run`). O módulo ensina RequestInput "e retomada pela API", mas uma API com reinício no meio é outra coisa.
- **`rerun_on_resume`**: com `False` (o padrão do `FunctionNode`), a resposta humana vira a saída do nó. Isso decide o desenho do nó de aprovação. Fonte: docstring de `_function_node.py`.
- **Rotas no grafo**: `Event(output=..., route="x")` e o mapa `{"rota": nó}` nas arestas.
- **`LlmAgent` como nó**: roda em `single_turn` e não vê o histórico da sessão, então a conversa com o RH precisa ir na entrada. `output_schema` com ferramentas é implementado por uma ferramenta sintética `set_model_response`, o que custa uma chamada a mais.
- **Plugin**: quais callbacks existem (`on_event_callback`, `on_user_message_callback`, `after_tool_callback`) e o que eles recebem num workflow. Fonte: `plugins/base_plugin.py`.
- **`SqliteSessionService`** (aiosqlite) em vez do `DatabaseSessionService`, que exige SQLAlchemy.
- **Cotas e latência dos modelos no plano gratuito**: medição direta, porque sem console do AI Studio não havia outra fonte.
- **Cliente MCP em Python** (`mcp.client.streamable_http`) para os nós de código consultarem o diretório.

**O que o módulo não ensina e o desafio exige:** fan-out e join no grafo; `RetryConfig`; comportamento de um `RequestInput` num ramo paralelo; retomada de workflow em outro processo; plugin enxergando eventos de nós de workflow; e o manejo de cota e latência dos modelos no plano gratuito. O primeiro é avisado no enunciado. Os outros não.

## Decisões

Desenho final do grafo:

```
START ─> receber ─> interpretar (LlmAgent + McpToolset + output_schema) ─> conferir
                        ▲                                                   │
                        └──────────────── "reler" (saída vazia) ────────────┤
      perguntar_rh (RequestInput) ─> receber  <────────── "faltando" ───────┤
                                                                            │
      calcular_acessos <──────────────────────────────────── "admissao" ────┤
        ├─> provisionar_email  ──┐                                          │
        ├─> provisionar_github ──┤                                          │
        ├─> provisionar_chat   ──┼─> junta_admissao (JoinNode) ─┐           │
        ├─> provisionar_nuvem  ──┤                              ├─> concluir│
        └─> aprovacao_gestor (RequestInput) ─> provisionar_sensiveis ┘      │
      revogar_email | revogar_github | revogar_chat | revogar_nuvem <─ "desligamento"
        └──────────────> junta_desligamento (JoinNode) ─> concluir
```

| Decisão | Motivo | Alternativas descartadas |
|---|---|---|
| Agente só extrai; `conferir` revalida no diretório por MCP em código; o agente devolve o **nome citado** do time e o código resolve o id | Assim "Jurídico" não vira time válido por aproximação do modelo, e a garantia de "não chutar" fica no código | Confiar no id devolvido pelo agente |
| Aprovação como **ramo paralelo** aos quatro sistemas, e não como etapa antes deles | Garantia 2: os comuns ficam criados durante a espera | Pedir aprovação antes (quebra "a admissão não para"); um nó único que cria tudo |
| `aprovacao_gestor` (só pergunta) separado de `provisionar_sensiveis` (age) | Com `rerun_on_resume=False`, a decisão vira a saída do nó, e o `JoinNode` sempre recebe cinco ramos, com aprovação, recusa ou sem sensíveis | Roteamento aprovado/recusado direto para o join (o join esperaria para sempre o ramo não tomado) |
| Um nó por sistema, com `RetryConfig` | Paralelismo visível no grafo e repetição isolada por sistema | Um nó com `asyncio.gather` dos quatro; repetição por chamada |
| Idempotência por sistema: 409 é sucesso (e-mail); PUT (GitHub); `Idempotency-Key` com o id do pedido e consulta prévia (chat); leitura antes de criar (nuvem) | Cada sistema reage de um jeito à repetição (a "pista" do enunciado) | Tentar e contar com o registro depois |
| `em_paralelo` espera todas as chamadas antes de levantar a falha | Não cancelar no meio uma escrita que o servidor já aplicou | `asyncio.gather` sem `return_exceptions` |
| Trilha num `BasePlugin` com eventos `custom_metadata` para as chamadas | Usa o conceito de plugins do curso e nenhum nó precisa lembrar de auditar | Gravar na trilha dentro de cada nó |
| `SqliteSessionService` para sessões + SQLite próprio para pedidos e trilha | Retomada depois do reinício sem infraestrutura extra | Postgres; `InMemorySessionService` (perderia a pendência) |
| Revogação varre o universo da política e lê o estado | Não depender do time atual da pessoa | Aplicar a política ao time dela no diretório (deixaria sobra se ela tivesse algo a mais) |
| Rota `reler` para saída vazia do modelo, com limite de 2 e depois pergunta ao RH | Defesa em código contra falha do modelo | Deixar o pedido `falhou` |
| Modelo `gemini-3-flash-preview`, `temperature=0`, `thinking_budget=0`, `HttpRetryOptions` | Único que acertou todos os casos com latência aceitável e cota disponível no dia | `2.5-flash` (cota), `2.5-flash-lite` (saída vazia e cargo errado), `3.5-flash` (1 a 4 min por chamada) |
| ADK `2.9.2` fixado, e não o `2.2.0` do curso | Versão mais nova da série 2 no momento. O protótipo validou a API de workflow nela | 2.2.0 (as aulas usam, mas não havia motivo para ficar atrás) |

## Onde o enunciado decidiu por você

- **Os nomes das quatro ferramentas MCP e a existência de `consultar_time` por nome sem acento** entregam a resolução do time pronta. Nada contra, mas a parte difícil de "conferir no diretório" já vem feita no servidor.
- **A pista da garantia 3** ("cada um dos quatro sistemas reage de um jeito diferente à chamada repetida") somada à descrição detalhada de cada sistema (quem responde 409, quem tem `Idempotency-Key`, quem "não tem chave de idempotência") praticamente entrega a estratégia por sistema. O aluno só precisa perceber que a nuvem pede leitura antes de escrever. Eu tiraria a frase "e não tem chave de idempotência" da nuvem, ou a pista inteira.
- **`--sem-sensiveis` no verificador e o passo 5 dizendo exatamente quais acessos não podem existir** (`infraestrutura` e `deploy-producao`) fecham o desenho da aprovação antes de o aluno pensar nele.
- **"Os modos são `indisponivel` ... `grava_e_falha` ..." e o passo 8 com a configuração exata** tiram do aluno a tarefa de imaginar falhas. Para correção isso é bom; como exercício de engenharia, entrega o teste pronto.
- **O código base já tem `calcular_acessos` em `nimbus/estado.py`**, a mesma função que o avaliador usa. Um aluno pode importar e passar na garantia 1 sem escrever a política. O enunciado não proíbe (ver Atalhos).
- **"Uma chamada devolve quando o pedido conclui ou quando ele para esperando uma resposta humana"** fixa um modelo síncrono. Com a latência do plano gratuito, isso gera chamadas HTTP de minutos (ver Custo). Um contrato assíncrono (202 + consulta) seria uma escolha legítima do aluno e resolveria o problema.

## Onde faltou orientação

- **Números de cota.** Uma linha como "no plano gratuito, alguns modelos têm 20 requisições por dia; guarde cota para o fluxo do avaliador ou use um modelo para desenvolver e outro para validar" teria economizado a maior parte do tempo perdido, sem entregar solução.
- **Latência dos modelos no plano gratuito.** Um modelo levou 104 s para responder "ok". Vale avisar que a latência varia muito e que o aluno deve medir antes de escolher.
- **Que um `RequestInput` num ramo paralelo não bloqueia os ramos irmãos.** Uma frase como "no ADK 2, um nó que pede entrada humana pausa só o próprio ramo" apontaria o caminho sem dar o desenho.
- **Como montar a resposta de retomada fora do `adk web`** (`FunctionResponse` com `name="adk_request_input"` e o `id` da pendência). O curso mostra a retomada, mas pela interface; na API, o aluno precisa ler o código-fonte.
- **Que o `LlmAgent` com `output_schema` faz uma chamada a mais quando tem ferramentas** (via `set_model_response`). Isso muda a conta de cota.
- **Que o `output` do agente não chega ao `on_event_callback` do plugin.** Quem montar a trilha só no plugin vai procurar o pedido extraído e não achar.
- **Qual o universo a varrer no desligamento** (ver Pontos vagos). Uma frase como "considere os times e canais que aparecem na política" fecharia a dúvida.
- **O formato exato de `acessos.criados`.** O contrato mostra `["..."]`.

## Custo

- **Modelos**: comecei com `gemini-2.5-flash`, passei por `gemini-2.5-flash-lite` e `gemini-3.5-flash` e fiquei com `gemini-3-flash-preview`. Os motivos estão em Decisões e Travas.
- **Erros de cota:**
  - 09:57:17, passo 3 da 1ª tentativa do fluxo do avaliador: `429`, `GenerateRequestsPerDayPerProjectPerModel-FreeTier`, `gemini-2.5-flash`, limite 20.
  - 10:23, sonda manual: `gemini-2.5-flash-lite` também sem cota diária (limite 20).
  - Na 4ª tentativa: 7 respostas `429` por minuto (`GenerateRequestsPerMinutePerProjectPerModel-FreeTier`, `gemini-3-flash`, limite 5), todas absorvidas pelo `HttpRetryOptions`, só com custo de latência.
  - 10:28:24, passo 10 da 4ª tentativa: 14 respostas `429` diárias (`GenerateRequestsPerDayPerProjectPerModel-FreeTier`, `gemini-3-flash`, limite 20). O `HttpRetryOptions` tentou 5 vezes, o pedido terminou `falhou` e eu refiz o passo com outro modelo.
  - 503 pontual em `gemini-flash-latest` e `gemini-3.1-flash-lite` nas sondas.
- **Estimativa de chamadas ao modelo:**
  - desenvolvimento e testes: cerca de 20 no `2.5-flash`, cerca de 12 no `2.5-flash-lite`, cerca de 10 no `3.5-flash` e cerca de 8 no `3-flash-preview`, mais 10 sondas de 1 chamada;
  - fluxo do avaliador (4ª tentativa): 9 leituras × 2 = cerca de 18 chamadas de sucesso, mais as retentativas por 429;
  - total do dia: por volta de 80 chamadas.
- **Latência**: com `gemini-3-flash-preview`, uma leitura leva de 3 s a 40 s, conforme o 429 por minuto. Com `gemini-3.5-flash` no plano gratuito, 3 a 4 minutos.

## Atalhos

- **Importar `calcular_acessos` de `nimbus/estado.py`.** A garantia 1 passaria sem o aluno escrever a política. O critério "a lista de acessos é calculada em código a partir de `dados/politica.json`" seria cumprido ao pé da letra, reaproveitando o código do verificador. Não usei.
- **Não usar o agente para nada relevante.** Um regex resolve os textos do fluxo do avaliador ("time de X", "engenheir[oa] de Y", "plen[oa]|sênior|júnior"). Só a exigência de um agente com MCP impede isso, e o critério de aceite olha só `var/diretorio-consultas.log`, que o *código* também preenche. **Nenhum critério verifica que o agente chamou o MCP**: basta o código consultar.
- **Paralelismo sem grafo.** Um único nó com `asyncio.gather` para os quatro sistemas produz os mesmos intervalos sobrepostos no registro. O critério da garantia 4 olha só o registro, não o grafo.
- **Aprovação sem ramo paralelo.** Criar os comuns num nó e *depois* pedir a aprovação passa no passo 5 do mesmo jeito (os comuns existem quando a pendência aparece). A exigência "a admissão não para por causa disso" não tem verificação que a diferencie.
- **Idempotência da nuvem por limpeza posterior.** Criar sem cuidado e, antes de concluir, apagar as atribuições duplicadas com `GET` + `DELETE`. O estado final fica "uma atribuição por papel", mas houve duplicado no meio (o registro mostraria, mas o critério olha o consolidado).
- **Desligamento por força bruta.** `DELETE` em todos os times e canais da política, sem ler nada, passa nos passos 9 e 10, e o registro fica cheio de `nao_encontrado`.
- **Trilha sem plugin.** O critério não exige plugin nem hook: gravar a trilha dentro dos nós ou na API passa igual.
- **409 trivial.** Responder 409 sempre que `situacao != aguardando_resposta` passa no passo 7 sem nenhuma relação com idempotência de verdade.

## Análise crítica do desafio

**A dificuldade vem do conteúdo do módulo ou de acidente?** O núcleo é bom e é conteúdo do módulo: idempotência por sistema, RequestInput com retomada, grafo com junção, separar o determinístico do não determinístico. Mas, na prática, **mais da metade do esforço desta execução foi acidente**: cota diária de 20, latência de minutos, modelo devolvendo resposta vazia. O resto do "difícil" (ramo paralelo com RequestInput, retomada em outro processo, plugin sem ver a saída do agente) é comportamento do framework que só se descobre lendo o código-fonte do ADK. Para um aluno sem esse hábito, isso vira trava de horas.

**Algum requisito depende de sorte com o modelo?** Sim, dois:
- O passo 3 depende de o modelo **não** deduzir o time "Dados" de "engenheiro de dados". O código não tem como distinguir "o texto citou Dados" de "o modelo inventou Dados" sem voltar ao texto. Mitiguei pedindo o nome *citado* e instruindo, mas continua sendo o modelo.
- Os passos 2 a 10 dependem de o modelo mapear corretamente cargo e nível ("engenheira de software plena" → `engenheiro-de-software`/`pleno`). O `flash-lite` errou isso. O código só confere se o id existe, não se é o certo.

A cota é o outro fator de sorte: o fluxo do avaliador passa ou falha conforme quanto da cota diária sobrou.

**O enunciado se sustenta sozinho?** Quase. O contrato da API, o fluxo do avaliador e os sistemas simulados são claros, e o fluxo do avaliador é o melhor pedaço do texto. Faltam as informações de ambiente (cota, latência) e a clareza sobre quem confere no diretório e sobre o formato da resposta. Nenhuma dúvida me impediu de seguir, mas várias viraram decisões que um corretor pode julgar diferente.

**O tamanho está adequado?** Está no limite superior. São cinco garantias, a trilha, a API com contrato estrito, o README com linhas de código e 12 passos de verificação. Como desafio final de MBA, depois de um desafio anterior mais simples, o escopo é defensável. O que pesa não é o escopo, e sim a soma de acidentes. Estimo de 22 a 38 horas para um aluno médio, sem contar a espera por cota.

**O que eu cortaria e o que acrescentaria:**
- Cortaria a exigência de que a trilha registre "cada chamada aos sistemas". O registro do simulador já faz isso, e a trilha poderia ser sobre decisões (pedido, perguntas, aprovação).
- Cortaria as linhas exatas no README ("aponta arquivos e trechos que existem"): isso quebra a cada refatoração e mede pouco.
- Acrescentaria um critério que **diferencie** um grafo de verdade de um `gather` num nó só. Por exemplo: "com o chat indisponível por 10 chamadas, o e-mail, o GitHub e a nuvem terminam antes do chat" (visível no registro).
- Acrescentaria um passo com texto que tente induzir o modelo a inventar (por exemplo, "Admissão do Paulo, da equipe de infra") para testar de fato a garantia 1.
- Acrescentaria uma seção "Ambiente e cota" no enunciado, com números e com a recomendação de usar um modelo para desenvolver e outro para validar.
- Deixaria o contrato permitir um modo assíncrono (202 + GET), ou fixaria um tempo máximo por chamada.

## Notas

- **Clareza: 7/10.** O contrato, os sistemas simulados e o fluxo do avaliador são precisos, mas o texto cala sobre cota e latência (que decidem se dá para terminar) e deixa ambíguos quem confere no diretório e o formato das respostas.
- **Desafio: 8/10.** O núcleo exige entender de verdade idempotência, pausa humana num grafo paralelo e retomada depois do reinício, mas uma parte relevante da dificuldade é acidente de framework e de cota, e não conteúdo.
