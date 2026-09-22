import pytest
from fastapi.testclient import TestClient

from nimbus import estado as modulo_estado
from nimbus.sistemas import app

MARCOS = "marcos.vieira@nimbus.dev"
PRISCILA = "priscila.alencar@nimbus.dev"
NOVA = "ana.souza@nimbus.dev"


@pytest.fixture
def cliente(monkeypatch):
    monkeypatch.setattr(modulo_estado, "ESPERA_ESCRITA_MS", 5)
    modulo_estado.reset()
    with TestClient(app) as cliente:
        yield cliente
    modulo_estado.reset()


def registro(cliente):
    return cliente.get("/admin/registro").json()


def test_email_recusa_segunda_criacao(cliente):
    primeira = cliente.post("/email/contas", json={"email": NOVA})
    segunda = cliente.post("/email/contas", json={"email": NOVA})

    assert primeira.status_code == 201
    assert segunda.status_code == 409
    assert segunda.json() == {"erro": "conta já existe"}
    assert [c["efeito"] for c in registro(cliente)] == ["criado", "ja_existia"]


def test_github_responde_200_nas_duas_chamadas(cliente):
    primeira = cliente.put(f"/github/times/risco/membros/{NOVA}")
    segunda = cliente.put(f"/github/times/risco/membros/{NOVA}")

    assert primeira.status_code == 200
    assert segunda.status_code == 200
    assert primeira.json()["ja_era_membro"] is False
    assert segunda.json()["ja_era_membro"] is True
    assert [c["efeito"] for c in registro(cliente)] == ["criado", "ja_existia"]


def test_chat_sem_chave_duplica(cliente):
    primeira = cliente.post("/chat/canais/risco/membros", json={"email": NOVA})
    segunda = cliente.post("/chat/canais/risco/membros", json={"email": NOVA})

    assert primeira.status_code == 201
    assert segunda.status_code == 201
    membros = cliente.get("/chat/canais/risco/membros").json()["registros"]
    assert [r["email"] for r in membros].count(NOVA) == 2
    efeitos = [c["efeito"] for c in registro(cliente) if c["operacao"] == "adicionar_membro"]
    assert efeitos == ["criado", "duplicado"]


def test_chat_com_mesma_chave_devolve_registro_anterior(cliente):
    cabecalho = {"Idempotency-Key": "admissao-ana-risco"}
    primeira = cliente.post("/chat/canais/risco/membros", json={"email": NOVA}, headers=cabecalho)
    segunda = cliente.post("/chat/canais/risco/membros", json={"email": NOVA}, headers=cabecalho)

    assert primeira.status_code == 201
    assert segunda.status_code == 200
    assert segunda.json() == primeira.json()
    membros = cliente.get("/chat/canais/risco/membros").json()["registros"]
    assert [r["email"] for r in membros].count(NOVA) == 1
    efeitos = [c["efeito"] for c in registro(cliente) if c["operacao"] == "adicionar_membro"]
    assert efeitos == ["criado", "ja_existia"]


def test_nuvem_cria_duas_atribuicoes_iguais(cliente):
    corpo = {"email": NOVA, "papel": "risco-leitura"}
    primeira = cliente.post("/nuvem/papeis", json=corpo)
    segunda = cliente.post("/nuvem/papeis", json=corpo)

    assert primeira.status_code == 201
    assert segunda.status_code == 201
    assert primeira.json()["id"] != segunda.json()["id"]
    atribuicoes = cliente.get("/nuvem/papeis", params={"email": NOVA}).json()["atribuicoes"]
    assert len(atribuicoes) == 2
    assert [c["efeito"] for c in registro(cliente) if c["operacao"] == "atribuir_papel"] == ["criado", "duplicado"]


def test_modo_indisponivel_responde_503_sem_alterar_estado(cliente):
    resposta = cliente.post("/admin/falhas", json={"email": {"modo": "indisponivel", "vezes": 1}})
    assert resposta.status_code == 200

    falhou = cliente.post("/email/contas", json={"email": NOVA})
    assert falhou.status_code == 503
    assert cliente.get("/admin/estado", params={"email": NOVA}).json()["email"] is False

    depois = cliente.post("/email/contas", json={"email": NOVA})
    assert depois.status_code == 201
    assert cliente.get("/admin/falhas").json()["email"] == {"modo": "nenhum"}


def test_modo_grava_e_falha_responde_504_e_altera_estado(cliente):
    cliente.post("/admin/falhas", json={"nuvem": {"modo": "grava_e_falha", "vezes": 1}})

    resposta = cliente.post("/nuvem/papeis", json={"email": NOVA, "papel": "risco-leitura"})

    assert resposta.status_code == 504
    consolidado = cliente.get("/admin/estado", params={"email": NOVA}).json()
    assert consolidado["papeis_nuvem"] == [{"papel": "risco-leitura", "atribuicoes": 1}]


def test_reset_devolve_estado_inicial(cliente):
    cliente.delete(f"/email/contas/{MARCOS}")
    cliente.post("/email/contas", json={"email": NOVA})
    cliente.post("/admin/falhas", json={"chat": {"modo": "indisponivel", "vezes": 3}})

    assert cliente.post("/admin/reset").status_code == 200

    assert registro(cliente) == []
    assert all(c == {"modo": "nenhum"} for c in cliente.get("/admin/falhas").json().values())
    assert cliente.get("/admin/estado", params={"email": NOVA}).json()["email"] is False
    assert cliente.get("/admin/estado", params={"email": MARCOS}).json() == {
        "email": True,
        "times_github": ["pagamentos"],
        "canais": [
            {"canal": "avisos", "registros": 1},
            {"canal": "geral", "registros": 1},
            {"canal": "pagamentos", "registros": 1},
        ],
        "papeis_nuvem": [
            {"papel": "deploy-homolog", "atribuicoes": 1},
            {"papel": "deploy-producao", "atribuicoes": 1},
            {"papel": "leitura-basica", "atribuicoes": 1},
            {"papel": "pagamentos-leitura", "atribuicoes": 1},
        ],
    }
    assert cliente.get("/admin/estado", params={"email": PRISCILA}).json() == {
        "email": True,
        "times_github": ["dados"],
        "canais": [
            {"canal": "avisos", "registros": 1},
            {"canal": "dados", "registros": 1},
            {"canal": "geral", "registros": 1},
        ],
        "papeis_nuvem": [
            {"papel": "dados-leitura", "atribuicoes": 1},
            {"papel": "deploy-homolog", "atribuicoes": 1},
            {"papel": "leitura-basica", "atribuicoes": 1},
        ],
    }


def test_registro_guarda_chamada_que_falhou(cliente):
    cliente.post("/admin/falhas", json={"chat": {"modo": "indisponivel", "vezes": 1}})

    resposta = cliente.post("/chat/canais/geral/membros", json={"email": NOVA})

    assert resposta.status_code == 503
    [chamada] = registro(cliente)
    assert chamada["sistema"] == "chat"
    assert chamada["operacao"] == "adicionar_membro"
    assert chamada["alvo"] == f"geral:{NOVA}"
    assert chamada["corpo"] == {"email": NOVA}
    assert chamada["status"] == 503
    assert chamada["efeito"] == "nenhum"
    assert chamada["seq"] == 1
    assert chamada["inicio"] <= chamada["fim"]


def test_registro_guarda_chamada_invalida(cliente):
    resposta = cliente.post("/email/contas", json={"mail": NOVA})

    assert resposta.status_code == 422
    assert resposta.json()["erro"] == "requisição inválida"
    [chamada] = registro(cliente)
    assert chamada["operacao"] == "criar_conta"
    assert chamada["corpo"] == {"mail": NOVA}
    assert chamada["status"] == 422
    assert chamada["efeito"] == "nenhum"
