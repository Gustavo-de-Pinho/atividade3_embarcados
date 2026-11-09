"""Teste de ponta a ponta: sobe os cinco processos em portas livres e com bancos temporários,
e exercita tudo pelo gateway, como faria o REST Client.

Executar:  python -m unittest discover -s testes -v
"""
import os
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

RAIZ = Path(__file__).resolve().parent.parent
NOMES = ["quartos", "pessoas", "senhas", "acessos", "gateway"]
MODULOS = {n: ("src.gateway" if n == "gateway" else f"src.servicos.{n}") for n in NOMES}
TOKEN = "chave-de-teste"


def porta_livre():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def hora(horas):
    return (datetime.now(timezone.utc) + timedelta(hours=horas)).isoformat()


class Ambiente:
    """Cinco processos + pasta temporária de dados."""

    def __init__(self):
        self.pasta = tempfile.mkdtemp(prefix="fechaduras-")
        self.portas = {n: porta_livre() for n in NOMES}
        env = {**os.environ, "DATA_DIR": self.pasta, "ADMIN_TOKEN": TOKEN}
        for n in NOMES:
            env[f"{n.upper()}_PORT"] = str(self.portas[n])
        self.procs = {
            n: subprocess.Popen([sys.executable, "-m", MODULOS[n]], cwd=RAIZ, env=env,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            for n in NOMES
        }
        self.base = f"http://127.0.0.1:{self.portas['gateway']}"
        self.http = requests.Session()
        self.http.trust_env = False
        for n in NOMES:  # espera cada serviço responder em /health
            self._esperar(n)

    def _esperar(self, nome):
        for _ in range(200):
            try:
                if requests.get(f"http://127.0.0.1:{self.portas[nome]}/health", timeout=1).ok:
                    return
            except requests.RequestException:
                time.sleep(0.05)
        raise RuntimeError(f"serviço {nome} não iniciou")

    def req(self, metodo, caminho, corpo=None, admin=True):
        headers = {"Authorization": f"Bearer {TOKEN}"} if admin else {}
        r = self.http.request(metodo, self.base + caminho, json=corpo, headers=headers, timeout=10)
        return r.status_code, (r.json() if r.content else None)

    def parar(self, nome=None):
        for n in ([nome] if nome else NOMES):
            self.procs[n].terminate()
            try:
                self.procs[n].wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.procs[n].kill()

    def limpar(self):
        self.parar()
        time.sleep(0.2)
        for arq in Path(self.pasta).glob("*"):
            try:
                arq.unlink()
            except OSError:
                pass


class TestFluxo(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.amb = Ambiente()
        cls.n = 0

    @classmethod
    def tearDownClass(cls):
        cls.amb.limpar()

    # ---- ajudantes: cada teste cria os próprios dados ----
    def novo_cenario(self, senha="012345", inicio=None, fim=None):
        TestFluxo.n += 1
        n = TestFluxo.n
        a = self.amb
        _, quarto = a.req("POST", "/quartos", {"numero": f"Q{n}", "fechadura_id": f"FECH-{n}"})
        _, pessoa = a.req("POST", "/pessoas", {"nome": f"Pessoa {n}", "documento": f"DOC{n}"})
        corpo = {"quarto_id": quarto["id"], "pessoa_id": pessoa["id"],
                 "inicio": inicio or hora(-1), "fim": fim or hora(2)}
        if senha:
            corpo["senha"] = senha
        status, s = a.req("POST", "/senhas", corpo)
        self.assertEqual(status, 201, s)
        return quarto, pessoa, s

    def abrir(self, fechadura, senha):
        return self.amb.req("POST", "/acessos", {"fechadura_id": fechadura, "senha": senha}, admin=False)

    # ---- testes ----
    def test_rotas_administrativas_exigem_chave(self):
        for caminho in ("/quartos", "/pessoas", "/senhas", "/acessos"):
            self.assertEqual(self.amb.req("GET", caminho, admin=False)[0], 401, caminho)

    def test_rotas_internas_nao_sao_expostas(self):
        self.assertEqual(self.amb.req("POST", "/senhas/interno/verificar",
                                      {"quarto_id": 1, "senha": "1234"}, admin=False)[0], 404)
        self.assertEqual(self.amb.req("GET", "/quartos/fechadura/FECH-1")[0], 404)

    def test_quartos_cadastro_validacao_e_duplicidade(self):
        a = self.amb
        status, q = a.req("POST", "/quartos", {"numero": "A1", "descricao": "Suíte", "fechadura_id": "FA1"})
        self.assertEqual(status, 201)
        self.assertIs(q["ativo"], True)
        self.assertEqual(a.req("POST", "/quartos", {"numero": "A2", "fechadura_id": "FA1"})[0], 409)
        self.assertEqual(a.req("POST", "/quartos", {"numero": "", "fechadura_id": "X"})[0], 400)
        self.assertEqual(a.req("GET", "/quartos/999999")[0], 404)
        _, up = a.req("PUT", f"/quartos/{q['id']}", {"descricao": "Suíte master"})
        self.assertEqual(up["descricao"], "Suíte master")
        self.assertEqual(up["fechadura_id"], "FA1")

    def test_pessoas_tipos_e_documento_unico(self):
        a = self.amb
        self.assertEqual(a.req("POST", "/pessoas", {"nome": "Maria", "documento": "P111", "tipo": "hospede"})[0], 201)
        self.assertEqual(a.req("POST", "/pessoas", {"nome": "Outra", "documento": "P111"})[0], 409)
        self.assertEqual(a.req("POST", "/pessoas", {"nome": "X", "documento": "P2", "tipo": "alien"})[0], 400)
        self.assertEqual(a.req("POST", "/pessoas", {"nome": "Joana", "documento": "P222", "tipo": "funcionario"})[0], 201)
        _, funcs = a.req("GET", "/pessoas?tipo=funcionario")
        self.assertTrue(all(p["tipo"] == "funcionario" for p in funcs))

    def test_senhas_validacoes(self):
        quarto, pessoa, _ = self.novo_cenario()
        base = {"quarto_id": quarto["id"], "pessoa_id": pessoa["id"], "senha": "654321",
                "inicio": hora(-1), "fim": hora(2)}
        a = self.amb
        casos = {
            "data sem fuso": {**base, "inicio": "2026-11-05"},
            "dia inexistente": {**base, "inicio": "2026-02-30T10:00:00-03:00"},
            "fim antes do início": {**base, "fim": hora(-2)},
            "senha como número": {**base, "senha": 654321},
            "senha curta": {**base, "senha": "12"},
        }
        for nome, corpo in casos.items():
            self.assertEqual(a.req("POST", "/senhas", corpo)[0], 400, nome)
        self.assertEqual(a.req("POST", "/senhas", {**base, "pessoa_id": 999999})[0], 404)
        self.assertEqual(a.req("POST", "/senhas", {**base, "quarto_id": 999999})[0], 404)
        self.assertEqual(a.req("POST", "/senhas", {"quarto_id": 1})[0], 400)

    def test_senha_nao_expoe_codigo_nem_hash(self):
        _, _, s = self.novo_cenario(senha="012345")
        self.assertNotIn("senha", s)
        self.assertNotIn("hash", s)
        texto = str(self.amb.req("GET", "/senhas")[1])
        self.assertNotIn("012345", texto)
        self.assertNotIn("hash", texto)
        con = sqlite3.connect(Path(self.amb.pasta) / "senhas.db")
        linhas = str(con.execute("SELECT * FROM senhas").fetchall())
        con.close()
        self.assertNotIn("012345", linhas)

    def test_mesma_senha_com_periodo_sobreposto_e_recusada(self):
        quarto, pessoa, _ = self.novo_cenario(senha="111222")
        corpo = {"quarto_id": quarto["id"], "pessoa_id": pessoa["id"], "senha": "111222",
                 "inicio": hora(0), "fim": hora(1)}
        self.assertEqual(self.amb.req("POST", "/senhas", corpo)[0], 409)
        # períodos que não se sobrepõem podem repetir o código
        corpo.update(inicio=hora(10), fim=hora(12))
        self.assertEqual(self.amb.req("POST", "/senhas", corpo)[0], 201)

    def test_senha_gerada_aparece_uma_unica_vez(self):
        _, _, s = self.novo_cenario(senha=None)
        self.assertRegex(s["senha"], r"^[0-9]{6}$")
        self.assertNotIn("senha", self.amb.req("GET", f"/senhas/{s['id']}")[1])

    def test_senha_correta_abre_e_e_registrada(self):
        quarto, pessoa, s = self.novo_cenario()
        status, r = self.abrir(f"FECH-{TestFluxo.n}", "012345")
        self.assertEqual(status, 200)
        self.assertIs(r["autorizado"], True)
        self.assertEqual(r["motivo"], "ACESSO_AUTORIZADO")
        _, hist = self.amb.req("GET", f"/acessos?quarto_id={quarto['id']}&autorizado=true")
        self.assertEqual(len(hist), 1)
        self.assertEqual((hist[0]["pessoa_id"], hist[0]["senha_id"]), (pessoa["id"], s["id"]))

    def test_negativas(self):
        quarto, _, _ = self.novo_cenario(senha="123123")
        fech = f"FECH-{TestFluxo.n}"
        status, r = self.abrir(fech, "000000")
        self.assertEqual((status, r["motivo"]), (403, "SENHA_INCORRETA"))

        self.amb.req("POST", "/senhas", {"quarto_id": quarto["id"], "pessoa_id": 1,
                                         "senha": "777777", "inicio": hora(-5), "fim": hora(-4)})
        status, r = self.abrir(fech, "777777")
        self.assertEqual((status, r["motivo"]), (403, "FORA_DO_PERIODO"))

        self.novo_cenario(senha="999000")  # outro quarto, outra fechadura
        self.assertEqual(self.abrir(f"FECH-{TestFluxo.n}", "123123")[0], 403, "senha de um quarto não abre outro")

        status, r = self.abrir("NAO-EXISTE", "123123")
        self.assertEqual((status, r["motivo"]), (404, "FECHADURA_DESCONHECIDA"))

    def test_formato_da_senha_enviada_pela_fechadura(self):
        self.novo_cenario()
        fech = f"FECH-{TestFluxo.n}"
        for senha in (12345, "12", "abcdef", None):
            status, r = self.abrir(fech, senha)
            self.assertEqual(status, 400, senha)
            self.assertIs(r["autorizado"], False)

    def test_historico_e_filtros(self):
        quarto, _, _ = self.novo_cenario(senha="424242")
        fech = f"FECH-{TestFluxo.n}"
        self.abrir(fech, "424242")
        self.abrir(fech, "000000")
        _, todos = self.amb.req("GET", f"/acessos?quarto_id={quarto['id']}")
        self.assertEqual(len(todos), 2)
        _, negados = self.amb.req("GET", f"/acessos?quarto_id={quarto['id']}&autorizado=false")
        self.assertEqual([a["motivo"] for a in negados], ["SENHA_INCORRETA"])
        self.assertEqual(self.amb.req("GET", "/acessos?quarto_id=abc")[0], 400)
        self.assertEqual(self.amb.req("GET", "/acessos?autorizado=talvez")[0], 400)

    def test_revogar_senha_impede_novo_acesso(self):
        _, _, s = self.novo_cenario()
        fech = f"FECH-{TestFluxo.n}"
        self.assertEqual(self.abrir(fech, "012345")[0], 200)
        self.assertEqual(self.amb.req("DELETE", f"/senhas/{s['id']}")[0], 204)
        status, r = self.abrir(fech, "012345")
        self.assertEqual((status, r["motivo"]), (403, "SENHA_INCORRETA"))
        self.assertIs(self.amb.req("GET", f"/senhas/{s['id']}")[1]["ativa"], False)

    def test_pessoa_e_quarto_inativos_nao_abrem(self):
        quarto, pessoa, _ = self.novo_cenario()
        fech = f"FECH-{TestFluxo.n}"
        a = self.amb
        self.assertEqual(a.req("DELETE", f"/pessoas/{pessoa['id']}")[0], 204)
        self.assertEqual(self.abrir(fech, "012345")[1]["motivo"], "PESSOA_INATIVA")
        a.req("PUT", f"/pessoas/{pessoa['id']}", {"ativo": True})
        self.assertEqual(self.abrir(fech, "012345")[0], 200)
        self.assertEqual(a.req("DELETE", f"/quartos/{quarto['id']}")[0], 204)
        self.assertEqual(self.abrir(fech, "012345")[1]["motivo"], "QUARTO_INATIVO")
        corpo = {"quarto_id": quarto["id"], "pessoa_id": pessoa["id"], "senha": "5555",
                 "inicio": hora(-1), "fim": hora(1)}
        self.assertEqual(a.req("POST", "/senhas", corpo)[0], 400, "não cadastra senha para quarto inativo")


class TestFalhas(unittest.TestCase):
    """Cada teste sobe um ambiente novo, porque derruba serviços."""

    def setUp(self):
        self.amb = Ambiente()
        a = self.amb
        _, q = a.req("POST", "/quartos", {"numero": "1", "fechadura_id": "F1"})
        _, p = a.req("POST", "/pessoas", {"nome": "Ana", "documento": "1"})
        a.req("POST", "/senhas", {"quarto_id": q["id"], "pessoa_id": p["id"], "senha": "012345",
                                  "inicio": hora(-1), "fim": hora(2)})
        self.addCleanup(a.limpar)

    def abrir(self):
        return self.amb.req("POST", "/acessos", {"fechadura_id": "F1", "senha": "012345"}, admin=False)

    def test_servico_de_senhas_fora_do_ar_nega_e_registra(self):
        self.assertEqual(self.abrir()[0], 200)
        antes = len(self.amb.req("GET", "/acessos")[1])
        self.amb.parar("senhas")
        status, r = self.abrir()
        self.assertEqual(status, 503)
        self.assertIs(r["autorizado"], False)
        self.assertEqual(r["motivo"], "SERVICO_INDISPONIVEL")
        hist = self.amb.req("GET", "/acessos")[1]
        self.assertEqual(len(hist), antes + 1)
        self.assertEqual(hist[0]["motivo"], "SERVICO_INDISPONIVEL")

    def test_servico_de_quartos_fora_do_ar_nega(self):
        self.amb.parar("quartos")
        status, r = self.abrir()
        self.assertEqual((status, r["motivo"]), (503, "SERVICO_INDISPONIVEL"))

    def test_servico_de_acessos_fora_do_ar_gateway_responde_503(self):
        self.amb.parar("acessos")
        self.assertEqual(self.abrir()[0], 503)


if __name__ == "__main__":
    unittest.main()
