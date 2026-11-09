"""Microservice: controle de acessos (decide e registra cada tentativa)."""
import re
from urllib.parse import quote

from flask import jsonify, request

from src.comum import (PORTAS, Banco, ErroHttp, agora_iso, buscar, chamar, corpo_json, criar_app,
                       data_iso, exigir, id_valido, iniciar, texto)

db = Banco("acessos", """
    CREATE TABLE IF NOT EXISTS acessos (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        fechadura_id TEXT NOT NULL,
        quarto_id    INTEGER,
        pessoa_id    INTEGER,
        senha_id     INTEGER,
        autorizado   INTEGER NOT NULL,
        motivo       TEXT NOT NULL,
        datahora     TEXT NOT NULL
    )
""")
app = criar_app("acessos")


def publico(a):
    return {**a, "autorizado": a["autorizado"] == 1}


# Tentativa enviada pela fechadura: { "fechadura_id": ..., "senha": ... }
@app.post("/acessos")
def tentar():
    corpo = corpo_json()
    fechadura_id = texto(corpo.get("fechadura_id"), "fechadura_id", 80)
    senha = corpo.get("senha")
    datahora = agora_iso()
    quarto = None

    # Número JSON perderia o zero à esquerda, por isso só texto é aceito.
    if not (isinstance(senha, str) and re.fullmatch(r"[0-9]{4,12}", senha)):
        decisao, status = {"autorizado": False, "motivo": "FORMATO_INVALIDO"}, 400
    else:
        try:
            # 1) Qual quarto tem esta fechadura?
            quarto = chamar("quartos", f"/quartos/fechadura/{quote(fechadura_id, safe='')}")
            if not quarto["ativo"]:
                decisao = {"autorizado": False, "motivo": "QUARTO_INATIVO"}
            else:
                # 2) A senha vale agora para este quarto?
                decisao = chamar("senhas", "/interno/verificar", "POST",
                                 {"quarto_id": quarto["id"], "senha": senha})
            status = 200 if decisao["autorizado"] else 403
        except ErroHttp as e:
            if e.status == 404:
                decisao, status = {"autorizado": False, "motivo": "FECHADURA_DESCONHECIDA"}, 404
            else:
                decisao, status = {"autorizado": False, "motivo": "SERVICO_INDISPONIVEL"}, 503  # na dúvida, não abre

    # 3) Grava a tentativa. Só depois responde: se a gravação falhar, nada é autorizado.
    novo = db.executar(
        """INSERT INTO acessos (fechadura_id, quarto_id, pessoa_id, senha_id, autorizado, motivo, datahora)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (fechadura_id, quarto["id"] if quarto else None, decisao.get("pessoa_id"), decisao.get("senha_id"),
         1 if decisao["autorizado"] else 0, decisao["motivo"], datahora),
    )
    return jsonify(id=novo, autorizado=decisao["autorizado"], motivo=decisao["motivo"], datahora=datahora), status


@app.get("/acessos")
def historico():
    a = request.args
    filtros, valores = [], []
    if a.get("quarto_id") is not None:
        filtros.append("quarto_id = ?")
        valores.append(id_valido(a["quarto_id"]))
    if a.get("pessoa_id") is not None:
        filtros.append("pessoa_id = ?")
        valores.append(id_valido(a["pessoa_id"]))
    if a.get("fechadura_id") is not None:
        filtros.append("fechadura_id = ?")
        valores.append(a["fechadura_id"])
    if a.get("autorizado") is not None:
        exigir(a["autorizado"] in ("true", "false"), "autorizado deve ser true ou false.")
        filtros.append("autorizado = ?")
        valores.append(1 if a["autorizado"] == "true" else 0)
    for campo, operador in (("de", ">="), ("ate", "<=")):
        if a.get(campo) is not None:
            filtros.append(f"datahora {operador} ?")
            valores.append(data_iso(a[campo], campo))
    where = f"WHERE {' AND '.join(filtros)}" if filtros else ""
    linhas = db.todos(f"SELECT * FROM acessos {where} ORDER BY id DESC LIMIT 1000", valores)
    return jsonify([publico(l) for l in linhas])


@app.get("/acessos/<id_>")
def consultar(id_):
    return jsonify(publico(buscar(db, "acessos", id_)))


if __name__ == "__main__":
    iniciar(app, PORTAS["acessos"])
