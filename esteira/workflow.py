"""O workflow da esteira de acessos.

    START -> receber -> interpretar (agente) -> conferir
    conferir --faltando-->     perguntar_rh -> receber            (laço com o RH)
    conferir --admissao-->     calcular_acessos
    calcular_acessos --> provisionar_email | provisionar_github
                         | provisionar_chat | provisionar_nuvem   (paralelo)
                         | aprovacao_gestor -> provisionar_sensiveis
    (os cinco ramos) --> junta_admissao -> concluir
    conferir --desligamento--> revogar_email | revogar_github
                               | revogar_chat | revogar_nuvem     (paralelo)
    (os quatro ramos) --> junta_desligamento -> concluir

Só `interpretar` usa o modelo. Todo o resto é nó de código.
"""

import re
import unicodedata
from typing import Any

from google.adk.agents.context import Context
from google.adk.events import Event, RequestInput
from google.adk.workflow import FunctionNode, JoinNode, RetryConfig, Workflow
from google.genai import types
from pydantic import BaseModel

from esteira import diretorio, sistemas
from esteira.agente import criar_agente
from esteira.politica import acessos_da_politica, descrever, email_corporativo, tem_sensiveis
from esteira.sistemas import Chamadas
from esteira.trilha import CHAVE_CHAMADA

# Garantia 3 e 5: um sistema fora do ar é repetido com espera crescente. Como
# toda operação em `sistemas.py` é idempotente, repetir o nó é seguro.
REPETICAO = RetryConfig(max_attempts=8, initial_delay=0.5, max_delay=5.0, backoff_factor=2.0, jitter=0.2)


class RespostaRH(BaseModel):
    texto: str


class DecisaoGestor(BaseModel):
    aprovado: bool


# Entrada e conversa com o RH


def _texto(conteudo: Any) -> str:
    if isinstance(conteudo, types.Content):
        return "".join(p.text or "" for p in conteudo.parts or [])
    return str(conteudo)


def receber(ctx: Context, node_input: Any) -> str:
    """Monta o texto que o agente lê: o pedido original e cada pergunta e resposta."""
    conversa = list(ctx.state.get("conversa", []))
    if isinstance(node_input, dict):
        conversa.append({"autor": "esteira", "texto": ctx.state.get("pergunta_pendente", "")})
        conversa.append({"autor": "rh", "texto": str(node_input.get("texto", ""))})
    else:
        conversa = [{"autor": "rh", "texto": _texto(node_input)}]
    ctx.state["conversa"] = conversa
    linhas = [f"Pedido do RH: {conversa[0]['texto']}"]
    for item in conversa[1:]:
        rotulo = "Pergunta da esteira" if item["autor"] == "esteira" else "Resposta do RH"
        linhas.append(f"{rotulo}: {item['texto']}")
    return "\n".join(linhas)


def perguntar_rh(node_input: dict):
    """Pausa o workflow até o RH responder. Na retomada, a resposta vira a saída do nó."""
    yield RequestInput(
        message=node_input["mensagem"],
        payload={"tipo": "dado_faltante", "problemas": node_input["problemas"]},
        response_schema=RespostaRH,
    )


# Conferência no diretório (determinística)


def _normalizar(texto: str) -> str:
    decomposto = unicodedata.normalize("NFKD", texto.strip().casefold())
    return "".join(c for c in decomposto if not unicodedata.combining(c))


def _candidatos_de_time(citado: str) -> list[str]:
    limpo = re.sub(r"^(o |a )?(time|equipe|squad)\s+", "", citado.strip(), flags=re.IGNORECASE)
    sem_preposicao = re.sub(r"^(de|do|da|dos|das)\s+", "", limpo, flags=re.IGNORECASE)
    return list(dict.fromkeys([citado.strip(), limpo, sem_preposicao]))


async def _resolver_time(citado: str) -> dict[str, Any] | None:
    for candidato in _candidatos_de_time(citado):
        if candidato and (time := await diretorio.consultar_time(candidato)):
            return time
    return None


def _resolver_id(valor: str | None, opcoes: list[dict[str, str]]) -> str | None:
    if not valor:
        return None
    procurado = _normalizar(valor).replace(" ", "-")
    for opcao in opcoes:
        if procurado in (_normalizar(opcao["id"]), _normalizar(opcao["nome"]).replace(" ", "-")):
            return opcao["id"]
    return None


async def conferir(ctx: Context, node_input: dict) -> Event:
    """Confere o que o agente extraiu contra o diretório, pelo MCP.

    Só segue adiante com valores que existem no diretório. Qualquer dado que
    falte ou que o diretório não reconheça vira pergunta ao RH, e nada é
    criado antes da resposta.
    """
    extraido = node_input or {}
    pessoa = (extraido.get("pessoa") or "").strip()
    tipo = extraido.get("tipo")
    problemas: list[str] = []
    perguntas: list[str] = []
    quem = pessoa or "a pessoa"

    if tipo not in ("admissao", "desligamento"):
        problemas.append("tipo ausente")
        perguntas.append("O pedido é de admissão ou de desligamento?")
    if not pessoa:
        problemas.append("pessoa ausente")
        perguntas.append("Qual é o nome completo da pessoa?")

    pedido: dict[str, Any] = {"tipo": tipo, "pessoa": pessoa}

    if tipo == "desligamento" and pessoa:
        colaborador = await diretorio.consultar_colaborador(pessoa)
        if colaborador is None or colaborador.get("situacao") != "ativo":
            problemas.append(f"colaborador não encontrado: {pessoa}")
            perguntas.append(f"Não encontrei {pessoa} entre os colaboradores ativos. Qual é o nome completo ou o e-mail?")
        else:
            pedido.update(pessoa=colaborador["nome"], email=colaborador["email"], time=colaborador["time"])

    if tipo == "admissao":
        citado = extraido.get("time_citado")
        if not citado:
            problemas.append("time ausente")
            perguntas.append(f"Qual é o time de {quem}?")
        elif (time := await _resolver_time(citado)) is None:
            nomes = ", ".join(t["nome"] for t in await diretorio.listar_times())
            problemas.append(f"time não existe no diretório: {citado}")
            perguntas.append(f"Não existe o time {citado} no diretório (times: {nomes}). Qual é o time de {quem}?")
        else:
            pedido.update(time=time["id"], gestor=time["gestor"])

        catalogo = await diretorio.listar_cargos()
        cargo = _resolver_id(extraido.get("cargo"), catalogo["cargos"])
        nivel = _resolver_id(extraido.get("nivel"), [{"id": n, "nome": n} for n in catalogo["niveis"]])
        if cargo is None:
            citado_cargo = extraido.get("cargo")
            problemas.append(f"cargo inválido: {citado_cargo}" if citado_cargo else "cargo ausente")
            nomes = ", ".join(c["nome"] for c in catalogo["cargos"])
            perguntas.append(f"Qual é o cargo de {quem}? (cargos: {nomes})")
        if nivel is None:
            citado_nivel = extraido.get("nivel")
            problemas.append(f"nível inválido: {citado_nivel}" if citado_nivel else "nível ausente")
            perguntas.append(f"Qual é o nível de {quem}? ({', '.join(catalogo['niveis'])})")
        pedido.update(cargo=cargo, nivel=nivel)
        if pessoa:
            try:
                pedido["email"] = email_corporativo(pessoa)
            except ValueError:
                problemas.append("nome sem sobrenome")
                perguntas.append(f"Qual é o nome completo, com sobrenome, de {quem}?")

    if problemas:
        mensagem = " ".join(perguntas)
        ctx.state["pergunta_pendente"] = mensagem
        return Event(
            output={"valido": False, "problemas": problemas, "mensagem": mensagem},
            route="faltando",
        )
    ctx.state["pedido"] = pedido
    return Event(output={"valido": True, "pedido": pedido}, route=tipo)


# Admissão


def calcular_acessos(ctx: Context, node_input: dict) -> dict:
    """Garantia 1: a lista de acessos sai de dados/politica.json, em código."""
    pedido = node_input["pedido"]
    acessos = acessos_da_politica(pedido["time"], pedido["nivel"])
    plano = {"email": pedido["email"], "gestor": pedido["gestor"], **acessos}
    ctx.state["plano"] = plano
    return plano


def _no_de_sistema(nome: str, sistema: str, operacao):
    """Cria um nó que fala com um sistema, registra cada chamada e repete em caso de falha."""

    async def executar(ctx: Context, node_input: dict):
        erro: Exception | None = None
        async with Chamadas(sistema) as chamadas:
            try:
                afetados = await operacao(chamadas, ctx, node_input)
            except sistemas.FalhaSistema as falha:
                erro = falha
        for registro in chamadas.registros:
            yield Event(custom_metadata={CHAVE_CHAMADA: registro})
        if erro is not None:
            raise erro
        yield {"sistema": sistema, "acessos": afetados}

    executar.__name__ = nome
    return FunctionNode(func=executar, name=nome, retry_config=REPETICAO)


async def _criar_email(ch: Chamadas, ctx: Context, plano: dict) -> list[str]:
    if not plano["comuns"]["email"]:
        return []
    await sistemas.criar_email(ch, plano["email"])
    return [f"email:{plano['email']}"]


async def _criar_github(ch: Chamadas, ctx: Context, plano: dict) -> list[str]:
    times = plano["comuns"]["times_github"]
    await sistemas.criar_github(ch, plano["email"], times)
    return [f"github:{t}" for t in times]


async def _criar_chat(ch: Chamadas, ctx: Context, plano: dict) -> list[str]:
    canais = plano["comuns"]["canais"]
    # A chave de idempotência usa o id do pedido: a mesma inclusão, repetida
    # em qualquer tentativa deste pedido, nunca vira um segundo registro.
    await sistemas.criar_chat(ch, plano["email"], canais, chave_pedido=ctx.session.id)
    return [f"chat:{c}" for c in canais]


async def _criar_nuvem(ch: Chamadas, ctx: Context, plano: dict) -> list[str]:
    papeis = plano["comuns"]["papeis_nuvem"]
    await sistemas.criar_nuvem(ch, plano["email"], papeis)
    return [f"nuvem:{p}" for p in papeis]


def aprovacao_gestor(node_input: dict):
    """Garantia 2: pausa só este ramo até o gestor do time decidir.

    Os outros quatro ramos seguem criando os acessos comuns enquanto isso. Na
    retomada, a decisão do gestor vira a saída deste nó.
    """
    sensiveis = node_input["sensiveis"]
    if not tem_sensiveis(sensiveis):
        yield {"necessaria": False}
        return
    gestor = node_input["gestor"]
    itens = descrever(sensiveis, node_input["email"])
    yield RequestInput(
        message=f"{gestor['nome']}, aprova os acessos sensíveis de {node_input['email']}: {', '.join(itens)}?",
        payload={"tipo": "aprovacao", "gestor": gestor, "acessos_sensiveis": itens},
        response_schema=DecisaoGestor,
    )


def _no_sensiveis():
    """Cria os sensíveis aprovados no GitHub e na nuvem, em paralelo, com a mesma idempotência."""

    async def provisionar_sensiveis(ctx: Context, node_input: dict):
        necessaria = node_input.get("necessaria", True)
        aprovado = necessaria and node_input.get("aprovado") is True
        if necessaria:
            ctx.state["decisao_gestor"] = {"aprovado": aprovado}
        if not aprovado:
            yield {"sistema": "sensiveis", "acessos": []}
            return
        plano = ctx.state["plano"]
        sensiveis, email = plano["sensiveis"], plano["email"]
        erro: Exception | None = None
        async with Chamadas("github") as gh, Chamadas("nuvem") as nv:
            try:
                await sistemas.em_paralelo(
                    sistemas.criar_github(gh, email, sensiveis["times_github"]),
                    sistemas.criar_nuvem(nv, email, sensiveis["papeis_nuvem"]),
                )
            except sistemas.FalhaSistema as falha:
                erro = falha
        for registro in gh.registros + nv.registros:
            yield Event(custom_metadata={CHAVE_CHAMADA: registro})
        if erro is not None:
            raise erro
        yield {"sistema": "sensiveis", "acessos": descrever(sensiveis, email)}

    return FunctionNode(func=provisionar_sensiveis, name="provisionar_sensiveis", retry_config=REPETICAO)


# Desligamento


async def _revogar_email(ch: Chamadas, ctx: Context, node_input: dict) -> list[str]:
    return await sistemas.revogar_email(ch, node_input["pedido"]["email"])


async def _revogar_github(ch: Chamadas, ctx: Context, node_input: dict) -> list[str]:
    return await sistemas.revogar_github(ch, node_input["pedido"]["email"])


async def _revogar_chat(ch: Chamadas, ctx: Context, node_input: dict) -> list[str]:
    return await sistemas.revogar_chat(ch, node_input["pedido"]["email"])


async def _revogar_nuvem(ch: Chamadas, ctx: Context, node_input: dict) -> list[str]:
    return await sistemas.revogar_nuvem(ch, node_input["pedido"]["email"])


# Conclusão


def concluir(ctx: Context, node_input: dict) -> dict:
    """Junta o resultado dos ramos. Só roda depois que todos terminaram."""
    pedido = ctx.state["pedido"]
    afetados = [a for ramo in node_input.values() if ramo for a in ramo.get("acessos") or []]
    criados = afetados if pedido["tipo"] == "admissao" else []
    revogados = afetados if pedido["tipo"] == "desligamento" else []
    return {
        "pedido": pedido,
        "acessos": {"criados": criados, "revogados": revogados},
        "decisao_gestor": ctx.state.get("decisao_gestor"),
    }


def criar_workflow() -> Workflow:
    no_receber = FunctionNode(func=receber, name="receber")
    no_interpretar = criar_agente()
    no_conferir = FunctionNode(func=conferir, name="conferir")
    no_perguntar = FunctionNode(func=perguntar_rh, name="perguntar_rh")
    no_calcular = FunctionNode(func=calcular_acessos, name="calcular_acessos")
    no_aprovacao = FunctionNode(func=aprovacao_gestor, name="aprovacao_gestor")
    no_sensiveis = _no_sensiveis()
    no_concluir = FunctionNode(func=concluir, name="concluir")

    criar = (
        _no_de_sistema("provisionar_email", "email", _criar_email),
        _no_de_sistema("provisionar_github", "github", _criar_github),
        _no_de_sistema("provisionar_chat", "chat", _criar_chat),
        _no_de_sistema("provisionar_nuvem", "nuvem", _criar_nuvem),
    )
    revogar = (
        _no_de_sistema("revogar_email", "email", _revogar_email),
        _no_de_sistema("revogar_github", "github", _revogar_github),
        _no_de_sistema("revogar_chat", "chat", _revogar_chat),
        _no_de_sistema("revogar_nuvem", "nuvem", _revogar_nuvem),
    )
    junta_admissao = JoinNode(name="junta_admissao")
    junta_desligamento = JoinNode(name="junta_desligamento")

    return Workflow(
        name="esteira_de_acessos",
        edges=[
            ("START", no_receber, no_interpretar, no_conferir),
            (no_conferir, {"faltando": no_perguntar, "admissao": no_calcular, "desligamento": revogar}),
            (no_perguntar, no_receber),
            (no_calcular, (*criar, no_aprovacao)),
            (no_aprovacao, no_sensiveis),
            ((*criar, no_sensiveis), junta_admissao),
            (revogar, junta_desligamento),
            (junta_admissao, no_concluir),
            (junta_desligamento, no_concluir),
        ],
    )
