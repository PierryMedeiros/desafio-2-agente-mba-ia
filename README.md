# Repositório base do desafio

Este arquivo é provisório e será substituído pelo enunciado do desafio antes da publicação.

## Como subir os serviços

Instale as dependências:

```bash
uv sync
```

Suba os sistemas simulados em `http://localhost:8100`:

```bash
uv run nimbus-sistemas
```

Em outro terminal, suba o diretório MCP em `http://localhost:8765/mcp`:

```bash
uv run nimbus-diretorio
```
