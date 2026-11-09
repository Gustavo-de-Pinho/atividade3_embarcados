"""API Gateway: única entrada REST do sistema. Não tem regra de negócio:
só autentica o administrador e encaminha cada rota ao serviço dono do recurso."""
import hmac
import os

import requests
from flask import Response, jsonify, request

from src.comum import HOST, PORTAS, criar_app, iniciar

app = criar_app("gateway")
TOKEN = os.environ.get("ADMIN_TOKEN", "admin-local-123")
if "ADMIN_TOKEN" not in os.environ:
    print("Aviso: ADMIN_TOKEN não definido; usando a chave de demonstração.")

_sessao = requests.Session()
_sessao.trust_env = False


def autenticado():
    enviado = request.headers.get("Authorization", "")
    return hmac.compare_digest(enviado, f"Bearer {TOKEN}")


def encaminhar(protegida):
    """Cria a função que atende uma rota: confere a chave (se exigida) e repassa ao serviço."""

    def atender(**_):
        if protegida and not autenticado():
            return jsonify(erro="Chave administrativa inválida ou ausente."), 401
        servico = request.path.split("/")[1]  # /quartos/1 -> "quartos"
        url = f"http://{HOST}:{PORTAS[servico]}{request.path}"
        try:
            r = _sessao.request(
                request.method, url, params=request.args, timeout=15,
                data=None if request.method in ("GET", "DELETE") else request.get_data(),
                headers={"Content-Type": request.content_type} if request.content_type else {},
            )
        except requests.RequestException:
            return jsonify(erro=f"Serviço de {servico} indisponível."), 503
        return Response(r.content, status=r.status_code, content_type=r.headers.get("Content-Type"))

    return atender


# Lista de rotas públicas do sistema. O que não está aqui não é exposto
# (por exemplo /senhas/interno/verificar e /quartos/fechadura/<id>).
# (método, caminho, exige chave de administrador?)
ROTAS = [
    ("GET", "/quartos", True), ("POST", "/quartos", True),
    ("GET", "/quartos/<id_>", True), ("PUT", "/quartos/<id_>", True), ("DELETE", "/quartos/<id_>", True),

    ("GET", "/pessoas", True), ("POST", "/pessoas", True),
    ("GET", "/pessoas/<id_>", True), ("PUT", "/pessoas/<id_>", True), ("DELETE", "/pessoas/<id_>", True),

    ("GET", "/senhas", True), ("POST", "/senhas", True),
    ("GET", "/senhas/<id_>", True), ("DELETE", "/senhas/<id_>", True),

    ("POST", "/acessos", False),  # a fechadura não tem a chave de administrador
    ("GET", "/acessos", True), ("GET", "/acessos/<id_>", True),
]

for metodo, caminho, protegida in ROTAS:
    app.add_url_rule(caminho, endpoint=f"{metodo} {caminho}", view_func=encaminhar(protegida), methods=[metodo])

if __name__ == "__main__":
    iniciar(app, PORTAS["gateway"])
