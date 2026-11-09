# Backend de controle de acesso a quartos (Python)

Backend em **Python (Flask, requests e SQLite)** para automatizar o acesso a quartos alugados com
fechaduras eletrônicas e senhas temporárias. São quatro microservices (quartos, pessoas, senhas e acessos)
com banco próprio, acessados por um único API gateway REST.

```
REST Client / app do administrador ─┐
                                    ├─► Gateway :3000 ─► quartos  :3001  dados/quartos.db
Fechadura (simulada) ───────────────┘                 ├─► pessoas  :3002  dados/pessoas.db
                                                      ├─► senhas   :3003  dados/senhas.db
                                                      └─► acessos  :3004  dados/acessos.db
```

## Como executar

Requer **Python 3.10 ou superior**. No Windows, use `python` (ou `py`) no PowerShell.

```powershell
pip install -r requirements.txt
copy .env.example .env      # opcional (Linux/macOS: cp). Aqui fica a chave do administrador
python scripts/iniciar.py   # sobe o gateway e os quatro serviços
```

A API fica em `http://127.0.0.1:3000`. Para encerrar, `Ctrl+C`. Os bancos são criados em `dados/`.
Se preferir isolar as bibliotecas do projeto, crie antes um ambiente virtual:
`python -m venv .venv` e depois `.venv\Scripts\Activate.ps1`.

## Como testar

- **REST Client (VS Code):** instale a extensão *REST Client* (Huachao Mao), abra `requisicoes.http` e clique em
  **Send Request** acima de cada bloco, de cima para baixo. O arquivo cria quarto, hóspede e senhas, testa
  acessos permitidos e negados, consulta o histórico e revoga a senha. Pode ser repetido: cada rodada cria
  dados novos.
- **Automatizado:** `python -m unittest discover -s testes -v` sobe tudo em portas livres e bancos
  temporários e cobre também a falha de um serviço.

## Autenticação

Cadastros e consultas exigem o cabeçalho `Authorization: Bearer <ADMIN_TOKEN>` (demonstração:
`admin-local-123`). A tentativa de abertura, `POST /acessos`, **não** exige a chave: é a rota usada pela fechadura.

## Rotas (URL base `http://127.0.0.1:3000`)

| Método | Rota | Função |
|---|---|---|
| GET / POST | `/quartos` | Listar / cadastrar quartos (`numero`, `descricao`, `fechadura_id`) |
| GET / PUT / DELETE | `/quartos/<id>` | Consultar / atualizar (campos parciais) / desativar |
| GET / POST | `/pessoas` | Listar (`?tipo=`) / cadastrar (`nome`, `documento`, `tipo`: `hospede` ou `funcionario`) |
| GET / PUT / DELETE | `/pessoas/<id>` | Consultar / atualizar / desativar |
| GET / POST | `/senhas` | Listar (`?quarto_id=`, `?pessoa_id=`) / cadastrar senha com validade |
| GET / DELETE | `/senhas/<id>` | Consultar / revogar |
| POST | `/acessos` | **Fechadura:** `{ "fechadura_id": "FECH-101", "senha": "012345" }` |
| GET | `/acessos` | Histórico; filtros `quarto_id`, `pessoa_id`, `fechadura_id`, `autorizado`, `de`, `ate` |
| GET | `/acessos/<id>` | Consultar um registro |
| GET | `/health` | Verificar se o gateway está no ar |

**Senhas:** `POST /senhas` recebe `quarto_id`, `pessoa_id`, `inicio`, `fim` e, opcionalmente, `senha`
(texto de 4 a 12 dígitos). Se `senha` for omitida, o sistema gera um código de 6 dígitos e o devolve **uma
única vez** na resposta. As datas precisam ter fuso, como `2026-11-09T14:00:00-03:00`. O código é guardado
apenas como hash (PBKDF2-SHA256 + salt). A senha vale de `inicio` (inclusive) até `fim` (exclusive). Para
mudar o período, revogue a senha e cadastre outra.

**Resposta da fechadura (`POST /acessos`):**

| Status | `motivo` | Significado |
|---|---|---|
| 200 | `ACESSO_AUTORIZADO` | A porta pode abrir |
| 403 | `SENHA_INCORRETA`, `FORA_DO_PERIODO`, `PESSOA_INATIVA`, `QUARTO_INATIVO` | Negado |
| 404 | `FECHADURA_DESCONHECIDA` | Fechadura não cadastrada |
| 400 | `FORMATO_INVALIDO` | Senha ausente, número JSON ou fora de 4–12 dígitos |
| 503 | `SERVICO_INDISPONIVEL` | Algum serviço não respondeu: por segurança, não abre |

`DELETE` em quartos e pessoas faz exclusão lógica (`ativo: false`) e em senhas revoga (`ativa: false`),
preservando o histórico.

## Estrutura

```
src/comum.py            utilitários: erros, validações, datas, banco SQLite, chamada entre serviços
src/gateway.py          API gateway (lista ROTAS)
src/servicos/*.py       quartos, pessoas, senhas e acessos
scripts/iniciar.py      sobe os cinco processos
testes/                 testes de integração
requisicoes.http        requisições para o REST Client
```

## Limitações conhecidas

- A fechadura é simulada por requisições HTTP; não há integração com hardware nem envio da senha por
  e-mail ou SMS (o administrador repassa o código ao hóspede).
- Não há limite de tentativas por fechadura. Um PIN de 4 a 12 dígitos é um segredo de baixa entropia; em
  produção seria preciso bloquear tentativas repetidas.
- Os serviços usam o servidor de desenvolvimento do Flask, escutam apenas em `127.0.0.1` e não usam HTTPS.

O roteiro de estudo e apresentação está em [APRESENTACAO.md](APRESENTACAO.md).
