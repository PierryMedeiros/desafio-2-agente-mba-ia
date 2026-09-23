"""Garantia 3: cada acesso acontece uma vez só.

Cada sistema reage de um jeito à chamada repetida, então cada um tem a sua
estratégia para que repetir seja seguro:

- e-mail: `409` na criação significa que a conta já existe, e isso é sucesso;
  `404` na remoção significa que ela já não existe, e isso também é sucesso.
- GitHub: `PUT` e `DELETE` já são idempotentes; basta repetir.
- chat: toda inclusão leva `Idempotency-Key` derivada do pedido, do canal e do
  e-mail. Se a chamada gravou e respondeu erro, a repetição devolve `200` com o
  registro anterior em vez de duplicar. Antes de incluir, a lista do canal é
  consultada, para não duplicar quem já estava lá.
- nuvem: não há chave de idempotência, então cada tentativa começa lendo as
  atribuições da pessoa e só cria os papéis que ainda não existem. Uma chamada
  que gravou e respondeu `504` aparece nessa leitura e não é refeita.

Toda falha que não é sucesso levanta `FalhaSistema`. Quem repete é o
`RetryConfig` do nó do workflow, e como cada operação acima é idempotente, a
repetição do nó inteiro é segura. Cada chamada vira um registro para a trilha.
"""

import asyncio
import time
from datetime import datetime, timezone
from typing import Any

import httpx

from esteira.config import SISTEMAS_URL
from esteira.politica import universo_da_politica

# Tempo generoso: cada escrita leva cerca de 800 ms. Se o cliente desistir
# antes do servidor gravar, a leitura da próxima tentativa mostra o efeito.
TIMEOUT = httpx.Timeout(30.0)


class FalhaSistema(RuntimeError):
    """Chamada que não chegou a um resultado aceitável; o nó será repetido."""


class Chamadas:
    """Faz as chamadas HTTP e guarda um registro de cada uma para a trilha."""

    def __init__(self, sistema: str) -> None:
        self.sistema = sistema
        self.registros: list[dict[str, Any]] = []
        self._cliente = httpx.AsyncClient(base_url=SISTEMAS_URL, timeout=TIMEOUT)

    async def __aenter__(self) -> "Chamadas":
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self._cliente.aclose()

    async def http(self, metodo: str, caminho: str, *, aceitos: dict[int, str], **kwargs: Any) -> httpx.Response | None:
        """Faz a chamada, registra e devolve a resposta quando o status é aceito."""
        inicio = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        relogio = time.monotonic()
        registro: dict[str, Any] = {"sistema": self.sistema, "metodo": metodo, "caminho": caminho, "inicio": inicio}
        try:
            resposta = await self._cliente.request(metodo, caminho, **kwargs)
        except httpx.HTTPError as erro:
            registro.update(status=None, resultado="erro_de_rede", erro=str(erro))
            self._fechar(registro, relogio)
            raise FalhaSistema(f"{self.sistema}: {metodo} {caminho}: {erro}") from erro
        registro["status"] = resposta.status_code
        registro["resultado"] = aceitos.get(resposta.status_code, "falhou")
        self._fechar(registro, relogio)
        if resposta.status_code not in aceitos:
            raise FalhaSistema(f"{self.sistema}: {metodo} {caminho} respondeu {resposta.status_code}")
        return resposta

    def _fechar(self, registro: dict[str, Any], relogio: float) -> None:
        registro["duracao_ms"] = round((time.monotonic() - relogio) * 1000)
        self.registros.append(registro)


async def em_paralelo(*operacoes: Any) -> None:
    """Roda as operações juntas e só depois propaga a primeira falha.

    Esperar todas antes de levantar evita cancelar no meio uma escrita que o
    servidor já aplicou, e deixa todas as chamadas registradas na trilha.
    """
    resultados = await asyncio.gather(*operacoes, return_exceptions=True)
    for resultado in resultados:
        if isinstance(resultado, BaseException):
            raise resultado


# E-mail


async def criar_email(ch: Chamadas, email: str) -> None:
    await ch.http("POST", "/email/contas", json={"email": email}, aceitos={201: "criado", 409: "ja_existia"})


async def revogar_email(ch: Chamadas, email: str) -> list[str]:
    resposta = await ch.http("DELETE", f"/email/contas/{email}", aceitos={204: "removido", 404: "nao_existia"})
    return [f"email:{email}"] if resposta.status_code == 204 else []


# GitHub


async def criar_github(ch: Chamadas, email: str, times: list[str]) -> None:
    await em_paralelo(
        *(ch.http("PUT", f"/github/times/{t}/membros/{email}", aceitos={200: "ok"}) for t in times)
    )


async def revogar_github(ch: Chamadas, email: str) -> list[str]:
    times = universo_da_politica()["times_github"]
    listas = await asyncio.gather(
        *(ch.http("GET", f"/github/times/{t}/membros", aceitos={200: "consulta"}) for t in times)
    )
    presentes = [t for t, r in zip(times, listas) if email in r.json()["membros"]]
    await em_paralelo(
        *(ch.http("DELETE", f"/github/times/{t}/membros/{email}", aceitos={204: "removido"}) for t in presentes)
    )
    return [f"github:{t}" for t in presentes]


# Chat


async def criar_chat(ch: Chamadas, email: str, canais: list[str], chave_pedido: str) -> None:
    async def incluir(canal: str) -> None:
        lista = await ch.http("GET", f"/chat/canais/{canal}/membros", aceitos={200: "consulta"})
        if any(r["email"] == email for r in lista.json()["registros"]):
            return
        await ch.http(
            "POST",
            f"/chat/canais/{canal}/membros",
            json={"email": email},
            headers={"Idempotency-Key": f"{chave_pedido}:{canal}:{email}"},
            aceitos={201: "criado", 200: "ja_existia"},
        )

    await em_paralelo(*(incluir(c) for c in canais))


async def revogar_chat(ch: Chamadas, email: str) -> list[str]:
    canais = universo_da_politica()["canais"]
    listas = await asyncio.gather(
        *(ch.http("GET", f"/chat/canais/{c}/membros", aceitos={200: "consulta"}) for c in canais)
    )
    presentes = [c for c, r in zip(canais, listas) if any(x["email"] == email for x in r.json()["registros"])]
    await em_paralelo(
        *(ch.http("DELETE", f"/chat/canais/{c}/membros/{email}", aceitos={204: "removido"}) for c in presentes)
    )
    return [f"chat:{c}" for c in presentes]


# Nuvem


async def _atribuicoes(ch: Chamadas, email: str) -> list[dict[str, Any]]:
    resposta = await ch.http("GET", "/nuvem/papeis", params={"email": email}, aceitos={200: "consulta"})
    return resposta.json()["atribuicoes"]


async def criar_nuvem(ch: Chamadas, email: str, papeis: list[str]) -> None:
    existentes = {a["papel"] for a in await _atribuicoes(ch, email)}
    faltando = [p for p in papeis if p not in existentes]
    await em_paralelo(
        *(
            ch.http("POST", "/nuvem/papeis", json={"email": email, "papel": p}, aceitos={201: "criado"})
            for p in faltando
        )
    )


async def revogar_nuvem(ch: Chamadas, email: str) -> list[str]:
    atribuicoes = await _atribuicoes(ch, email)
    await em_paralelo(
        *(
            ch.http("DELETE", f"/nuvem/papeis/{a['id']}", aceitos={204: "removido", 404: "nao_existia"})
            for a in atribuicoes
        )
    )
    return [f"nuvem:{a['papel']}" for a in atribuicoes]
