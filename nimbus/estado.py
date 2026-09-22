"""Estado em memória dos quatro sistemas simulados da Nimbus.

Guarda as contas de e-mail, os membros dos times do GitHub, os registros dos
canais de chat, as atribuições de papéis na nuvem, o registro de chamadas e a
configuração de falhas. Tudo vive na memória do processo e `reset()` devolve
ao estado inicial.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

RAIZ = Path(__file__).resolve().parent.parent
DADOS = RAIZ / "dados"
CAMINHO_DIRETORIO = DADOS / "diretorio.json"
CAMINHO_POLITICA = DADOS / "politica.json"

SISTEMAS = ("email", "github", "chat", "nuvem")
EFEITOS = ("criado", "ja_existia", "duplicado", "removido", "nao_encontrado", "nenhum")
MODOS_FALHA = ("indisponivel", "grava_e_falha", "lento", "nenhum")

# Espera aplicada a toda operação de escrita, em milissegundos. Os testes
# reduzem esse valor para a suíte não ficar lenta.
ESPERA_ESCRITA_MS = int(os.environ.get("NIMBUS_ESPERA_MS", "800"))


def carregar_json(caminho: Path) -> dict[str, Any]:
    with caminho.open(encoding="utf-8") as arquivo:
        return json.load(arquivo)


def agora_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _sem_repetir(itens: list[str]) -> list[str]:
    return list(dict.fromkeys(itens))


def calcular_acessos(politica: dict[str, Any], time: str, nivel: str) -> dict[str, Any]:
    """Aplica a política a um time e um nível e devolve os acessos esperados."""
    todos = politica.get("todos", {})
    do_time = politica.get("por_time", {}).get(time, {})
    do_nivel = politica.get("por_nivel", {}).get(nivel, {})
    camadas = (todos, do_time, do_nivel)
    return {
        "email": any(camada.get("email", False) for camada in camadas),
        "times_github": _sem_repetir([t for c in camadas for t in c.get("times_github", [])]),
        "canais": _sem_repetir([t for c in camadas for t in c.get("canais", [])]),
        "papeis_nuvem": _sem_repetir([t for c in camadas for t in c.get("papeis_nuvem", [])]),
    }


class Estado:
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.contas_email: set[str] = set()
        self.times_github: dict[str, set[str]] = {}
        self.canais_chat: dict[str, list[dict[str, Any]]] = {}
        self.chaves_chat: dict[tuple[str, str], dict[str, Any]] = {}
        self.papeis_nuvem: list[dict[str, Any]] = []
        self.registro: list[dict[str, Any]] = []
        self.falhas: dict[str, dict[str, Any]] = {}
        self._seq_registro = 0
        self._seq_chat = 0
        self._seq_nuvem = 0
        self._carregar_estado_inicial()

    def _carregar_estado_inicial(self) -> None:
        diretorio = carregar_json(CAMINHO_DIRETORIO)
        politica = carregar_json(CAMINHO_POLITICA)
        for colaborador in diretorio["colaboradores"]:
            if colaborador.get("situacao") != "ativo":
                continue
            email = colaborador["email"]
            acessos = calcular_acessos(politica, colaborador["time"], colaborador["nivel"])
            if acessos["email"]:
                self.contas_email.add(email)
            for time in acessos["times_github"]:
                self.times_github.setdefault(time, set()).add(email)
            for canal in acessos["canais"]:
                self.novo_registro_chat(canal, email)
            for papel in acessos["papeis_nuvem"]:
                self.nova_atribuicao_nuvem(email, papel)

    # Chat e nuvem

    def novo_registro_chat(self, canal: str, email: str) -> dict[str, Any]:
        self._seq_chat += 1
        registro = {"id": f"chat-{self._seq_chat}", "canal": canal, "email": email, "criado_em": agora_iso()}
        self.canais_chat.setdefault(canal, []).append(registro)
        return registro

    def nova_atribuicao_nuvem(self, email: str, papel: str) -> dict[str, Any]:
        self._seq_nuvem += 1
        atribuicao = {"id": f"atr-{self._seq_nuvem}", "email": email, "papel": papel}
        self.papeis_nuvem.append(atribuicao)
        return atribuicao

    # Registro de chamadas

    def proximo_seq(self) -> int:
        self._seq_registro += 1
        return self._seq_registro

    def registrar(
        self,
        *,
        seq: int,
        inicio: str,
        sistema: str,
        operacao: str,
        alvo: str,
        corpo: Any,
        status: int,
        efeito: str,
    ) -> None:
        if efeito not in EFEITOS:
            raise ValueError(f"efeito desconhecido: {efeito}")
        self.registro.append(
            {
                "seq": seq,
                "inicio": inicio,
                "fim": agora_iso(),
                "sistema": sistema,
                "operacao": operacao,
                "alvo": alvo,
                "corpo": corpo,
                "status": status,
                "efeito": efeito,
            }
        )
        self.registro.sort(key=lambda chamada: chamada["seq"])

    # Configuração de falhas

    def configurar_falha(self, sistema: str, modo: str, vezes: int, ms: int | None) -> None:
        if modo == "nenhum":
            self.falhas.pop(sistema, None)
            return
        config: dict[str, Any] = {"modo": modo, "vezes": vezes}
        if modo == "lento":
            config["ms"] = ms
        self.falhas[sistema] = config

    def consumir_falha(self, sistema: str) -> dict[str, Any] | None:
        """Devolve a falha configurada para esta chamada de escrita e desconta uma vez."""
        config = self.falhas.get(sistema)
        if config is None:
            return None
        atual = dict(config)
        config["vezes"] -= 1
        if config["vezes"] <= 0:
            del self.falhas[sistema]
        return atual

    def config_falhas(self) -> dict[str, dict[str, Any]]:
        return {sistema: dict(self.falhas.get(sistema, {"modo": "nenhum"})) for sistema in SISTEMAS}

    # Consolidado por pessoa

    def consolidado(self, email: str) -> dict[str, Any]:
        canais = []
        for canal in sorted(self.canais_chat):
            registros = sum(1 for r in self.canais_chat[canal] if r["email"] == email)
            if registros:
                canais.append({"canal": canal, "registros": registros})
        contagem_papeis: dict[str, int] = {}
        for atribuicao in self.papeis_nuvem:
            if atribuicao["email"] == email:
                contagem_papeis[atribuicao["papel"]] = contagem_papeis.get(atribuicao["papel"], 0) + 1
        return {
            "email": email in self.contas_email,
            "times_github": sorted(t for t, membros in self.times_github.items() if email in membros),
            "canais": canais,
            "papeis_nuvem": [{"papel": p, "atribuicoes": n} for p, n in sorted(contagem_papeis.items())],
        }


estado = Estado()


def reset() -> None:
    estado.reset()
