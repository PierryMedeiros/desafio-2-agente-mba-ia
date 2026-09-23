# Esteira de acessos da Nimbus

API em Python com Google ADK 2 que recebe pedidos de admissão e de desligamento em texto livre, pergunta ao RH o que faltar, aplica a política de acessos em código, provisiona os quatro sistemas em paralelo, espera o gestor para o que é sensível e registra tudo numa trilha de auditoria.

A regra do projeto: o modelo lê o pedido, a política decide o acesso e o código garante que ele aconteça uma vez só.

## Arquitetura

### Visão geral

```
RH ──HTTP──> esteira/api.py (FastAPI :8000)
                 │  Runner + App(plugins=[TrilhaPlugin])
                 │  SqliteSessionService (var/sessoes-adk.db)  ← uma sessão por pedido
                 ▼
             Workflow "esteira_de_acessos" (esteira/workflow.py)
                 │                         │
     McpToolset (agente)            httpx (nós de código)
                 ▼                         ▼
   diretório MCP :8765/mcp        sistemas simulados :8100
   (e cliente MCP dos nós           e-mail, GitHub, chat, nuvem
    de conferência)
```

Cada pedido é uma sessão do ADK, e o id da sessão é o `pedido_id`. A API guarda a situação de cada pedido e a trilha em `var/esteira.db` (`esteira/banco.py`). As pendências são `RequestInput` do workflow; responder a uma pendência retoma o workflow com um `FunctionResponse` para o `adk_request_input` daquela pendência.

### O grafo do workflow

```
START ─> receber ─> interpretar (LlmAgent) ─> conferir
                                                 │
            ┌───────────── "faltando" ───────────┤
            ▼                                    │
      perguntar_rh (RequestInput) ─> receber     │   (laço com o RH)
                                                 │
            ┌───────────── "admissao" ───────────┤
            ▼                                    │
      calcular_acessos                           │
            ├─> provisionar_email  ─────┐        │
            ├─> provisionar_github ─────┤        │
            ├─> provisionar_chat   ─────┤        │
            ├─> provisionar_nuvem  ─────┼─> junta_admissao ─┐
            └─> aprovacao_gestor (RequestInput)             │
                   └─> provisionar_sensiveis ─┘             │
                                                            ├─> concluir
            ┌──────────── "desligamento" ────────┘          │
            ├─> revogar_email  ─────┐                       │
            ├─> revogar_github ─────┤                       │
            ├─> revogar_chat   ─────┼─> junta_desligamento ─┘
            └─> revogar_nuvem  ─────┘
```

Só `interpretar` usa o modelo. Todos os outros nós são funções Python (`FunctionNode`), determinísticas.

| Nó | Tipo | O que faz e por quê |
|---|---|---|
| `receber` | código | Monta o texto que o agente lê: o pedido original e cada pergunta e resposta trocada com o RH. O agente roda em modo `single_turn` e não enxerga o histórico da sessão, então tudo que ele precisa vai na entrada. |
| `interpretar` | `LlmAgent` com `McpToolset` e `output_schema` | Único ponto não determinístico. Transforma texto livre em `PedidoExtraido` (tipo, pessoa, time citado, cargo e nível), usando `listar_cargos` e as demais ferramentas do diretório para chegar aos ids. Não decide acesso. |
| `conferir` | código | Confere cada campo no diretório pelo MCP: resolve o time citado com `consultar_time`, valida cargo e nível com `listar_cargos`, e no desligamento acha a pessoa com `consultar_colaborador`. Calcula o e-mail pela regra 3. Se falta algo ou o diretório não reconhece o valor, a rota é `faltando`; senão, `admissao` ou `desligamento`. |
| `perguntar_rh` | código com `RequestInput` | Pausa o workflow com uma pendência `dado_faltante`. Na retomada, a resposta do RH volta para `receber`, e o agente relê tudo. Nada foi criado até aqui. |
| `calcular_acessos` | código | Aplica `dados/politica.json` a time e nível e separa comuns e sensíveis. |
| `provisionar_*` (4 nós) | código com `RetryConfig` | Um nó por sistema, em ramos paralelos do grafo. Cada um cria os acessos comuns daquele sistema de forma idempotente e emite um evento por chamada HTTP para a trilha. |
| `aprovacao_gestor` | código com `RequestInput` | Se o perfil tem sensíveis, pausa só este ramo com uma pendência `aprovacao` que identifica o gestor. Os quatro ramos de provisionamento seguem enquanto isso. Sem sensíveis, segue direto. |
| `provisionar_sensiveis` | código com `RetryConfig` | Com aprovação, cria os sensíveis no GitHub e na nuvem, em paralelo. Com recusa, termina sem criar nada e sem erro. |
| `junta_admissao` / `junta_desligamento` | `JoinNode` | Espera todos os ramos. O pedido só conclui quando todos terminaram. |
| `revogar_*` (4 nós) | código com `RetryConfig` | Um nó por sistema, em paralelo. Cada um descobre o que a pessoa tem naquele sistema e remove só o que é dela. |
| `concluir` | código | Consolida os acessos criados ou revogados e encerra o pedido. |

### Por que este desenho

- **Agente dentro do grafo, conferência fora dele.** O agente só extrai. O nó `conferir` valida contra o diretório de novo, em código, porque um valor inventado pelo modelo não pode seguir adiante só porque ele o escreveu com confiança. Para o time, o agente devolve só o nome citado (`time_citado`) e quem resolve o id é o código, via `consultar_time`. Assim, "Jurídico" nunca vira um time válido por aproximação.
- **Um nó por sistema, não um nó que chama os quatro.** O paralelismo fica visível no grafo e cada sistema tem a sua própria repetição: o chat indisponível repete só o ramo do chat.
- **A aprovação é um ramo paralelo, não uma etapa antes do provisionamento.** Os comuns ficam criados enquanto o gestor não responde, como pede a garantia 2.
- **`provisionar_sensiveis` separado de `aprovacao_gestor`.** O nó de aprovação tem `rerun_on_resume=False` (o padrão), então na retomada a decisão vira a saída dele sem rodar de novo. Quem age sobre a decisão é o nó seguinte, e o `JoinNode` sempre recebe os cinco ramos, com aprovação, recusa ou sem sensíveis.
- **Plugin para a trilha.** A auditoria fica num `BasePlugin` registrado no `App` e não depende de cada nó lembrar de registrar.
- **Modelo:** `gemini-2.5-flash-lite`, com `temperature=0` e sem *thinking* (`thinking_budget=0`), porque a tarefa é extração curta e não precisa de raciocínio. Cada leitura de pedido faz 2 chamadas ao modelo (`listar_cargos` e a resposta final), e o fluxo completo do avaliador faz cerca de 18. Comecei com `gemini-2.5-flash`, mas no plano gratuito ele tem só 20 requisições por dia por projeto, que acabaram durante o desenvolvimento. A cota é por modelo, e o `flash-lite` acertou os mesmos casos. A chamada usa `HttpRetryOptions` para esperar e repetir quando o plano gratuito devolve 429 por minuto. O modelo pode ser trocado por `ESTEIRA_MODELO`.

### Limitações do framework encontradas e como contornei

- **Saída do `LlmAgent` não chega ao plugin.** Quando o agente com `output_schema` termina, o Runner limpa `event.output` do evento (a saída é a própria mensagem do modelo, `message_as_output`) antes de chamar `on_event_callback`. Contorno: `conferir` devolve o que recebeu do agente no campo `extraido`, e a trilha registra o pedido extraído a partir da saída de `conferir` (`esteira/trilha.py`, no ramo `if no == "conferir"`).
- **`RequestInput` descarta o `state` do nó.** Um `FunctionNode` que devolve `RequestInput` não leva junto o `state_delta`. Contorno: a pergunta pendente é gravada no estado pelo nó anterior (`conferir`), que emite um evento de saída comum.
- **A contagem de repetições do `RetryConfig` não persiste na retomada** (o próprio ADK avisa no log). Não afeta este desenho, porque os nós que repetem nunca ficam esperando humano.
- **Tool Confirmation não funciona dentro de workflow**, como visto no curso. A aprovação do gestor usa `RequestInput` num nó de código, e não a confirmação de ferramenta.

## Garantias

### Garantia 1: quem decide acesso é a política

- `esteira/politica.py`, `acessos_da_politica` (linhas 28 a 42): soma `todos`, `por_time[time]` e `por_nivel[nivel]` de `dados/politica.json` e separa o que está em `sensiveis`.
- `esteira/workflow.py`, `calcular_acessos` (linhas 188 a 194): é o único lugar que produz a lista de acessos, a partir de time e nível já conferidos no diretório.
- `esteira/workflow.py`, `conferir` (linhas 111 a 182): time, cargo e nível só seguem se existirem no diretório, consultado pelo MCP (`esteira/diretorio.py`).

**Por que não depende do modelo:** o agente não tem ferramenta que crie acesso, e o `output_schema` dele (`esteira/agente.py`, `PedidoExtraido`) não tem campo de acesso. Ele só devolve time, cargo e nível, e esses valores ainda são conferidos no diretório. Qualquer que seja o texto, os acessos vêm de uma função pura sobre a política.

### Garantia 2: nada sensível sem o gestor

- `esteira/workflow.py`, `aprovacao_gestor` (linhas 244 a 260): se há sensíveis, emite um `RequestInput` com o gestor do time (vindo do diretório via `consultar_time`) e a lista dos sensíveis.
- `esteira/workflow.py`, `_no_sensiveis` / `provisionar_sensiveis` (linhas 263 a 293): cria os sensíveis só quando a resposta é `{"aprovado": true}`; com recusa, termina com lista vazia e sem erro.
- `esteira/workflow.py`, `criar_workflow` (linhas 329 em diante): `aprovacao_gestor` é um ramo paralelo aos quatro `provisionar_*`, então os comuns são criados enquanto a decisão não chega.
- `esteira/api.py`, `responder` (linhas 133 a 163): só aceita a resposta se `pendencia_id` for a pendência atual (senão, `409`) e valida o formato `{"aprovado": bool}`. A pendência é consumida antes de retomar, então uma segunda resposta igual recebe `409`.
- Reinício: sessões em `SqliteSessionService` (`esteira/api.py`, linhas 35 a 41) e pedidos em `var/esteira.db` (`esteira/banco.py`). Depois do reinício, o workflow reconstrói o que já rodou a partir dos eventos da sessão e só executa o que falta.

**Por que não depende do modelo:** a necessidade de aprovação vem do bloco `sensiveis` da política, e a decisão vem da API. O modelo não participa de nenhuma das duas.

### Garantia 3: cada acesso acontece uma vez só

`esteira/sistemas.py` tem uma estratégia por sistema (a docstring do topo resume):

- e-mail, `criar_email` (linha 93): `409` na criação é sucesso ("já existe"), então repetir depois de um `504` que gravou não duplica.
- GitHub, `criar_github` (linha 105): `PUT` idempotente.
- chat, `criar_chat` (linhas 126 a 139): consulta o canal antes e envia `Idempotency-Key` = `pedido_id:canal:email`. A repetição de uma chamada que gravou devolve `200` com o registro anterior.
- nuvem, `criar_nuvem` (linhas 162 a 170): sem chave de idempotência, então cada tentativa começa com `GET /nuvem/papeis?email=` e só cria os papéis que ainda não existem. A atribuição gravada por uma chamada que respondeu `504` aparece nessa leitura e não é refeita.
- Repetição: `esteira/workflow.py`, `REPETICAO` (linha 35), um `RetryConfig` do ADK em cada nó de sistema, com espera exponencial e até 8 tentativas. Como toda operação acima é idempotente, repetir o nó inteiro é seguro. `em_paralelo` (`esteira/sistemas.py`, linha 78) espera todas as chamadas do nó terminarem antes de propagar a falha, para não cancelar no meio uma escrita que o servidor já aplicou.

**Por que não depende do modelo:** o modelo roda antes de qualquer escrita e não participa das chamadas aos sistemas. A idempotência está em código, por sistema.

### Garantia 4: os quatro sistemas em paralelo

- `esteira/workflow.py`, `criar_workflow` (linhas 329 em diante): `calcular_acessos` abre em leque para `provisionar_email`, `provisionar_github`, `provisionar_chat` e `provisionar_nuvem` (mais `aprovacao_gestor`), e `junta_admissao` é um `JoinNode` que espera todos. No desligamento, o mesmo com `revogar_*` e `junta_desligamento`.
- Dentro de cada nó, as chamadas de um mesmo sistema (três canais, vários papéis) também saem juntas, com `asyncio.gather`.

**Por que não depende do modelo:** o paralelismo é estrutura do grafo. O `Workflow` agenda como tarefas `asyncio` todos os nós com gatilho pronto, e `GET /admin/registro` mostra as escritas nos quatro sistemas começando no mesmo instante.

### Garantia 5: desligamento não deixa sobra

- `esteira/sistemas.py`, `revogar_email`, `revogar_github`, `revogar_chat`, `revogar_nuvem` (linhas 97 a 181): cada um descobre o que a pessoa tem (lista de membros dos times e canais que a política conhece, atribuições da nuvem filtradas pelo e-mail) e remove só o que é dela. `404` na remoção é sucesso, porque o acesso já não existe.
- `esteira/politica.py`, `universo_da_politica` (linha 45): todos os times do GitHub e canais da política, inclusive os sensíveis, para a revogação não depender do time atual da pessoa.
- `esteira/workflow.py`, `REPETICAO`: um sistema fora do ar faz o nó repetir, e como a próxima tentativa relê o estado, ela só remove o que ainda sobra.
- A pessoa do desligamento vem do diretório (`consultar_colaborador`), e todo `DELETE` é endereçado pelo e-mail dela ou pelo id de uma atribuição dela. Nenhum acesso de outra pessoa é tocado.

**Por que não depende do modelo:** o modelo só identifica o nome, conferido depois no diretório. O que é revogado vem da leitura dos sistemas.

### Trilha de auditoria

- `esteira/trilha.py`, `TrilhaPlugin`: `on_event_callback` grava o pedido extraído pelo agente, o pedido estruturado, as perguntas ao RH, o pedido de aprovação, os acessos calculados, cada chamada aos sistemas (evento com `custom_metadata`) e a conclusão. `on_user_message_callback` grava as respostas do RH e a decisão do gestor. `after_tool_callback` grava as consultas do agente ao diretório.
- `esteira/banco.py`: a trilha fica em SQLite (`var/esteira.db`) e continua disponível depois do reinício. `GET /pedidos/{id}/trilha` devolve os itens em ordem, cada um com `horario`, `etapa` e `detalhe`.

## Como rodar

### Pré-requisitos

- Python 3.12 ou superior e [uv](https://docs.astral.sh/uv/).
- Uma chave do Google AI Studio (Gemini).

### Variáveis do `.env`

```
cp .env.example .env
```

| Variável | Obrigatória | Valor |
|---|---|---|
| `GOOGLE_API_KEY` | sim | chave do Google AI Studio |
| `GOOGLE_GENAI_USE_VERTEXAI` | não | `FALSE` (ou vazio) para usar o AI Studio |
| `ESTEIRA_MODELO` | não | modelo do agente; padrão `gemini-2.5-flash-lite` |
| `NIMBUS_SISTEMAS_URL` | não | padrão `http://localhost:8100` |
| `NIMBUS_DIRETORIO_URL` | não | padrão `http://localhost:8765/mcp` |

### Subir tudo

Na raiz do projeto, em três terminais:

```
uv sync
uv run nimbus-sistemas     # terminal 1: sistemas simulados em http://localhost:8100
uv run nimbus-diretorio    # terminal 2: diretório MCP em http://localhost:8765/mcp
uv run esteira-api         # terminal 3: a API em http://localhost:8000
```

A API guarda sessões, pedidos e trilha em `var/`. Para parar, use Ctrl+C; para voltar, rode `uv run esteira-api` de novo, e as pendências continuam de onde pararam. Para começar do zero, apague `var/esteira.db` e `var/sessoes-adk.db` com a API parada.

### Exemplo

```
curl -s -X POST localhost:8000/pedidos -H 'content-type: application/json' \
  -d '{"texto": "Admissão da Carla Mendes, engenheira de software plena no time de Risco, início em 10/03."}'

curl -s localhost:8000/pedidos/<pedido_id>
curl -s localhost:8000/pedidos/<pedido_id>/trilha

curl -s -X POST localhost:8000/pedidos/<pedido_id>/respostas -H 'content-type: application/json' \
  -d '{"pendencia_id": "<id>", "resposta": {"texto": "É do time de Dados"}}'
```

### Contrato

- `POST /pedidos` → `201`; `POST /pedidos/{id}/respostas` → `200`, `409` para pendência inexistente e `422` para resposta fora do formato; `GET /pedidos/{id}` → `200`; `GET /pedidos/{id}/trilha` → `200`. Rotas com `{pedido_id}` respondem `404` quando o pedido não existe.
- Todas as rotas de pedido devolvem o mesmo formato: `pedido_id`, `situacao`, `pendencia`, `pedido` e `acessos`.
- A pendência de aprovação traz `gestor` (`id`, `nome`, `email`) e `acessos_sensiveis`.
- Durante o processamento de uma chamada, o pedido fica internamente como `em_andamento`. A chamada só devolve quando ele está em `aguardando_resposta`, `concluido` ou `falhou`.
