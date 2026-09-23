"""Trilha de auditoria como plugin do ADK.

O plugin enxerga todos os eventos do Runner e grava na trilha do pedido (o id
da sessão é o id do pedido) o que precisa se explicar depois: o pedido que o
agente extraiu, as consultas dele ao diretório, o pedido estruturado depois da
conferência, as perguntas ao RH e as respostas, o pedido de aprovação e a
decisão do gestor, os acessos calculados e cada chamada aos sistemas com o
resultado. Por ficar no plugin, nenhum nó precisa lembrar de auditar.
"""

from typing import Any, Optional

from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event
from google.adk.plugins.base_plugin import BasePlugin
from google.adk.tools.base_tool import BaseTool
from google.adk.tools.tool_context import ToolContext
from google.genai import types

from esteira import banco

PEDIDO_DE_INPUT = "adk_request_input"
CHAVE_CHAMADA = "chamada_sistema"

# Saída de cada nó que vira etapa da trilha.
ETAPAS_POR_NO = {
    "calcular_acessos": "acessos_calculados_pela_politica",
    "concluir": "pedido_concluido",
}


def nome_do_no(evento: Event) -> str | None:
    if not evento.node_info or not evento.node_info.path:
        return None
    return evento.node_info.path.rsplit("/", 1)[-1].split("@", 1)[0]


class TrilhaPlugin(BasePlugin):
    def __init__(self) -> None:
        super().__init__(name="trilha_de_auditoria")

    async def on_user_message_callback(
        self, *, invocation_context: InvocationContext, user_message: types.Content
    ) -> Optional[types.Content]:
        pedido_id = invocation_context.session.id
        for parte in user_message.parts or []:
            resposta = parte.function_response
            if resposta is None or resposta.name != PEDIDO_DE_INPUT:
                continue
            conteudo = dict(resposta.response or {})
            etapa = "decisao_do_gestor" if "aprovado" in conteudo else "resposta_do_rh"
            banco.registrar(pedido_id, etapa, {"pendencia_id": resposta.id, "resposta": conteudo})
        return None

    async def on_event_callback(self, *, invocation_context: InvocationContext, event: Event) -> Optional[Event]:
        pedido_id = invocation_context.session.id
        metadados = event.custom_metadata or {}
        if CHAVE_CHAMADA in metadados:
            banco.registrar(pedido_id, "chamada_sistema", metadados[CHAVE_CHAMADA])
            return None

        for chamada in event.get_function_calls():
            if chamada.name != PEDIDO_DE_INPUT:
                continue
            argumentos = dict(chamada.args or {})
            carga = argumentos.get("payload") or {}
            etapa = "aprovacao_solicitada" if carga.get("tipo") == "aprovacao" else "pergunta_ao_rh"
            banco.registrar(
                pedido_id,
                etapa,
                {"pendencia_id": chamada.id, "mensagem": argumentos.get("message"), **carga},
            )

        no = nome_do_no(event)
        if event.output is None or no is None:
            return None
        if no == "conferir":
            # A saída do agente chega ao plugin sem `output` (o Runner limpa o
            # campo quando a saída é a própria mensagem do modelo), então o que
            # ele extraiu é registrado a partir da entrada de `conferir`.
            saida = event.output
            if not isinstance(saida, dict):
                banco.registrar(pedido_id, "agente_sem_resposta_estruturada", {"acao": "reler o mesmo texto"})
                return None
            banco.registrar(pedido_id, "pedido_extraido_pelo_agente", saida.get("extraido"))
            if saida.get("valido"):
                banco.registrar(pedido_id, "pedido_estruturado", saida["pedido"])
            else:
                banco.registrar(pedido_id, "dado_faltante_ou_invalido", {"problemas": saida.get("problemas")})
        elif no in ETAPAS_POR_NO:
            banco.registrar(pedido_id, ETAPAS_POR_NO[no], event.output)
        return None

    async def after_tool_callback(
        self, *, tool: BaseTool, tool_args: dict[str, Any], tool_context: ToolContext, result: dict[str, Any]
    ) -> Optional[dict[str, Any]]:
        if tool.name == "set_model_response":
            return None
        pedido_id = tool_context.session.id
        banco.registrar(pedido_id, "agente_consultou_diretorio", {"ferramenta": tool.name, "argumentos": tool_args})
        return None
