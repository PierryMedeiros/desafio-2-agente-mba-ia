"""Servidor MCP somente leitura com o diretório da Nimbus.

Expõe times, gestores, cargos, níveis e colaboradores lidos de
`dados/diretorio.json`. Cada chamada de ferramenta deixa uma linha em
`var/diretorio-consultas.log` como evidência de consulta.
"""

import json
import unicodedata
from datetime import datetime
from typing import Any

from mcp.server.fastmcp import FastMCP

from nimbus.estado import CAMINHO_DIRETORIO, RAIZ, carregar_json

HOST = "127.0.0.1"
PORTA = 8765
CAMINHO_LOG = RAIZ / "var" / "diretorio-consultas.log"

mcp = FastMCP(
    "nimbus-diretorio",
    instructions="Diretório somente leitura da Nimbus: times, gestores, cargos, níveis e colaboradores.",
    host=HOST,
    port=PORTA,
    streamable_http_path="/mcp",
)


def _normalizar(texto: str) -> str:
    decomposto = unicodedata.normalize("NFKD", texto.strip().casefold())
    return "".join(c for c in decomposto if not unicodedata.combining(c))


def _registrar_consulta(ferramenta: str, argumentos: dict[str, Any]) -> None:
    CAMINHO_LOG.parent.mkdir(parents=True, exist_ok=True)
    momento = datetime.now().astimezone().isoformat(timespec="milliseconds")
    linha = f"{momento} {ferramenta} {json.dumps(argumentos, ensure_ascii=False)}\n"
    with CAMINHO_LOG.open("a", encoding="utf-8") as log:
        log.write(linha)


def _diretorio() -> dict[str, Any]:
    return carregar_json(CAMINHO_DIRETORIO)


@mcp.tool()
def listar_times() -> dict[str, Any]:
    """Lista os times da Nimbus com id, nome e gestor."""
    _registrar_consulta("listar_times", {})
    return {"times": _diretorio()["times"]}


@mcp.tool()
def consultar_time(nome_ou_id: str) -> dict[str, Any]:
    """Consulta um time pelo id ou pelo nome, sem diferenciar maiúsculas nem acentos."""
    _registrar_consulta("consultar_time", {"nome_ou_id": nome_ou_id})
    procurado = _normalizar(nome_ou_id)
    for time in _diretorio()["times"]:
        if procurado in (_normalizar(time["id"]), _normalizar(time["nome"])):
            return {"encontrado": True, **time}
    return {"encontrado": False}


@mcp.tool()
def listar_cargos() -> dict[str, Any]:
    """Lista os cargos da Nimbus e os níveis válidos."""
    _registrar_consulta("listar_cargos", {})
    diretorio = _diretorio()
    return {"cargos": diretorio["cargos"], "niveis": diretorio["niveis"]}


@mcp.tool()
def consultar_colaborador(nome_ou_email: str) -> dict[str, Any]:
    """Consulta um colaborador pelo nome completo ou pelo e-mail, sem diferenciar maiúsculas nem acentos."""
    _registrar_consulta("consultar_colaborador", {"nome_ou_email": nome_ou_email})
    procurado = _normalizar(nome_ou_email)
    for colaborador in _diretorio()["colaboradores"]:
        if procurado in (_normalizar(colaborador["email"]), _normalizar(colaborador["nome"])):
            return {"encontrado": True, **colaborador}
    return {"encontrado": False}


def main() -> None:
    print(f"Diretório da Nimbus em http://localhost:{PORTA}/mcp")
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
