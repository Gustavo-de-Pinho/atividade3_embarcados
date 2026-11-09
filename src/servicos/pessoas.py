"""Microservice: cadastro de pessoas (hóspedes e funcionários)."""
from flask import jsonify, request

from src.comum import PORTAS, Banco, buscar, corpo_json, criar_app, exigir, iniciar, texto

TIPOS = ("hospede", "funcionario")

db = Banco("pessoas", """
    CREATE TABLE IF NOT EXISTS pessoas (
        id        INTEGER PRIMARY KEY AUTOINCREMENT,
        nome      TEXT NOT NULL,
        documento TEXT NOT NULL UNIQUE,
        tipo      TEXT NOT NULL CHECK (tipo IN ('hospede', 'funcionario')),
        email     TEXT,
        telefone  TEXT,
        ativo     INTEGER NOT NULL DEFAULT 1
    )
""")
app = criar_app("pessoas")


def publico(p):
    return {**p, "ativo": p["ativo"] == 1}


def validar(d):
    exigir(d.get("tipo") in TIPOS, f"tipo deve ser um de: {', '.join(TIPOS)}.")
    exigir(d.get("email") is None or isinstance(d["email"], str), "email deve ser texto.")
    exigir(d.get("telefone") is None or isinstance(d["telefone"], str), "telefone deve ser texto.")
    exigir(d.get("ativo") is None or isinstance(d["ativo"], bool), "ativo deve ser booleano.")
    return {
        "nome": texto(d.get("nome"), "nome"),
        "documento": texto(d.get("documento"), "documento", 40),
        "tipo": d["tipo"],
        "email": d.get("email"),
        "telefone": d.get("telefone"),
        "ativo": 0 if d.get("ativo") is False else 1,
    }


@app.get("/pessoas")
def listar():
    tipo = request.args.get("tipo")
    exigir(tipo is None or tipo in TIPOS, f"tipo deve ser um de: {', '.join(TIPOS)}.")
    if tipo:
        linhas = db.todos("SELECT * FROM pessoas WHERE tipo = ? ORDER BY id", (tipo,))
    else:
        linhas = db.todos("SELECT * FROM pessoas ORDER BY id")
    return jsonify([publico(p) for p in linhas])


@app.get("/pessoas/<id_>")
def consultar(id_):
    return jsonify(publico(buscar(db, "pessoas", id_)))


@app.post("/pessoas")
def cadastrar():
    d = validar({"tipo": "hospede", **corpo_json()})
    novo = db.executar(
        "INSERT INTO pessoas (nome, documento, tipo, email, telefone, ativo) VALUES (?, ?, ?, ?, ?, ?)",
        (d["nome"], d["documento"], d["tipo"], d["email"], d["telefone"], d["ativo"]),
    )
    return jsonify(publico(buscar(db, "pessoas", novo))), 201


@app.put("/pessoas/<id_>")
def atualizar(id_):
    atual = buscar(db, "pessoas", id_)
    d = validar({**publico(atual), **corpo_json()})
    db.executar(
        "UPDATE pessoas SET nome = ?, documento = ?, tipo = ?, email = ?, telefone = ?, ativo = ? WHERE id = ?",
        (d["nome"], d["documento"], d["tipo"], d["email"], d["telefone"], d["ativo"], atual["id"]),
    )
    return jsonify(publico(buscar(db, "pessoas", atual["id"])))


# Exclusão lógica: a pessoa deixa de abrir quartos, mas o histórico permanece.
@app.delete("/pessoas/<id_>")
def desativar(id_):
    atual = buscar(db, "pessoas", id_)
    db.executar("UPDATE pessoas SET ativo = 0 WHERE id = ?", (atual["id"],))
    return "", 204


if __name__ == "__main__":
    iniciar(app, PORTAS["pessoas"])
