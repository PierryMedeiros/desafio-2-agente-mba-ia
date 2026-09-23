"""API da esteira de acessos, no contrato do enunciado.

Cada pedido é uma sessão do ADK (o id da sessão é o id do pedido), guardada no
SQLite pelo `SqliteSessionService`. Abrir um pedido roda o workflow até ele
concluir ou parar numa pendência; responder a pendência retoma o workflow
mandando a resposta como `FunctionResponse` do `adk_request_input`. Como tudo
fica no banco, a pendência sobrevive ao reinício da API.
"""

import asyncio
import logging
import uuid
from contextlib import asynccontextmanager
from typing import Any

import uvicorn
from fastapi import Body, FastAPI
from fastapi.responses import JSONResponse
from google.adk.apps import App
from google.adk.runners import Runner
from google.adk.sessions.sqlite_session_service import SqliteSessionService
from google.genai import types
from pydantic import BaseModel, ValidationError

from esteira import banco
from esteira.config import API_HOST, API_PORTA, CAMINHO_BANCO
from esteira.trilha import PEDIDO_DE_INPUT, TrilhaPlugin, nome_do_no
from esteira.workflow import DecisaoGestor, RespostaRH, criar_workflow

logger = logging.getLogger("esteira")
NOME_APP = "esteira_de_acessos"
USUARIO = "rh"
CAMPOS_DO_PEDIDO = ("tipo", "pessoa", "email", "time", "cargo", "nivel")

CAMINHO_SESSOES = CAMINHO_BANCO.with_name("sessoes-adk.db")
CAMINHO_SESSOES.parent.mkdir(parents=True, exist_ok=True)
sessoes = SqliteSessionService(str(CAMINHO_SESSOES))
runner = Runner(
    app=App(name=NOME_APP, root_agent=criar_workflow(), plugins=[TrilhaPlugin()]),
    session_service=sessoes,
)
# O avaliador abre um pedido por vez, mas uma trava por pedido evita que duas
# respostas simultâneas retomem a mesma pendência.
travas: dict[str, asyncio.Lock] = {}


class NovoPedido(BaseModel):
    texto: str


class Resposta(BaseModel):
    pendencia_id: str
    resposta: dict[str, Any]


@asynccontextmanager
async def ciclo_de_vida(_: FastAPI):
    banco.iniciar()
    yield
    await runner.close()


app = FastAPI(title="Esteira de acessos da Nimbus", lifespan=ciclo_de_vida)


def _pendencia(chamada: types.FunctionCall) -> dict[str, Any]:
    argumentos = dict(chamada.args or {})
    carga = dict(argumentos.get("payload") or {})
    tipo = carga.pop("tipo", "dado_faltante")
    pendencia = {"id": chamada.id, "tipo": tipo, "mensagem": argumentos.get("message")}
    if tipo == "aprovacao":
        pendencia["gestor"] = carga.get("gestor")
        pendencia["acessos_sensiveis"] = carga.get("acessos_sensiveis", [])
    return pendencia


async def executar(pedido_id: str, mensagem: types.Content) -> None:
    """Roda o workflow até concluir ou parar esperando alguém, e grava a situação."""
    pendencia: dict[str, Any] | None = None
    resultado: dict[str, Any] | None = None
    try:
        async for evento in runner.run_async(user_id=USUARIO, session_id=pedido_id, new_message=mensagem):
            for chamada in evento.get_function_calls():
                if chamada.name == PEDIDO_DE_INPUT:
                    pendencia = _pendencia(chamada)
            if evento.output is not None and nome_do_no(evento) == "concluir":
                resultado = evento.output
    except Exception as erro:  # noqa: BLE001 - qualquer falha encerra o pedido como falhou
        logger.exception("pedido %s falhou", pedido_id)
        banco.registrar(pedido_id, "pedido_falhou", {"erro": f"{type(erro).__name__}: {erro}"})
        banco.atualizar_pedido(pedido_id, situacao="falhou", pendencia=None)
        return

    sessao = await sessoes.get_session(app_name=NOME_APP, user_id=USUARIO, session_id=pedido_id)
    estado = sessao.state if sessao else {}
    pedido = estado.get("pedido")
    campos: dict[str, Any] = {}
    if pedido:
        campos["pedido"] = {k: pedido.get(k) for k in CAMPOS_DO_PEDIDO if pedido.get(k) is not None}
    if resultado is not None:
        campos.update(situacao="concluido", pendencia=None, acessos=resultado["acessos"])
    elif pendencia is not None:
        campos.update(situacao="aguardando_resposta", pendencia=pendencia)
    else:
        banco.registrar(pedido_id, "pedido_falhou", {"erro": "workflow terminou sem concluir nem pedir resposta"})
        campos.update(situacao="falhou", pendencia=None)
    banco.atualizar_pedido(pedido_id, **campos)


def _nao_encontrado() -> JSONResponse:
    return JSONResponse(status_code=404, content={"erro": "pedido não encontrado"})


@app.post("/pedidos", status_code=201)
async def abrir_pedido(corpo: NovoPedido) -> JSONResponse:
    pedido_id = str(uuid.uuid4())
    banco.criar_pedido(pedido_id)
    banco.registrar(pedido_id, "pedido_recebido", {"texto": corpo.texto})
    await sessoes.create_session(app_name=NOME_APP, user_id=USUARIO, session_id=pedido_id)
    async with travas.setdefault(pedido_id, asyncio.Lock()):
        await executar(pedido_id, types.Content(role="user", parts=[types.Part(text=corpo.texto)]))
    return JSONResponse(status_code=201, content=banco.ler_pedido(pedido_id))


@app.post("/pedidos/{pedido_id}/respostas")
async def responder(pedido_id: str, corpo: Resposta = Body(...)) -> JSONResponse:
    if banco.ler_pedido(pedido_id) is None:
        return _nao_encontrado()
    async with travas.setdefault(pedido_id, asyncio.Lock()):
        atual = banco.ler_pedido(pedido_id)
        pendencia = atual["pendencia"]
        if atual["situacao"] != "aguardando_resposta" or not pendencia or pendencia["id"] != corpo.pendencia_id:
            return JSONResponse(
                status_code=409, content={"erro": "não existe pendência com esse id nesse pedido"}
            )
        esquema = DecisaoGestor if pendencia["tipo"] == "aprovacao" else RespostaRH
        try:
            resposta = esquema.model_validate(corpo.resposta).model_dump()
        except ValidationError as erro:
            return JSONResponse(status_code=422, content={"erro": "resposta inválida", "detalhes": erro.errors()})
        # A pendência é consumida antes de retomar: uma segunda resposta igual
        # recebe 409 mesmo que chegue enquanto a primeira ainda roda.
        banco.atualizar_pedido(pedido_id, situacao="em_andamento", pendencia=None)
        mensagem = types.Content(
            role="user",
            parts=[
                types.Part(
                    function_response=types.FunctionResponse(
                        id=pendencia["id"], name=PEDIDO_DE_INPUT, response=resposta
                    )
                )
            ],
        )
        await executar(pedido_id, mensagem)
    return JSONResponse(status_code=200, content=banco.ler_pedido(pedido_id))


@app.get("/pedidos/{pedido_id}")
async def consultar(pedido_id: str) -> JSONResponse:
    pedido = banco.ler_pedido(pedido_id)
    return JSONResponse(content=pedido) if pedido else _nao_encontrado()


@app.get("/pedidos/{pedido_id}/trilha")
async def trilha(pedido_id: str) -> JSONResponse:
    if banco.ler_pedido(pedido_id) is None:
        return _nao_encontrado()
    return JSONResponse(content=banco.ler_trilha(pedido_id))


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    banco.iniciar()
    print(f"Esteira de acessos em http://localhost:{API_PORTA}")
    uvicorn.run(app, host=API_HOST, port=API_PORTA)
