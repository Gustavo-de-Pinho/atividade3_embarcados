"""Microservice: cadastro de senhas e verificação de validade."""
import hashlib
import hmac
import os
import re
import secrets

from flask import jsonify, request

from src.comum import (PORTAS, Banco, ErroHttp, agora_iso, buscar, chamar, corpo_json, criar_app,
                       data_iso, exigir, id_valido, iniciar)

# O código nunca é gravado: guardamos apenas hash (PBKDF2-SHA256) e salt.
db = Banco("senhas", """
    CREATE TABLE IF NOT EXISTS senhas (
        id        INTEGER PRIMARY KEY AUTOINCREMENT,
        pessoa_id INTEGER NOT NULL,
        quarto_id INTEGER NOT NULL,
        hash      TEXT NOT NULL,
        salt      TEXT NOT NULL,
        inicio    TEXT NOT NULL,   -- ISO 8601 em UTC
        fim       TEXT NOT NULL,   -- ISO 8601 em UTC
        ativa     INTEGER NOT NULL DEFAULT 1,
        criada_em TEXT NOT NULL
    )
""")
app = criar_app("senhas")

ITERACOES = 100_000


def publica(s):
    """Campos que podem aparecer nas respostas (nunca hash, salt ou código)."""
    return {
        "id": s["id"], "pessoa_id": s["pessoa_id"], "quarto_id": s["quarto_id"],
        "inicio": s["inicio"], "fim": s["fim"], "ativa": s["ativa"] == 1, "criada_em": s["criada_em"],
    }


def validar_codigo(codigo):
    exigir(isinstance(codigo, str) and re.fullmatch(r"[0-9]{4,12}", codigo) is not None,
           "senha deve ser um texto de 4 a 12 dígitos.")


def calcular_hash(codigo, salt_hex):
    return hashlib.pbkdf2_hmac("sha256", codigo.encode(), bytes.fromhex(salt_hex), ITERACOES).hex()


def confere(codigo, registro):
    return hmac.compare_digest(calcular_hash(codigo, registro["salt"]), registro["hash"])


def repetida(quarto_id, codigo, inicio, fim):
    """Existe senha ativa, no mesmo quarto, com o mesmo código e período que se sobrepõe?"""
    outras = db.todos(
        "SELECT * FROM senhas WHERE quarto_id = ? AND ativa = 1 AND inicio < ? AND fim > ?",
        (quarto_id, fim, inicio),
    )
    return any(confere(codigo, s) for s in outras)


def existente(servico, recurso, id_, rotulo):
    """Consulta outro serviço e traduz o 404 numa mensagem clara."""
    try:
        return chamar(servico, f"/{recurso}/{id_}")
    except ErroHttp as e:
        if e.status == 404:
            raise ErroHttp(404, f"{rotulo} não encontrado(a).")
        raise


@app.get("/senhas")
def listar():
    filtros, valores = [], []
    for campo in ("quarto_id", "pessoa_id"):
        if request.args.get(campo) is not None:
            filtros.append(f"{campo} = ?")
            valores.append(id_valido(request.args[campo]))
    where = f"WHERE {' AND '.join(filtros)}" if filtros else ""
    linhas = db.todos(f"SELECT * FROM senhas {where} ORDER BY id", valores)
    return jsonify([publica(s) for s in linhas])


@app.get("/senhas/<id_>")
def consultar(id_):
    return jsonify(publica(buscar(db, "senhas", id_)))


@app.post("/senhas")
def cadastrar():
    corpo = corpo_json()
    quarto_id = id_valido(corpo.get("quarto_id"))
    pessoa_id = id_valido(corpo.get("pessoa_id"))
    inicio = data_iso(corpo.get("inicio"), "inicio")
    fim = data_iso(corpo.get("fim"), "fim")
    exigir(inicio < fim, "inicio deve ser anterior a fim.")
    informada = "senha" in corpo
    if informada:
        validar_codigo(corpo["senha"])

    quarto = existente("quartos", "quartos", quarto_id, "Quarto")
    pessoa = existente("pessoas", "pessoas", pessoa_id, "Pessoa")
    exigir(quarto["ativo"] and pessoa["ativo"], "Quarto e pessoa devem estar ativos.")

    if informada:
        codigo = corpo["senha"]
        if repetida(quarto_id, codigo, inicio, fim):
            raise ErroHttp(409, "Esta senha já está em uso neste quarto em período sobreposto.")
    else:
        codigo = f"{secrets.randbelow(1_000_000):06d}"
        while repetida(quarto_id, codigo, inicio, fim):
            codigo = f"{secrets.randbelow(1_000_000):06d}"

    salt = os.urandom(16).hex()
    novo = db.executar(
        "INSERT INTO senhas (pessoa_id, quarto_id, hash, salt, inicio, fim, criada_em) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (pessoa_id, quarto_id, calcular_hash(codigo, salt), salt, inicio, fim, agora_iso()),
    )
    criada = publica(buscar(db, "senhas", novo))
    # O código gerado só pode ser visto agora; depois dele só existe o hash.
    return jsonify(criada if informada else {**criada, "senha": codigo}), 201


# Revogar = desativar. A senha deixa de abrir, mas o registro continua no histórico.
@app.delete("/senhas/<id_>")
def revogar(id_):
    s = buscar(db, "senhas", id_)
    db.executar("UPDATE senhas SET ativa = 0 WHERE id = ?", (s["id"],))
    return "", 204


# Rota interna chamada pelo serviço de acessos. O gateway não a expõe.
@app.post("/interno/verificar")
def verificar():
    corpo = corpo_json()
    quarto_id = id_valido(corpo.get("quarto_id"))
    validar_codigo(corpo.get("senha"))
    agora = agora_iso()  # o horário vem do servidor, nunca do cliente

    registros = db.todos("SELECT * FROM senhas WHERE quarto_id = ? AND ativa = 1", (quarto_id,))
    iguais = [r for r in registros if confere(corpo["senha"], r)]

    if not iguais:
        return jsonify(autorizado=False, motivo="SENHA_INCORRETA")
    # Início inclusivo, fim exclusivo.
    vigente = next((s for s in iguais if s["inicio"] <= agora < s["fim"]), None)
    if vigente is None:
        return jsonify(autorizado=False, motivo="FORA_DO_PERIODO", senha_id=iguais[0]["id"])

    pessoa = None
    try:
        pessoa = chamar("pessoas", f"/pessoas/{vigente['pessoa_id']}")
    except ErroHttp as e:
        if e.status != 404:
            raise
    if pessoa is None or not pessoa["ativo"]:
        return jsonify(autorizado=False, motivo="PESSOA_INATIVA", senha_id=vigente["id"])
    return jsonify(autorizado=True, motivo="ACESSO_AUTORIZADO", senha_id=vigente["id"], pessoa_id=pessoa["id"])


if __name__ == "__main__":
    iniciar(app, PORTAS["senhas"])
