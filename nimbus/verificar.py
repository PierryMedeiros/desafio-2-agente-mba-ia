"""Verificador de acessos da Nimbus.

Compara o consolidado de `GET /admin/estado` com o que `dados/politica.json`
manda para a pessoa e imprime o que está faltando, sobrando ou duplicado.

Códigos de saída: 0 quando está tudo conforme, 1 quando há divergência e 2
quando os argumentos são inválidos ou os sistemas não respondem.
"""

import argparse
import os
import sys
from typing import Any

import httpx

from nimbus.estado import CAMINHO_DIRETORIO, CAMINHO_POLITICA, calcular_acessos, carregar_json

URL_PADRAO = os.environ.get("NIMBUS_SISTEMAS_URL", "http://localhost:8100")

Acesso = tuple[str, str]
NOMES_SISTEMAS = {"email": "e-mail", "github": "github", "chat": "chat", "nuvem": "nuvem"}


def montar_argumentos() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="nimbus-verificar",
        description="Compara os acessos de uma pessoa nos sistemas da Nimbus com a política.",
    )
    parser.add_argument("--pessoa", required=True, help="e-mail corporativo da pessoa")
    parser.add_argument("--time", help="id do time, por exemplo pagamentos")
    parser.add_argument("--cargo", help="id do cargo, por exemplo engenheiro-de-software")
    parser.add_argument("--nivel", help="junior, pleno ou senior")
    parser.add_argument(
        "--sem-sensiveis",
        action="store_true",
        help="espera ausentes os acessos marcados como sensíveis na política",
    )
    parser.add_argument("--desligado", action="store_true", help="espera nenhum acesso em nenhum sistema")
    parser.add_argument("--url", default=URL_PADRAO, help=f"endereço dos sistemas (padrão {URL_PADRAO})")
    return parser


def validar(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    if args.desligado:
        if args.time or args.cargo or args.nivel or args.sem_sensiveis:
            parser.error("--desligado não se combina com --time, --cargo, --nivel nem --sem-sensiveis")
        return
    if not (args.time and args.cargo and args.nivel):
        parser.error("informe --time, --cargo e --nivel, ou use --desligado")
    diretorio = carregar_json(CAMINHO_DIRETORIO)
    times = [t["id"] for t in diretorio["times"]]
    cargos = [c["id"] for c in diretorio["cargos"]]
    niveis = diretorio["niveis"]
    if args.time not in times:
        parser.error(f"time desconhecido: {args.time}. Válidos: {', '.join(times)}")
    if args.cargo not in cargos:
        parser.error(f"cargo desconhecido: {args.cargo}. Válidos: {', '.join(cargos)}")
    if args.nivel not in niveis:
        parser.error(f"nível desconhecido: {args.nivel}. Válidos: {', '.join(niveis)}")


def acessos_esperados(args: argparse.Namespace) -> set[Acesso]:
    if args.desligado:
        return set()
    politica = carregar_json(CAMINHO_POLITICA)
    acessos = calcular_acessos(politica, args.time, args.nivel)
    if args.sem_sensiveis:
        sensiveis = politica.get("sensiveis", {})
        for chave in ("times_github", "canais", "papeis_nuvem"):
            acessos[chave] = [a for a in acessos[chave] if a not in sensiveis.get(chave, [])]
    esperados: set[Acesso] = set()
    if acessos["email"]:
        esperados.add(("email", "conta"))
    esperados |= {("github", t) for t in acessos["times_github"]}
    esperados |= {("chat", c) for c in acessos["canais"]}
    esperados |= {("nuvem", p) for p in acessos["papeis_nuvem"]}
    return esperados


def acessos_encontrados(consolidado: dict[str, Any]) -> tuple[dict[Acesso, int], set[Acesso]]:
    """Devolve a quantidade de registros por acesso e o conjunto de sensíveis."""
    contagem: dict[Acesso, int] = {}
    if consolidado["email"]:
        contagem[("email", "conta")] = 1
    for time in consolidado["times_github"]:
        contagem[("github", time)] = 1
    for canal in consolidado["canais"]:
        contagem[("chat", canal["canal"])] = canal["registros"]
    for papel in consolidado["papeis_nuvem"]:
        contagem[("nuvem", papel["papel"])] = papel["atribuicoes"]
    politica = carregar_json(CAMINHO_POLITICA)
    sensiveis_politica = politica.get("sensiveis", {})
    sensiveis = {("github", t) for t in sensiveis_politica.get("times_github", [])}
    sensiveis |= {("chat", c) for c in sensiveis_politica.get("canais", [])}
    sensiveis |= {("nuvem", p) for p in sensiveis_politica.get("papeis_nuvem", [])}
    return contagem, sensiveis


def ordenar(acessos: set[Acesso]) -> list[Acesso]:
    ordem = list(NOMES_SISTEMAS)
    return sorted(acessos, key=lambda a: (ordem.index(a[0]), a[1]))


def descrever(acesso: Acesso) -> str:
    return f"{NOMES_SISTEMAS[acesso[0]]}: {acesso[1]}"


def imprimir_tabela(linhas: list[list[str]]) -> None:
    cabecalho = ["Sistema", "Acesso", "Esperado", "Encontrado", "Situação"]
    larguras = [max(len(str(linha[i])) for linha in [cabecalho, *linhas]) for i in range(len(cabecalho))]

    def formatar(linha: list[str]) -> str:
        return "  ".join(str(celula).ljust(largura) for celula, largura in zip(linha, larguras)).rstrip()

    print(formatar(cabecalho))
    print("  ".join("-" * largura for largura in larguras))
    for linha in linhas:
        print(formatar(linha))


def imprimir_lista(titulo: str, itens: list[str]) -> None:
    print(f"{titulo} ({len(itens)}):")
    if not itens:
        print("  nenhum")
    for item in itens:
        print(f"  - {item}")


def main() -> None:
    parser = montar_argumentos()
    args = parser.parse_args()
    validar(parser, args)

    try:
        resposta = httpx.get(f"{args.url}/admin/estado", params={"email": args.pessoa}, timeout=10)
        resposta.raise_for_status()
    except httpx.HTTPError as erro:
        print(f"Não foi possível consultar {args.url}/admin/estado: {erro}", file=sys.stderr)
        sys.exit(2)

    esperados = acessos_esperados(args)
    encontrados, sensiveis = acessos_encontrados(resposta.json())

    faltando = ordenar(esperados - set(encontrados))
    sobrando = ordenar(set(encontrados) - esperados)
    duplicados = ordenar({a for a, n in encontrados.items() if n > 1})

    linhas = []
    for acesso in ordenar(esperados | set(encontrados)):
        quantidade = encontrados.get(acesso, 0)
        if acesso in faltando:
            situacao = "faltando"
        elif acesso in sobrando:
            situacao = "sobrando"
        elif quantidade > 1:
            situacao = "duplicado"
        else:
            situacao = "ok"
        if acesso in sobrando and quantidade > 1:
            situacao = "sobrando e duplicado"
        nome = acesso[1] + (" (sensível)" if acesso in sensiveis else "")
        esperado = "sim" if acesso in esperados else "não"
        linhas.append([NOMES_SISTEMAS[acesso[0]], nome, esperado, str(quantidade), situacao])

    print(f"Pessoa: {args.pessoa}")
    if args.desligado:
        print("Cenário: desligamento, nenhum acesso esperado")
    else:
        extra = ", sem acessos sensíveis" if args.sem_sensiveis else ""
        print(f"Cenário: time {args.time}, cargo {args.cargo}, nível {args.nivel}{extra}")
    print()
    if linhas:
        imprimir_tabela(linhas)
    else:
        print("Nenhum acesso esperado e nenhum acesso encontrado.")
    print()
    imprimir_lista("Faltando", [descrever(a) for a in faltando])
    imprimir_lista("Sobrando", [descrever(a) for a in sobrando])
    duplicados_desc = [f"{descrever(a)} ({encontrados[a]} registros)" for a in duplicados]
    imprimir_lista("Duplicados", duplicados_desc)
    print()

    if faltando or sobrando or duplicados:
        print("Resultado: DIVERGENTE")
        sys.exit(1)
    print("Resultado: CONFORME")
    sys.exit(0)


if __name__ == "__main__":
    main()
