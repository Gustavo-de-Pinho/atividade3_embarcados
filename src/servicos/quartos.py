"""Microservice: cadastro de quartos."""
from flask import jsonify, request

from src.comum import PORTAS, Banco, ErroHttp, buscar, corpo_json, criar_app, exigir, iniciar, texto

db = Banco("quartos", """
    CREATE TABLE IF NOT EXISTS quartos (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        numero       TEXT NOT NULL UNIQUE,
        descricao    TEXT,
        fechadura_id TEXT NOT NULL UNIQUE,
        ativo        INTEGER NOT NULL DEFAULT 1
    )
""")
app = criar_app("quartos")


def publico(q):
    return {**q, "ativo": q["ativo"] == 1}


def validar(d):
    exigir(d.get("descricao") is None or isinstance(d["descricao"], str), "descricao deve ser texto.")
    exigir(d.get("ativo") is None or isinstance(d["ativo"], bool), "ativo deve ser booleano.")
    return {
        "numero": texto(d.get("numero"), "numero", 40),
        "descricao": d.get("descricao"),
        "fechadura_id": texto(d.get("fechadura_id"), "fechadura_id", 80),
        "ativo": 0 if d.get("ativo") is False else 1,
    }


@app.get("/quartos")
def listar():
    return jsonify([publico(q) for q in db.todos("SELECT * FROM quartos ORDER BY id")])


# Rota usada pelo serviço de acessos. Não é exposta pelo gateway.
@app.get("/quartos/fechadura/<fechadura_id>")
def por_fechadura(fechadura_id):
    q = db.um("SELECT * FROM quartos WHERE fechadura_id = ?", (fechadura_id,))
    if q is None:
        raise ErroHttp(404, "Fechadura não cadastrada.")
    return jsonify(publico(q))


@app.get("/quartos/<id_>")
def consultar(id_):
    return jsonify(publico(buscar(db, "quartos", id_)))


@app.post("/quartos")
def cadastrar():
    d = validar(corpo_json())
    novo = db.executar(
        "INSERT INTO quartos (numero, descricao, fechadura_id, ativo) VALUES (?, ?, ?, ?)",
        (d["numero"], d["descricao"], d["fechadura_id"], d["ativo"]),
    )
    return jsonify(publico(buscar(db, "quartos", novo))), 201


# PUT aceita campos parciais: o que não vier mantém o valor atual.
@app.put("/quartos/<id_>")
def atualizar(id_):
    atual = buscar(db, "quartos", id_)
    d = validar({**publico(atual), **corpo_json()})
    db.executar(
        "UPDATE quartos SET numero = ?, descricao = ?, fechadura_id = ?, ativo = ? WHERE id = ?",
        (d["numero"], d["descricao"], d["fechadura_id"], d["ativo"], atual["id"]),
    )
    return jsonify(publico(buscar(db, "quartos", atual["id"])))


# Exclusão lógica: preserva senhas e histórico que referenciam o quarto.
@app.delete("/quartos/<id_>")
def desativar(id_):
    atual = buscar(db, "quartos", id_)
    db.executar("UPDATE quartos SET ativo = 0 WHERE id = ?", (atual["id"],))
    return "", 204


if __name__ == "__main__":
    iniciar(app, PORTAS["quartos"])
