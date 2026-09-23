# Acesso na medida: a esteira de acessos da Nimbus

Na Nimbus, toda admissão vira uma maratona manual. Alguém do RH avisa que a pessoa entra na semana que vem, e o time de plataforma sai criando conta de e-mail, adicionando em time do GitHub, jogando em canais do chat e atribuindo papéis na nuvem. No desligamento, a mesma maratona ao contrário, com um detalhe pior: o que passa despercebido vira um ex-funcionário com acesso ativo.

A empresa quer automatizar isso com um agente que entenda o pedido do RH escrito em português. A área de segurança aprovou com duas condições. A primeira é que o modelo pode ler o pedido, mas quem decide o que cada pessoa recebe é a política de acessos. A segunda é que os sistemas da Nimbus caem, demoram e às vezes gravam e respondem erro, e nada disso pode virar acesso duplicado ou acesso esquecido.

Em uma frase: construa com Google ADK a esteira de acessos da Nimbus, em que um pedido em texto livre vira exatamente os acessos previstos na política, criados uma única vez, com aprovação humana para o que é sensível.

## Objetivo

Entregar, num fork público do repositório base:

- uma API em Python que recebe pedidos de admissão e de desligamento em texto livre e segue o contrato deste enunciado;
- um agente que interpreta o pedido, com o diretório da empresa consultado pelo servidor MCP;
- um workflow que aplica a política em código, provisiona nos quatro sistemas em paralelo e espera aprovação do gestor para o que é sensível;
- uma trilha de auditoria por pedido;
- um README com a arquitetura, o lugar de cada garantia no código e como rodar.

## O ponto de partida

O repositório base não traz nenhum agente, workflow ou API, e esse vácuo é proposital: isso é a sua entrega. Ele traz o mundo ao redor, que o avaliador usa na correção.

Repositório base: https://github.com/devfullcycle/REPO-A-DEFINIR

Os dados:

- `dados/politica.json`: o que cada pessoa recebe. A soma de `todos`, do bloco do time em `por_time` e do bloco do nível em `por_nivel`. O bloco `sensiveis` marca quais acessos exigem aprovação.
- `dados/diretorio.json`: times com seus gestores, cargos, níveis e os colaboradores já ativos.

Os serviços, que sobem com dois comandos e ficam no ar durante a correção:

```
uv sync
uv run nimbus-sistemas     # sistemas simulados em http://localhost:8100
uv run nimbus-diretorio    # diretório da empresa em http://localhost:8765/mcp
```

O diretório responde apenas por MCP, somente leitura, com as ferramentas `listar_times`, `consultar_time`, `listar_cargos` e `consultar_colaborador`. Cada consulta é registrada em `var/diretorio-consultas.log`.

Os quatro sistemas simulados, cada um com um jeito próprio de lidar com a chamada repetida:

- E-mail: `POST /email/contas` responde `201` na primeira vez e `409` se a conta já existe. `DELETE /email/contas/{email}` responde `204` ou `404`. `GET /email/contas` lista.
- GitHub: `PUT /github/times/{time}/membros/{email}` responde sempre `200`, com `ja_era_membro` indicando se já estava lá. `DELETE` do mesmo caminho responde sempre `204`. `GET /github/times/{time}/membros` lista.
- Chat: `POST /chat/canais/{canal}/membros` cria um registro novo a cada chamada, e aceita o cabeçalho `Idempotency-Key`, que faz a chamada repetida devolver `200` com o registro anterior. `DELETE /chat/canais/{canal}/membros/{email}` remove todos os registros daquele e-mail no canal. `GET` lista, inclusive os repetidos.
- Nuvem: `POST /nuvem/papeis` cria uma atribuição nova a cada chamada, com id próprio, e não tem chave de idempotência. `GET /nuvem/papeis?email=...` lista e `DELETE /nuvem/papeis/{id}` remove uma atribuição.

As rotas administrativas, usadas para preparar cenários e conferir resultados:

- `POST /admin/reset` devolve os sistemas ao estado inicial e limpa o registro.
- `POST /admin/falhas` liga falhas por sistema, por um número de chamadas. Os modos são `indisponivel` (responde `503` sem efeito nenhum), `grava_e_falha` (aplica o efeito e responde `504`), `lento` e `nenhum`. Eles valem para as chamadas de escrita, inclusive as de remoção, e não afetam as consultas.
- `GET /admin/registro` traz todas as chamadas, com horário de início e fim, status e efeito (`criado`, `ja_existia`, `duplicado`, `removido`, `nao_encontrado` ou `nenhum`).
- `GET /admin/estado?email=...` traz o consolidado de uma pessoa, com a contagem de registros por canal e de atribuições por papel.

O verificador compara o estado de uma pessoa com o que a política manda e sai com código 0 quando está tudo certo:

```
uv run nimbus-verificar --pessoa carla.mendes@nimbus.dev --time risco --cargo engenheiro-de-software --nivel pleno
uv run nimbus-verificar --pessoa marcos.vieira@nimbus.dev --desligado
```

Cada escrita nos sistemas leva cerca de 800 ms de propósito, para dar para enxergar no registro se o provisionamento foi em paralelo ou em fila.

## Tecnologias obrigatórias e restrições

- Python 3.12 ou superior, com o projeto gerenciado por uv. O `pyproject.toml` já existe: adicione suas dependências nele.
- Google ADK na série 2, na versão 2.2.0 (a do curso) ou mais nova, com a versão exata fixada.
- Modelos Gemini, com chave do Google AI Studio. O modelo de cada agente é escolha sua: consulte os limites ativos do seu projeto no próprio Google AI Studio. Como ordem de grandeza, o fluxo do avaliador faz algumas dezenas de chamadas ao modelo.
- As pastas `dados/`, `nimbus/` e `testes/` não podem ser alteradas, e o código da sua solução não importa nada de `nimbus/`: aquele pacote é o mundo externo, não biblioteca. Os serviços simulados sobem com os comandos acima, na configuração padrão.
- A sua API responde em `http://localhost:8000` e sobe com um comando documentado no README.
- O diretório da empresa é consultado pelo servidor MCP, nunca lendo `dados/diretorio.json` direto.
- Nenhuma chave de API versionada: o `.env` fica fora do Git e o `.env.example` é versionado com os nomes das variáveis e sem nenhum segredo.
- Se esbarrar em uma limitação do framework, documente no README o que encontrou e como contornou, em vez de abandonar a garantia.

## Regras de negócio

1. Na admissão, a pessoa recebe exatamente os acessos que a política dá para o time e o nível dela, somando os três blocos.
2. Acesso marcado como sensível só é criado depois que o gestor do time aprova. Se ele recusar, o pedido termina com os demais acessos criados.
3. O endereço de e-mail é o primeiro nome e o último sobrenome, em minúsculas, sem acentos, separados por ponto, seguidos de `@nimbus.dev`.
4. No desligamento, a pessoa fica sem nenhum acesso nos quatro sistemas, e ninguém mais é afetado.
5. O pedido do RH chega em texto livre e pode vir incompleto ou citar time, cargo ou nível que não existem no diretório. Nesses casos o fluxo pergunta ao RH.
6. Um pedido concluído não cria nem revoga nada duas vezes, independente de quantas tentativas foram necessárias.

## Requisitos

### 1. O agente que lê o pedido

Conceitos do curso: agentes, output schema e MCP.

O agente transforma o texto do RH em um pedido estruturado: o tipo (admissão ou desligamento), a pessoa e, na admissão, o time, o cargo e o nível. Time, cargo e nível são conferidos no diretório, e no desligamento a pessoa também. Essa conferência pode ser feita pelo agente ou por código, desde que passe pelo servidor MCP. Quando falta um dado, ou quando o dado não existe no diretório, o fluxo para e pergunta ao RH, sem inventar valor e sem criar nada antes da resposta.

### 2. Garantia 1: quem decide acesso é a política

Conceitos do curso: nós de código no workflow e a diferença entre o que é determinístico e o que não é.

A lista de acessos de cada pessoa sai de `dados/politica.json`, aplicada em código a partir do time e do nível. O modelo não escolhe acesso, não acrescenta e não remove. Ao final de uma admissão, a pessoa tem exatamente os acessos previstos, fora os sensíveis recusados.

### 3. Garantia 2: nada sensível sem o gestor

Conceitos do curso: RequestInput no workflow e retomada pela API.

Os acessos marcados como sensíveis ficam pendentes até o gestor daquele time responder pela API, e a pendência diz quem é esse gestor. A admissão não para por causa disso: os acessos que não são sensíveis são criados enquanto a decisão não chega. Se o gestor aprovar, os sensíveis entram; se recusar, o pedido termina sem eles e sem erro. Enquanto a espera dura, o pedido sobrevive a um reinício da API e continua de onde parou.

### 4. Garantia 3: cada acesso acontece uma vez só

Conceitos do curso: idempotência, tratamento de erros e logging.

Os sistemas da Nimbus falham. Um fica indisponível por algumas chamadas e outro aplica o efeito e responde erro mesmo assim. O pedido precisa concluir apesar disso, sem acesso faltando no fim e sem acesso criado duas vezes no caminho: nenhuma chamada no registro dos sistemas pode ter efeito `duplicado`. Criar o repetido e limpar depois não vale.

### 5. Garantia 4: os quatro sistemas em paralelo

Conceitos do curso: o grafo do workflow, com ramos paralelos e junção.

Uma admissão não pode atender um sistema de cada vez. Os quatro são atendidos em paralelo e o pedido só conclui quando todos terminam. No registro, as chamadas a sistemas diferentes aparecem com intervalos que se sobrepõem.

Aqui o desafio passa do que as aulas mostram: o curso cita fluxos paralelos e retentativa, mas o projeto das aulas não usa nenhum dos dois. Montar o ramo paralelo, a junção e a política de repetição faz parte da pesquisa.

### 6. Garantia 5: desligamento não deixa sobra

Conceitos do curso: roteamento no grafo e idempotência.

O desligamento revoga todos os acessos da pessoa nos quatro sistemas, inclusive os sensíveis, considerando os times e os canais que aparecem na política. Se um sistema estiver fora do ar, o fluxo insiste até concluir. Acesso de outra pessoa não é tocado.

### 7. A trilha de auditoria

Conceitos do curso: hooks e plugins.

Toda mudança de acesso precisa se explicar depois. Cada pedido tem uma trilha consultável pela API com o pedido estruturado que o agente extraiu, as perguntas feitas ao RH e as respostas recebidas, a decisão do gestor quando houve, e cada chamada aos sistemas com o resultado. A trilha continua disponível depois de reiniciar a API.

### 8. A API

Conceitos do curso: Runner, App, execução personalizada e aplicação web com sessões.

A API segue exatamente o contrato abaixo, porque a correção é feita por ele. Uma chamada devolve quando o pedido conclui ou quando ele para esperando uma resposta humana.

## Contrato da API

Todas as rotas recebem e devolvem JSON. As rotas com `{pedido_id}` respondem `404` quando o pedido não existe.

Abrir um pedido:

```
POST /pedidos
{"texto": "Admissão do Rodrigo Salles como analista de produto pleno, começa semana que vem"}

201
{
  "pedido_id": "...",
  "situacao": "aguardando_resposta",
  "pendencia": {
    "id": "...",
    "tipo": "dado_faltante",
    "mensagem": "Qual é o time do Rodrigo Salles?"
  }
}
```

As três rotas devolvem sempre o mesmo objeto, com os cinco campos do exemplo de `GET /pedidos/{pedido_id}` abaixo. O exemplo acima mostra só os três primeiros para encurtar.

`situacao` é `aguardando_resposta`, `concluido` ou `falhou`. `pendencia` é `null` quando não há nada esperando. `tipo` é `dado_faltante` ou `aprovacao`. Numa pendência de aprovação, a pendência traz também o gestor responsável e os acessos sensíveis em questão, nos campos que você escolher. Os itens de `criados` e `revogados` têm formato livre, desde que identifiquem o sistema e o recurso.

Responder uma pendência:

```
POST /pedidos/{pedido_id}/respostas
{"pendencia_id": "...", "resposta": {"texto": "É do time de Dados"}}

200  mesmo objeto da rota de pedidos
409  não existe pendência com esse id nesse pedido
```

Numa pendência de aprovação, a resposta é `{"aprovado": true}` ou `{"aprovado": false}`.

Consultar um pedido:

```
GET /pedidos/{pedido_id}

200
{
  "pedido_id": "...",
  "situacao": "concluido",
  "pendencia": null,
  "pedido": {"tipo": "admissao", "pessoa": "Carla Mendes", "time": "risco", "cargo": "engenheiro-de-software", "nivel": "pleno"},
  "acessos": {"criados": ["..."], "revogados": []}
}
```

Consultar a trilha:

```
GET /pedidos/{pedido_id}/trilha

200  lista em ordem, cada item com horário, etapa e detalhe
```

## Fora de escopo

- Interface visual: a entrega é só a API.
- Autenticação: quem chama a API é o RH, e a resposta do gestor chega pela mesma rota.
- Mudança de time, cargo ou nível de quem já está na empresa.
- Readmitir alguém que já foi desligado, ou admitir quem já está ativo no diretório.
- Reinício da API no meio da criação dos acessos. O reinício só é testado enquanto o pedido espera uma resposta humana.
- Notificação real para as pessoas envolvidas.
- Dois pedidos processados ao mesmo tempo: o avaliador abre um pedido por vez.
- Tom e redação das mensagens, fora os pontos citados no fluxo do avaliador.
- Testes automatizados, avaliações (evals) e deploy.

## Fluxo do avaliador

O avaliador pode variar a redação dos pedidos e responder o que for preciso para completar um fluxo. As verificações olham o estado dos sistemas simulados, o registro de chamadas e a trilha, e não o texto das respostas.

**1.** Em um clone limpo do fork, copia o `.env.example` para `.env`, preenche a chave, roda `uv sync` e sobe os dois serviços da Nimbus e a API, como descrito no README. Chama `POST /admin/reset` e confere que `GET /admin/estado?email=marcos.vieira@nimbus.dev` traz os acessos iniciais dele.

**2.** Abre o pedido `Admissão da Carla Mendes, engenheira de software plena no time de Risco, início em 10/03.`. Confere que o pedido conclui sem nenhuma pendência, que `uv run nimbus-verificar --pessoa carla.mendes@nimbus.dev --time risco --cargo engenheiro-de-software --nivel pleno` sai com código 0 e que, em `GET /admin/registro`, existem chamadas a sistemas diferentes com intervalos sobrepostos.

**3.** Abre o pedido `Admissão do Rodrigo Salles como analista de produto pleno, começa semana que vem.`, que não diz o time. Confere que a situação é `aguardando_resposta` com pendência do tipo `dado_faltante` e que `GET /admin/estado?email=rodrigo.salles@nimbus.dev` não traz nenhum acesso.

**4.** Responde a pendência com `É do time Jurídico`, que não existe no diretório. Confere que o pedido continua esperando resposta e que nada foi criado. Responde com `É do time de Dados` e confere que o pedido conclui e que o verificador do Rodrigo, com time `dados`, cargo `analista-de-produto` e nível `pleno`, sai com código 0.

**5.** Abre o pedido `Admissão da Beatriz Nunes, engenheira de software sênior no time de Plataforma, entra dia 01/04.`. Confere que a situação é `aguardando_resposta` com pendência do tipo `aprovacao`, que a pendência identifica Sofia Arantes como gestora, que os acessos não sensíveis da Beatriz já existem e que `infraestrutura` no GitHub e `deploy-producao` na nuvem ainda não.

**6.** Responde a pendência com `{"aprovado": false}`. Confere que o pedido conclui e que o verificador da Beatriz, com `--sem-sensiveis`, sai com código 0.

**7.** Abre o pedido `Admissão do Tiago Prado, engenheiro de software sênior no time de Plataforma.` e espera a pendência de aprovação. Para a API com Ctrl+C e sobe de novo com o mesmo comando. Confere que `GET /pedidos/{id}` ainda mostra a pendência, responde `{"aprovado": true}` e confere que o verificador do Tiago, sem a flag, sai com código 0. Envia a mesma resposta de novo e confere que ela recebe `409` e que nada muda.

**8.** Liga as falhas com `POST /admin/falhas` e o corpo `{"chat": {"modo": "indisponivel", "vezes": 3}, "nuvem": {"modo": "grava_e_falha", "vezes": 1}}`. Abre o pedido `Admissão da Renata Duarte, analista de produto júnior no time de Pagamentos.`. Confere que o pedido conclui, que o verificador da Renata sai com código 0 que `GET /admin/estado?email=renata.duarte@nimbus.dev` mostra um registro por canal e uma atribuição por papel, e que nenhuma chamada do registro tem efeito `duplicado`.

**9.** Desliga as falhas com `POST /admin/falhas` e o corpo `{"chat": {"modo": "nenhum"}, "nuvem": {"modo": "nenhum"}}`. Abre o pedido `Desligamento do Marcos Vieira, último dia 30/04.`. Confere que o pedido conclui, que `uv run nimbus-verificar --pessoa marcos.vieira@nimbus.dev --desligado` sai com código 0 e que os acessos da Priscila Alencar continuam intactos.

**10.** Liga a falha `{"email": {"modo": "indisponivel", "vezes": 2}}` e abre o pedido `Desligamento da Priscila Alencar.`. Confere que o pedido conclui e que o verificador dela, com `--desligado`, sai com código 0.

**11.** Consulta `GET /pedidos/{id}/trilha` do pedido do Tiago e confere que ela traz o pedido estruturado, a decisão do gestor e as chamadas aos sistemas com o resultado de cada uma. Confere também que `var/diretorio-consultas.log` tem consultas ao diretório.

**12.** Confere no repositório: a versão exata do ADK fixada; `dados/`, `nimbus/` e `testes/` idênticos aos do repositório base; nenhuma chave versionada; a lista de acessos calculada em código a partir de `dados/politica.json`, sem o modelo escolher e sem importar nada de `nimbus/`; o diretório consultado pelo MCP; e o README com as seções pedidas, apontando arquivos e trechos que existem.

Do ambiente limpo ao último desligamento, as cinco garantias precisam ficar de pé em todos os passos. Se qualquer verificação falhar, a entrega está incompleta.

## Critérios de aceite

Execução e entrega

☐ `uv sync` instala o projeto sem erro, com a versão exata do ADK fixada, na série 2 e igual ou superior à 2.2.0 (passos 1 e 12).
☐ Os comandos do README sobem a API em `http://localhost:8000` com os serviços da Nimbus no ar (passo 1).
☐ As pastas `dados/`, `nimbus/` e `testes/` estão idênticas às do repositório base (passo 12).
☐ Nenhuma chave de API está versionada, o `.env` não está no repositório e o `.env.example` lista as variáveis (passo 12).

O agente e o diretório

☐ Um pedido completo vira pedido estruturado e conclui sem pendência (passo 2).
☐ Um pedido sem o time gera pendência ao RH e nada é criado até a resposta (passo 3).
☐ Um time que não existe no diretório gera nova pergunta em vez de chute (passo 4).
☐ As consultas ao diretório aparecem em `var/diretorio-consultas.log` (passo 11).
☐ O diretório é consultado pelo MCP, e não pela leitura direta do arquivo (passo 12).

Garantia 1: quem decide acesso é a política

☐ O verificador sai com código 0 ao final de cada admissão (passos 2, 4, 7 e 8).
☐ A lista de acessos é calculada em código a partir de `dados/politica.json`, sem importar nada de `nimbus/` (passo 12).

Garantia 2: nada sensível sem o gestor

☐ Perfil com acesso sensível fica aguardando o gestor, com os não sensíveis criados e os sensíveis ausentes (passo 5).
☐ A pendência de aprovação identifica o gestor do time (passo 5).
☐ Recusa conclui o pedido sem os sensíveis, e o verificador com `--sem-sensiveis` sai com código 0 (passo 6).
☐ A pendência sobrevive ao reinício da API, e a aprovação depois dele cria os sensíveis (passo 7).
☐ Responder de novo a mesma pendência recebe `409` e não muda nada (passo 7).

Garantia 3: cada acesso acontece uma vez só

☐ Com o chat indisponível e a nuvem gravando antes de falhar, a admissão conclui (passo 8).
☐ O consolidado mostra um registro por canal e uma atribuição por papel, sem duplicados (passo 8).
☐ Nenhuma chamada do registro tem efeito `duplicado`, nem durante o processo (passo 8).

Garantia 4: os quatro sistemas em paralelo

☐ No registro, chamadas a sistemas diferentes têm intervalos sobrepostos (passo 2).

Garantia 5: desligamento não deixa sobra

☐ O desligamento deixa a pessoa sem nenhum acesso e o verificador com `--desligado` sai com código 0 (passo 9).
☐ Os acessos de outras pessoas continuam intactos (passo 9).
☐ Com um sistema fora do ar, o desligamento ainda conclui sem sobra (passo 10).

Trilha de auditoria

☐ A trilha traz o pedido estruturado, a decisão do gestor e cada chamada aos sistemas com o resultado (passo 11).
☐ A trilha continua disponível depois do reinício da API (passos 7 e 11).

Contrato e README

☐ Todas as rotas seguem o contrato: caminhos, campos, formatos e códigos de status (passos 2 a 11).
☐ O README tem as seções Arquitetura, Garantias e Como rodar, e a seção Garantias aponta arquivos e trechos que existem no repositório (passo 12).

## Entregável

- Link do fork público do repositório base, com tudo na branch `main`.
- `README.md` na raiz, substituindo este enunciado.

O README tem três seções. Arquitetura descreve o grafo do workflow, cada nó e cada agente, com o motivo de cada escolha. Garantias mostra, para cada uma das cinco, o arquivo e o trecho do código que a implementam e por que ela não depende do que o modelo decide. Como rodar traz os pré-requisitos, as variáveis do `.env`, os comandos para subir os serviços da Nimbus e a sua API.

## Dicas finais

Comece escolhendo o modelo com calma, porque é ali que mora o tropeço mais caro deste desafio. No plano gratuito o limite é diário e por modelo, e ele acaba rápido: se você desenvolver e validar com o mesmo modelo no mesmo dia, corre o risco de ficar sem cota no meio do fluxo do avaliador. Vale usar um modelo para desenvolver e outro para validar. Meça também a latência antes de decidir, porque ela varia muito entre modelos e uma chamada pode levar minutos. E desconfie dos modelos menores: eles trocam cargo e nível e às vezes devolvem resposta vazia depois de chamar uma ferramenta.

Três comportamentos do ADK que as aulas não mostram e que economizam horas. Um nó que espera resposta humana pausa apenas o próprio ramo, e os ramos irmãos seguem até o fim. Para devolver essa resposta fora do adk web, a documentação oficial e o código-fonte do próprio ADK mostram como um cliente responde a uma pausa pendente. E a saída de um agente não chega ao plugin como saída de nó, então uma trilha montada só pelo plugin pode não enxergar o pedido extraído.

Quando um acesso duplicar, não adivinhe onde foi: `GET /admin/registro` mostra cada tentativa com o efeito real, inclusive a chamada que gravou antes de responder erro. O mesmo registro denuncia provisionamento em fila, porque cada escrita leva cerca de 800 ms de propósito. Os dois serviços da Nimbus sobem em terminais separados e a partir da raiz do projeto, e o endereço do diretório termina em `/mcp`.

E a filosofia do desafio cabe em uma frase: o modelo lê o pedido, a política decide o acesso e o código garante que ele aconteça uma vez só.