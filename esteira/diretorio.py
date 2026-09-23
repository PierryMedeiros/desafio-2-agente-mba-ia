"""Cliente MCP do diretório da Nimbus, usado pelos nós de código.

O agente consulta o diretório pelo McpToolset do ADK. Os nós de código
conferem o que o agente devolveu chamando as mesmas ferramentas MCP por este
cliente, para que nenhum valor inventado siga adiante. O arquivo
`dados/diretorio.json` nunca é lido direto.
"""

import json
from typing import Any

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from esteira.config import DIRETORIO_MCP_URL


async def chamar(ferramenta: str, **argumentos: Any) -> dict[str, Any]:
    async with streamablehttp_client(DIRETORIO_MCP_URL) as (leitura, escrita, _):
        async with ClientSession(leitura, escrita) as sessao:
            await sessao.initialize()
            resultado = await sessao.call_tool(ferramenta, argumentos)
    if resultado.isError:
        raise RuntimeError(f"diretório respondeu erro em {ferramenta}: {resultado.content}")
    if resultado.structuredContent is not None:
        dados = resultado.structuredContent
        # FastMCP embrulha retornos que não são dict em {"result": ...}.
        return dados.get("result", dados) if isinstance(dados.get("result"), dict) else dados
    return json.loads(resultado.content[0].text)


async def consultar_time(nome_ou_id: str) -> dict[str, Any] | None:
    resposta = await chamar("consultar_time", nome_ou_id=nome_ou_id)
    return resposta if resposta.get("encontrado") else None


async def listar_times() -> list[dict[str, Any]]:
    return (await chamar("listar_times"))["times"]


async def listar_cargos() -> dict[str, Any]:
    return await chamar("listar_cargos")


async def consultar_colaborador(nome_ou_email: str) -> dict[str, Any] | None:
    resposta = await chamar("consultar_colaborador", nome_ou_email=nome_ou_email)
    return resposta if resposta.get("encontrado") else None
