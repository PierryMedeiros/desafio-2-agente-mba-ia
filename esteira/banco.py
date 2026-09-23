"""Persistência da API: situação de cada pedido e a trilha de auditoria.

Fica num SQLite em `var/`, separado do banco de sessões do ADK, para que a
trilha e as pendências sobrevivam ao reinício da API.
"""

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator

from esteira.config import CAMINHO_BANCO

ESQUEMA = """
CREATE TABLE IF NOT EXISTS pedidos (
    pedido_id TEXT PRIMARY KEY,
    situacao TEXT NOT NULL,
    pendencia TEXT,
    pedido TEXT,
    acessos TEXT NOT NULL,
    criado_em TEXT NOT NULL,
    atualizado_em TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS trilha (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    pedido_id TEXT NOT NULL,
    horario TEXT NOT NULL,
    etapa TEXT NOT NULL,
    detalhe TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS trilha_pedido ON trilha (pedido_id, seq);
"""

ACESSOS_VAZIOS = {"criados": [], "revogados": []}


def agora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


@contextmanager
def conexao() -> Iterator[sqlite3.Connection]:
    CAMINHO_BANCO.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(CAMINHO_BANCO, timeout=10)
    con.row_factory = sqlite3.Row
    try:
        with con:
            yield con
    finally:
        con.close()


def iniciar() -> None:
    with conexao() as con:
        con.executescript(ESQUEMA)


# Pedidos


def criar_pedido(pedido_id: str) -> None:
    momento = agora()
    with conexao() as con:
        con.execute(
            "INSERT INTO pedidos VALUES (?, ?, NULL, NULL, ?, ?, ?)",
            (pedido_id, "em_andamento", json.dumps(ACESSOS_VAZIOS), momento, momento),
        )


def atualizar_pedido(pedido_id: str, **campos: Any) -> None:
    colunas = {k: (json.dumps(v, ensure_ascii=False) if k != "situacao" else v) for k, v in campos.items()}
    atribuicoes = ", ".join(f"{k} = ?" for k in colunas)
    with conexao() as con:
        con.execute(
            f"UPDATE pedidos SET {atribuicoes}, atualizado_em = ? WHERE pedido_id = ?",
            (*colunas.values(), agora(), pedido_id),
        )


def ler_pedido(pedido_id: str) -> dict[str, Any] | None:
    with conexao() as con:
        linha = con.execute("SELECT * FROM pedidos WHERE pedido_id = ?", (pedido_id,)).fetchone()
    if linha is None:
        return None
    return {
        "pedido_id": linha["pedido_id"],
        "situacao": linha["situacao"],
        "pendencia": json.loads(linha["pendencia"]) if linha["pendencia"] else None,
        "pedido": json.loads(linha["pedido"]) if linha["pedido"] else None,
        "acessos": json.loads(linha["acessos"]),
    }


# Trilha


def registrar(pedido_id: str, etapa: str, detalhe: Any) -> None:
    with conexao() as con:
        con.execute(
            "INSERT INTO trilha (pedido_id, horario, etapa, detalhe) VALUES (?, ?, ?, ?)",
            (pedido_id, agora(), etapa, json.dumps(detalhe, ensure_ascii=False, default=str)),
        )


def ler_trilha(pedido_id: str) -> list[dict[str, Any]]:
    with conexao() as con:
        linhas = con.execute(
            "SELECT seq, horario, etapa, detalhe FROM trilha WHERE pedido_id = ? ORDER BY seq", (pedido_id,)
        ).fetchall()
    return [
        {"seq": l["seq"], "horario": l["horario"], "etapa": l["etapa"], "detalhe": json.loads(l["detalhe"])}
        for l in linhas
    ]
