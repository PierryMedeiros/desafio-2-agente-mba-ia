"""Garantia 1: a lista de acessos sai da política, aplicada em código.

Nada aqui passa pelo modelo. Recebe time e nível já conferidos no diretório e
devolve exatamente o que `dados/politica.json` manda, separado em comuns e
sensíveis.
"""

import json
import unicodedata
from functools import cache
from typing import Any

from esteira.config import CAMINHO_POLITICA, DOMINIO_EMAIL

CATEGORIAS = ("times_github", "canais", "papeis_nuvem")


@cache
def carregar_politica() -> dict[str, Any]:
    with CAMINHO_POLITICA.open(encoding="utf-8") as arquivo:
        return json.load(arquivo)


def _sem_repetir(itens: list[str]) -> list[str]:
    return list(dict.fromkeys(itens))


def acessos_da_politica(time: str, nivel: str) -> dict[str, Any]:
    """Soma os blocos `todos`, `por_time[time]` e `por_nivel[nivel]` e separa os sensíveis."""
    politica = carregar_politica()
    if time not in politica["por_time"] or nivel not in politica["por_nivel"]:
        raise ValueError(f"política não cobre time={time!r} nível={nivel!r}")
    camadas = (politica["todos"], politica["por_time"][time], politica["por_nivel"][nivel])
    marcados = politica.get("sensiveis", {})

    comuns: dict[str, Any] = {"email": any(c.get("email", False) for c in camadas)}
    sensiveis: dict[str, Any] = {"email": False}
    for categoria in CATEGORIAS:
        todos = _sem_repetir([item for camada in camadas for item in camada.get(categoria, [])])
        comuns[categoria] = [a for a in todos if a not in marcados.get(categoria, [])]
        sensiveis[categoria] = [a for a in todos if a in marcados.get(categoria, [])]
    return {"comuns": comuns, "sensiveis": sensiveis}


def universo_da_politica() -> dict[str, list[str]]:
    """Todos os times do GitHub e canais que a política conhece, usados na revogação."""
    politica = carregar_politica()
    blocos = [politica["todos"], *politica["por_time"].values(), *politica["por_nivel"].values()]
    blocos.append(politica.get("sensiveis", {}))
    return {
        categoria: sorted({item for bloco in blocos for item in bloco.get(categoria, [])})
        for categoria in CATEGORIAS
    }


def tem_sensiveis(acessos: dict[str, Any]) -> bool:
    return any(acessos.get(categoria) for categoria in CATEGORIAS)


def _sem_acentos(texto: str) -> str:
    decomposto = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in decomposto if not unicodedata.combining(c))


def email_corporativo(nome_completo: str) -> str:
    """Regra 3: primeiro nome e último sobrenome, minúsculas, sem acentos, separados por ponto."""
    partes = [p for p in _sem_acentos(nome_completo).lower().replace("-", " ").split() if p.isalpha()]
    if len(partes) < 2:
        raise ValueError(f"nome sem sobrenome: {nome_completo!r}")
    return f"{partes[0]}.{partes[-1]}@{DOMINIO_EMAIL}"


def descrever(acessos: dict[str, Any], email: str) -> list[str]:
    """Lista legível dos acessos, no formato usado em `acessos.criados` da API."""
    itens = [f"email:{email}"] if acessos.get("email") else []
    itens += [f"github:{t}" for t in acessos.get("times_github", [])]
    itens += [f"chat:{c}" for c in acessos.get("canais", [])]
    itens += [f"nuvem:{p}" for p in acessos.get("papeis_nuvem", [])]
    return itens
