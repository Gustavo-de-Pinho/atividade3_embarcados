"""Funções compartilhadas pelos serviços. Só reúne utilitários: nenhum dado é compartilhado."""
import os
import re
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

import requests
from flask import Flask, jsonify, request

RAIZ = Path(__file__).resolve().parent.parent


def _carregar_env():
    """Lê o arquivo .env (se existir) sem sobrescrever variáveis já definidas."""
    arquivo = RAIZ / ".env"
    if not arquivo.exists():
        return
    for linha in arquivo.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if linha and not linha.startswith("#") and "=" in linha:
            chave, valor = linha.split("=", 1)
            os.environ.setdefault(chave.strip(), valor.strip())


_carregar_env()

HOST = "127.0.0.1"
PORTAS = {
    "gateway": int(os.environ.get("GATEWAY_PORT", 3000)),
    "quartos": int(os.environ.get("QUARTOS_PORT", 3001)),
    "pessoas": int(os.environ.get("PESSOAS_PORT", 3002)),
    "senhas": int(os.environ.get("SENHAS_PORT", 3003)),
    "acessos": int(os.environ.get("ACESSOS_PORT", 3004)),
}


# ---------- erros e validações ----------
class ErroHttp(Exception):
    def __init__(self, status, mensagem):
        super().__init__(mensagem)
        self.status = status
        self.mensagem = mensagem


def exigir(condicao, mensagem):
    """Se a condição for falsa, interrompe a requisição com 400."""
    if not condicao:
        raise ErroHttp(400, mensagem)


def texto(valor, campo, maximo=150):
    exigir(
        isinstance(valor, str) and 0 < len(valor.strip()) and len(valor) <= maximo,
        f"{campo} deve ser um texto de 1 a {maximo} caracteres.",
    )
    return valor.strip()


def id_valido(valor):
    ok = (isinstance(valor, int) and not isinstance(valor, bool) and valor > 0) or (
        isinstance(valor, str) and re.fullmatch(r"[1-9][0-9]*", valor) is not None
    )
    exigir(ok, "ID inválido.")
    return int(valor)


def corpo_json():
    """Corpo da requisição, já garantido como objeto JSON."""
    corpo = request.get_json(silent=True)
    exigir(isinstance(corpo, dict), "Envie um objeto JSON no corpo da requisição.")
    return corpo


# ---------- datas ----------
def agora_iso():
    return para_iso(datetime.now(timezone.utc))


def para_iso(dt):
    """ISO 8601 em UTC com milissegundos: comparar as strings equivale a comparar as datas."""
    return dt.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


_PADRAO_DATA = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?(Z|[+-]\d{2}:\d{2})")


def data_iso(valor, campo):
    """Exige fuso horário (ex.: 2026-11-09T14:00:00-03:00) e converte para ISO em UTC."""
    mensagem = f"{campo} deve ser data ISO 8601 com fuso, como 2026-11-09T14:00:00-03:00."
    exigir(isinstance(valor, str) and _PADRAO_DATA.fullmatch(valor), mensagem)
    try:
        dt = datetime.fromisoformat(valor.replace("Z", "+00:00"))
    except ValueError:
        raise ErroHttp(400, mensagem + " (a data não existe)")
    return para_iso(dt)


# ---------- banco de dados ----------
class Banco:
    """Um arquivo SQLite por serviço. Cada operação abre e fecha a sua conexão,
    o que é seguro mesmo com várias requisições ao mesmo tempo."""

    def __init__(self, nome, esquema):
        pasta = Path(os.environ.get("DATA_DIR", "dados"))
        if not pasta.is_absolute():
            pasta = RAIZ / pasta
        pasta.mkdir(parents=True, exist_ok=True)
        self.caminho = pasta / f"{nome}.db"
        with closing(self._conectar()) as con, con:
            con.execute("PRAGMA journal_mode = WAL")
            con.executescript(esquema)

    def _conectar(self):
        con = sqlite3.connect(self.caminho, timeout=5)
        con.row_factory = sqlite3.Row
        return con

    def todos(self, sql, params=()):
        with closing(self._conectar()) as con:
            return [dict(l) for l in con.execute(sql, params).fetchall()]

    def um(self, sql, params=()):
        with closing(self._conectar()) as con:
            linha = con.execute(sql, params).fetchone()
            return dict(linha) if linha else None

    def executar(self, sql, params=()):
        """Executa uma escrita e devolve o id do registro criado."""
        with closing(self._conectar()) as con, con:  # `with con` confirma (commit) a transação
            return con.execute(sql, params).lastrowid


def buscar(db, tabela, id_):
    """Lê um registro pelo ID ou lança 404. `tabela` vem sempre de constantes do código."""
    registro = db.um(f"SELECT * FROM {tabela} WHERE id = ?", (id_valido(id_),))
    if registro is None:
        raise ErroHttp(404, "Registro não encontrado.")
    return registro


# ---------- chamada a outro serviço (REST) ----------
_sessao = requests.Session()
_sessao.trust_env = False  # ignora proxies do sistema: as chamadas são locais


def chamar(servico, caminho, metodo="GET", dados=None):
    try:
        r = _sessao.request(
            metodo, f"http://{HOST}:{PORTAS[servico]}{caminho}", json=dados, timeout=4
        )  # timeout: serviço lento não deixa a requisição presa
    except requests.RequestException:
        raise ErroHttp(503, f"Serviço de {servico} indisponível.")
    if r.status_code >= 400:
        try:
            mensagem = r.json().get("erro", "Falha no serviço.")
        except ValueError:
            mensagem = "Falha no serviço."
        raise ErroHttp(r.status_code, mensagem)
    return r.json() if r.content else None


# ---------- aplicação Flask ----------
def criar_app(nome):
    app = Flask(nome)
    app.json.sort_keys = False
    app.json.ensure_ascii = False

    @app.get("/health")
    def saude():
        return jsonify(servico=nome, status="ok")

    @app.errorhandler(ErroHttp)
    def erro_http(e):
        return jsonify(erro=e.mensagem), e.status

    @app.errorhandler(sqlite3.IntegrityError)
    def erro_unico(e):
        if "UNIQUE" in str(e):
            return jsonify(erro="Já existe um cadastro com esse valor único."), 409
        return jsonify(erro="Dados inválidos."), 400

    @app.errorhandler(404)
    def nao_encontrada(e):
        return jsonify(erro="Rota não encontrada."), 404

    @app.errorhandler(405)
    def metodo_nao_permitido(e):
        return jsonify(erro="Método não permitido."), 405

    @app.errorhandler(Exception)
    def erro_interno(e):
        app.logger.exception(e)
        return jsonify(erro="Erro interno do serviço."), 500

    return app


def iniciar(app, porta):
    try:
        app.run(host=HOST, port=porta, threaded=True, use_reloader=False)
    except KeyboardInterrupt:
        pass
