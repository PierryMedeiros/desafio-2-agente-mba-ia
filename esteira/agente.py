"""O agente que lê o pedido do RH.

É o único ponto não determinístico da esteira: transforma texto livre em
campos, consultando o diretório pelo MCP para usar os ids certos. Ele não
decide acesso nenhum, e o que ele devolve ainda é conferido em código no nó
`conferir` antes de qualquer efeito.
"""

from typing import Literal

from google.adk.agents import LlmAgent
from google.adk.tools.mcp_tool import McpToolset
from google.adk.tools.mcp_tool.mcp_session_manager import StreamableHTTPConnectionParams
from google.genai import types
from pydantic import BaseModel, Field

from esteira.config import DIRETORIO_MCP_URL, MODELO


class PedidoExtraido(BaseModel):
    tipo: Literal["admissao", "desligamento"] | None = Field(
        default=None, description="admissao ou desligamento; null se o texto não deixa claro"
    )
    pessoa: str | None = Field(default=None, description="nome completo da pessoa, como escrito no texto")
    time_citado: str | None = Field(
        default=None,
        description="nome do time exatamente como o RH escreveu, sem 'time de'; null se nenhum time foi citado",
    )
    cargo: str | None = Field(default=None, description="id do cargo segundo listar_cargos; null se não citado")
    nivel: str | None = Field(default=None, description="id do nível segundo listar_cargos; null se não citado")


INSTRUCAO = """
Você lê pedidos do RH da Nimbus, escritos em português, e extrai os campos do
pedido. Você não decide acessos: só extrai o que está escrito.

O texto pode trazer o pedido original seguido de perguntas da esteira e
respostas do RH. Considere tudo: uma resposta posterior do RH completa ou
corrige o pedido original.

Regras:
- tipo: "admissao" para admissão, contratação ou entrada; "desligamento" para
  desligamento, demissão ou saída.
- pessoa: o nome completo da pessoa, sem título.
- time_citado: só preencha se o texto disser explicitamente o time (por
  exemplo "no time de Risco", "é do time de Dados"). Copie o nome do time como
  escrito, sem "time de". O cargo NÃO indica o time: "engenheiro de dados"
  não quer dizer time de Dados. Se o RH citar um time que não existe no
  diretório, copie o nome citado assim mesmo; a conferência é feita depois.
- cargo e nivel: chame a ferramenta listar_cargos e devolva os ids dela. O
  gênero não importa ("engenheira de software plena" é o cargo
  engenheiro-de-software no nível pleno). Se o cargo ou o nível não estiverem
  no texto, deixe null.
- No desligamento, só tipo e pessoa importam.
- Nunca invente nem deduza um valor que não está escrito. Na dúvida, null.
""".strip()


def criar_agente() -> LlmAgent:
    return LlmAgent(
        name="interpretar",
        model=MODELO,
        description="Extrai o pedido estruturado a partir do texto livre do RH.",
        instruction=INSTRUCAO,
        tools=[
            McpToolset(
                connection_params=StreamableHTTPConnectionParams(url=DIRETORIO_MCP_URL),
                tool_filter=["listar_times", "consultar_time", "listar_cargos", "consultar_colaborador"],
            )
        ],
        output_schema=PedidoExtraido,
        generate_content_config=types.GenerateContentConfig(
            temperature=0,
            # Extração curta: sem raciocínio estendido, cada chamada fica bem mais rápida.
            thinking_config=types.ThinkingConfig(thinking_budget=0),
            http_options=types.HttpOptions(
                retry_options=types.HttpRetryOptions(attempts=5, initial_delay=2, max_delay=30)
            ),
        ),
    )
