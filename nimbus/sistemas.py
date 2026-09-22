"""Sistemas simulados da Nimbus: e-mail, GitHub interno, chat e nuvem.

Cada sistema trata duplicidade de um jeito diferente, de propósito:
- e-mail recusa duplicado com 409;
- GitHub é idempotente por natureza;
- chat duplica, mas aceita o cabeçalho Idempotency-Key;
- nuvem duplica e não tem chave de idempotência.

As rotas em /admin servem para preparar cenários e inspecionar o resultado.
"""

import asyncio
import json
from collections.abc import Callable
from typing import Any, Literal

import uvicorn
from fastapi import Body, FastAPI, Header, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field, model_validator

from nimbus import estado as modulo_estado
from nimbus.estado import SISTEMAS, agora_iso, estado

HOST = "127.0.0.1"
PORTA = 8100
PADRAO_EMAIL = r"^[^@\s/]+@[^@\s/]+$"

app = FastAPI(
    title="Sistemas simulados da Nimbus",
    description="E-mail corporativo, GitHub interno, chat e nuvem, com rotas administrativas.",
)


class CorpoConta(BaseModel):
    email: str = Field(pattern=PADRAO_EMAIL)


class CorpoMembroCanal(BaseModel):
    email: str = Field(pattern=PADRAO_EMAIL)


class CorpoPapel(BaseModel):
    email: str = Field(pattern=PADRAO_EMAIL)
    papel: str = Field(min_length=1)


class ConfigFalha(BaseModel):
    modo: Literal["indisponivel", "grava_e_falha", "lento", "nenhum"]
    vezes: int = Field(default=1, ge=1)
    ms: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def exigir_ms_no_modo_lento(self) -> "ConfigFalha":
        if self.modo == "lento" and self.ms is None:
            raise ValueError("o modo lento exige o campo ms")
        return self


Resultado = tuple[int, str, Any]


def responder(status: int, conteudo: Any) -> Response:
    if status == 204:
        return Response(status_code=204)
    return JSONResponse(status_code=status, content=conteudo)


async def escrever(
    sistema: str,
    operacao: str,
    alvo: str,
    corpo: Any,
    aplicar: Callable[[], Resultado],
) -> Response:
    """Executa uma escrita aplicando a falha configurada, a espera e o registro."""
    seq = estado.proximo_seq()
    inicio = agora_iso()
    falha = estado.consumir_falha(sistema)
    modo = falha["modo"] if falha else "nenhum"
    espera_ms = modulo_estado.ESPERA_ESCRITA_MS
    if modo == "lento":
        espera_ms += falha["ms"]

    if modo == "indisponivel":
        status, efeito, conteudo = 503, "nenhum", {"erro": "sistema indisponível"}
    else:
        status, efeito, conteudo = aplicar()
        if modo == "grava_e_falha":
            status, conteudo = 504, {"erro": "tempo de resposta esgotado"}

    await asyncio.sleep(espera_ms / 1000)
    estado.registrar(
        seq=seq,
        inicio=inicio,
        sistema=sistema,
        operacao=operacao,
        alvo=alvo,
        corpo=corpo,
        status=status,
        efeito=efeito,
    )
    return responder(status, conteudo)


def ler(sistema: str, operacao: str, alvo: str, conteudo: Any) -> Response:
    """Responde uma leitura sem espera e deixa a chamada no registro."""
    seq = estado.proximo_seq()
    inicio = agora_iso()
    estado.registrar(
        seq=seq,
        inicio=inicio,
        sistema=sistema,
        operacao=operacao,
        alvo=alvo,
        corpo=None,
        status=200,
        efeito="nenhum",
    )
    return responder(200, conteudo)


# Nome da operação no registro para cada rota dos quatro sistemas.
OPERACOES = {
    "criar_conta": "criar_conta",
    "remover_conta": "remover_conta",
    "listar_contas": "listar_contas",
    "adicionar_membro_github": "adicionar_membro",
    "remover_membro_github": "remover_membro",
    "listar_membros_github": "listar_membros",
    "adicionar_membro_chat": "adicionar_membro",
    "remover_membro_chat": "remover_membro",
    "listar_membros_chat": "listar_membros",
    "atribuir_papel": "atribuir_papel",
    "listar_papeis": "listar_atribuicoes",
    "remover_atribuicao": "remover_atribuicao",
}


@app.exception_handler(RequestValidationError)
async def requisicao_invalida(request: Request, erro: RequestValidationError) -> Response:
    """Responde 422 em português e registra a chamada quando ela é para um dos sistemas."""
    conteudo = {"erro": "requisição inválida", "detalhes": jsonable_encoder(erro.errors())}
    rota = request.scope.get("route")
    sistema = request.url.path.strip("/").split("/")[0]
    if rota is not None and rota.name in OPERACOES and sistema in SISTEMAS:
        bruto = await request.body()
        try:
            corpo = json.loads(bruto) if bruto else None
        except ValueError:
            corpo = bruto.decode("utf-8", errors="replace")
        estado.registrar(
            seq=estado.proximo_seq(),
            inicio=agora_iso(),
            sistema=sistema,
            operacao=OPERACOES[rota.name],
            alvo=":".join(str(v) for v in request.path_params.values()) or "*",
            corpo=corpo,
            status=422,
            efeito="nenhum",
        )
    return JSONResponse(status_code=422, content=conteudo)


# E-mail corporativo: recusa duplicado


@app.post("/email/contas", status_code=201, tags=["email"])
async def criar_conta(corpo: CorpoConta) -> Response:
    def aplicar() -> Resultado:
        if corpo.email in estado.contas_email:
            return 409, "ja_existia", {"erro": "conta já existe"}
        estado.contas_email.add(corpo.email)
        return 201, "criado", {"email": corpo.email}

    return await escrever("email", "criar_conta", corpo.email, corpo.model_dump(), aplicar)


@app.delete("/email/contas/{email}", status_code=204, tags=["email"])
async def remover_conta(email: str) -> Response:
    def aplicar() -> Resultado:
        if email not in estado.contas_email:
            return 404, "nao_encontrado", {"erro": "conta não encontrada"}
        estado.contas_email.discard(email)
        return 204, "removido", None

    return await escrever("email", "remover_conta", email, None, aplicar)


@app.get("/email/contas", tags=["email"])
async def listar_contas() -> Response:
    return ler("email", "listar_contas", "*", {"contas": sorted(estado.contas_email)})


# GitHub interno: idempotente por natureza


@app.put("/github/times/{time}/membros/{email}", tags=["github"])
async def adicionar_membro_github(time: str, email: str) -> Response:
    def aplicar() -> Resultado:
        membros = estado.times_github.setdefault(time, set())
        if email in membros:
            return 200, "ja_existia", {"time": time, "email": email, "ja_era_membro": True}
        membros.add(email)
        return 200, "criado", {"time": time, "email": email, "ja_era_membro": False}

    return await escrever("github", "adicionar_membro", f"{time}:{email}", None, aplicar)


@app.delete("/github/times/{time}/membros/{email}", status_code=204, tags=["github"])
async def remover_membro_github(time: str, email: str) -> Response:
    def aplicar() -> Resultado:
        membros = estado.times_github.get(time, set())
        if email not in membros:
            return 204, "nao_encontrado", None
        membros.discard(email)
        return 204, "removido", None

    return await escrever("github", "remover_membro", f"{time}:{email}", None, aplicar)


@app.get("/github/times/{time}/membros", tags=["github"])
async def listar_membros_github(time: str) -> Response:
    membros = sorted(estado.times_github.get(time, set()))
    return ler("github", "listar_membros", time, {"time": time, "membros": membros})


# Chat: duplica, mas aceita chave de idempotência


@app.post("/chat/canais/{canal}/membros", status_code=201, tags=["chat"])
async def adicionar_membro_chat(
    canal: str,
    corpo: CorpoMembroCanal,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> Response:
    def aplicar() -> Resultado:
        if idempotency_key is not None:
            anterior = estado.chaves_chat.get((canal, idempotency_key))
            if anterior is not None:
                return 200, "ja_existia", anterior
        ja_havia = any(r["email"] == corpo.email for r in estado.canais_chat.get(canal, []))
        registro = estado.novo_registro_chat(canal, corpo.email)
        if idempotency_key is not None:
            estado.chaves_chat[(canal, idempotency_key)] = registro
        return 201, "duplicado" if ja_havia else "criado", registro

    alvo = f"{canal}:{corpo.email}"
    return await escrever("chat", "adicionar_membro", alvo, corpo.model_dump(), aplicar)


@app.delete("/chat/canais/{canal}/membros/{email}", status_code=204, tags=["chat"])
async def remover_membro_chat(canal: str, email: str) -> Response:
    def aplicar() -> Resultado:
        registros = estado.canais_chat.get(canal, [])
        removidos = {r["id"] for r in registros if r["email"] == email}
        if not removidos:
            return 204, "nao_encontrado", None
        estado.canais_chat[canal] = [r for r in registros if r["id"] not in removidos]
        for chave, registro in list(estado.chaves_chat.items()):
            if registro["id"] in removidos:
                del estado.chaves_chat[chave]
        return 204, "removido", None

    return await escrever("chat", "remover_membro", f"{canal}:{email}", None, aplicar)


@app.get("/chat/canais/{canal}/membros", tags=["chat"])
async def listar_membros_chat(canal: str) -> Response:
    registros = list(estado.canais_chat.get(canal, []))
    return ler("chat", "listar_membros", canal, {"canal": canal, "registros": registros})


# Nuvem: duplica e não tem chave de idempotência


@app.post("/nuvem/papeis", status_code=201, tags=["nuvem"])
async def atribuir_papel(corpo: CorpoPapel) -> Response:
    def aplicar() -> Resultado:
        ja_havia = any(a["email"] == corpo.email and a["papel"] == corpo.papel for a in estado.papeis_nuvem)
        atribuicao = estado.nova_atribuicao_nuvem(corpo.email, corpo.papel)
        return 201, "duplicado" if ja_havia else "criado", atribuicao

    alvo = f"{corpo.email}:{corpo.papel}"
    return await escrever("nuvem", "atribuir_papel", alvo, corpo.model_dump(), aplicar)


@app.get("/nuvem/papeis", tags=["nuvem"])
async def listar_papeis(email: str | None = Query(default=None)) -> Response:
    atribuicoes = [dict(a) for a in estado.papeis_nuvem if email is None or a["email"] == email]
    return ler("nuvem", "listar_atribuicoes", email or "*", {"atribuicoes": atribuicoes})


@app.delete("/nuvem/papeis/{id_atribuicao}", status_code=204, tags=["nuvem"])
async def remover_atribuicao(id_atribuicao: str) -> Response:
    def aplicar() -> Resultado:
        for atribuicao in estado.papeis_nuvem:
            if atribuicao["id"] == id_atribuicao:
                estado.papeis_nuvem.remove(atribuicao)
                return 204, "removido", None
        return 404, "nao_encontrado", {"erro": "atribuição não encontrada"}

    return await escrever("nuvem", "remover_atribuicao", id_atribuicao, None, aplicar)


# Rotas administrativas


@app.post("/admin/reset", tags=["admin"])
async def admin_reset() -> dict[str, str]:
    modulo_estado.reset()
    return {"situacao": "estado inicial restaurado"}


@app.post("/admin/falhas", tags=["admin"])
async def admin_configurar_falhas(corpo: dict[str, ConfigFalha] = Body(...)) -> Response:
    desconhecidos = sorted(set(corpo) - set(SISTEMAS))
    if desconhecidos:
        erro = f"sistema desconhecido: {', '.join(desconhecidos)}. Use {', '.join(SISTEMAS)}"
        return JSONResponse(status_code=422, content={"erro": erro})
    for sistema, config in corpo.items():
        estado.configurar_falha(sistema, config.modo, config.vezes, config.ms)
    return JSONResponse(status_code=200, content=estado.config_falhas())


@app.get("/admin/falhas", tags=["admin"])
async def admin_ver_falhas() -> dict[str, Any]:
    return estado.config_falhas()


@app.get("/admin/registro", tags=["admin"])
async def admin_registro() -> list[dict[str, Any]]:
    return list(estado.registro)


@app.get("/admin/estado", tags=["admin"])
async def admin_estado(email: str = Query(...)) -> dict[str, Any]:
    return estado.consolidado(email)


def main() -> None:
    print(f"Sistemas da Nimbus em http://localhost:{PORTA}")
    uvicorn.run(app, host=HOST, port=PORTA)


if __name__ == "__main__":
    main()
