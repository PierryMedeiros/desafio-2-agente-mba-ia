"""Configuração da esteira, lida do ambiente com valores padrão para rodar local."""

import os
from pathlib import Path

from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parent.parent

# A chave do Gemini e as variáveis opcionais vêm do .env da raiz do projeto.
load_dotenv(RAIZ / ".env")
CAMINHO_POLITICA = RAIZ / "dados" / "politica.json"

SISTEMAS_URL = os.environ.get("NIMBUS_SISTEMAS_URL", "http://localhost:8100")
DIRETORIO_MCP_URL = os.environ.get("NIMBUS_DIRETORIO_URL", "http://localhost:8765/mcp")

# Banco SQLite com as sessões do ADK, os pedidos e a trilha. Fica em var/,
# que está no .gitignore, para sobreviver ao reinício da API.
CAMINHO_BANCO = Path(os.environ.get("ESTEIRA_BANCO", RAIZ / "var" / "esteira.db"))

MODELO = os.environ.get("ESTEIRA_MODELO", "gemini-2.5-flash")

API_HOST = os.environ.get("ESTEIRA_HOST", "127.0.0.1")
API_PORTA = int(os.environ.get("ESTEIRA_PORTA", "8000"))

DOMINIO_EMAIL = "nimbus.dev"
