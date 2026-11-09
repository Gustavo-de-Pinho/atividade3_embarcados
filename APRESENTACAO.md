# Roteiro para estudar e apresentar

## Demonstração (sugestão de 5 a 8 minutos)

1. `pip install -r requirements.txt` e `python scripts/iniciar.py`. Mostre os cinco processos no terminal
   (portas 3000 a 3004) e, em `dados/`, os quatro arquivos `.db`: um por serviço.
2. Abra `requisicoes.http` e envie as requisições 01 a 05: gateway no ar, quarto, hóspede, senha válida e
   tentativa correta (`autorizado: true`).
3. Envie 06 a 09: senha errada, senha vencida e o histórico, mostrando registros com `autorizado: false`.
4. Envie 04b: o sistema gera um código e o mostra uma única vez. Depois envie 10 e mostre que o código não aparece.
5. Envie 11 e 12: revogue a senha e mostre que a mesma senha, que antes abria, agora é negada.
6. Envie 15 e 16: sem a chave, o gateway responde 401; a rota interna de verificação responde 404.
7. Em outro terminal, `python -m unittest discover -s testes -v`, com destaque para os testes de falha de serviço.

## Caminho de uma tentativa

1. A fechadura envia `POST /acessos` com `fechadura_id` e `senha` ao **gateway**.
2. O gateway encontra a rota na lista `ROTAS`, vê que ela não exige chave e encaminha ao serviço de **acessos**
   com `requests`.
3. **Acessos** valida o formato da senha e pergunta ao serviço de **quartos** qual quarto usa aquela
   fechadura. Se o quarto estiver inativo, nega.
4. **Acessos** chama a rota interna `/interno/verificar` do serviço de **senhas**, que:
   - calcula o hash da senha recebida com o salt de cada senha ativa do quarto e compara;
   - confere se `inicio <= agora < fim` (o horário é o do servidor);
   - consulta o serviço de **pessoas** para ver se a pessoa ainda está ativa.
5. **Acessos** grava a decisão no próprio SQLite e só então responde. Se a gravação falhar, nada é autorizado.
6. A fechadura simulada lê `autorizado` e decide abrir ou permanecer fechada.

## Ordem sugerida para ler o código

1. **`src/servicos/quartos.py`**: o cadastro mais simples. `corpo_json()` devolve o JSON enviado; `validar`
   devolve um dicionário com os campos já conferidos; `db.executar(...)` grava; `jsonify` responde.
2. **`src/servicos/pessoas.py`**: mesmo padrão, com `tipo` (`hospede` ou `funcionario`).
3. **`src/gateway.py`**: comece pela lista `ROTAS`. Cada linha diz método, caminho e se exige a chave.
   `encaminhar` cria a função de cada rota: confere o token, escolhe o serviço pelo primeiro trecho da URL e
   repassa a requisição.
4. **`src/servicos/senhas.py`**: `cadastrar` valida datas, confere pessoa e quarto nos outros serviços e grava
   só o hash. `verificar` percorre as senhas do quarto, compara hashes e confere a validade. `publica` lista
   os campos que podem sair nas respostas.
5. **`src/servicos/acessos.py`**: siga os comentários numerados: consultar quarto, verificar senha, gravar e
   responder.
6. **`src/comum.py`**: utilitários repetidos: erros, validações, datas, a classe `Banco`, `chamar` (REST entre
   serviços) e `criar_app`.
7. **`scripts/iniciar.py`**: a lista `MODULOS` tem exatamente os cinco programas que ele inicia.

## Funções e conceitos que aparecem várias vezes

- `@app.get`, `@app.post`, `@app.put`, `@app.delete`: definem o que acontece em cada método e rota HTTP.
- `<id_>` na rota: valor do caminho (o `1` de `/quartos/1`) que chega como parâmetro da função.
- `request.args`: filtros depois do `?`; `corpo_json()`: objeto JSON enviado, já verificado.
- `jsonify(...)`, e `return ..., 201`: devolvem JSON e escolhem o status HTTP.
- `db.todos(sql, params)`: lê uma lista; `db.um(...)`: lê um registro ou `None`; `db.executar(...)`: escreve e devolve o id criado.
- `chamar(servico, caminho, ...)`: faz a requisição REST a outro serviço (com timeout de 4 s) e devolve o JSON.
- `buscar(db, tabela, id)`: lê um registro do banco do próprio serviço ou lança 404.
- `exigir(condicao, mensagem)`: se a condição for falsa, interrompe a requisição com 400.
- `ErroHttp(status, mensagem)`: exceção que o Flask converte em resposta JSON com o status indicado.

## Requisitos do enunciado e onde estão

| Requisito | Implementação |
|---|---|
| Cadastro de quartos com a identificação das fechaduras | `quartos.py`, campo `fechadura_id` (único) |
| Cadastro de hóspedes e funcionários (limpeza, manutenção) | `pessoas.py`, campo `tipo` |
| Senhas com início e fim de validade, ligadas a pessoa e quarto | `senhas.py`: `inicio`, `fim`, `pessoa_id`, `quarto_id` |
| Verificar a senha, autorizar ou negar e registrar toda tentativa | `acessos.py` + `/interno/verificar` em `senhas.py` |
| Administrador cadastra quartos, pessoas e senhas | Rotas protegidas por `ADMIN_TOKEN` no gateway |
| Hóspedes e funcionários abrem a porta com a senha | `POST /acessos`, usada pela fechadura (sem chave) |
| Serviços acessados por API gateway com interface REST | `gateway.py`, lista `ROTAS` |
| Cada serviço com seu próprio banco | Quatro arquivos SQLite, abertos com `Banco` |
| Serviço lê dado de outro por requisição | `chamar`, com `requests` |
| Testar sem frontend | `requisicoes.http` (REST Client) e testes automatizados |

## Perguntas para entender o código

**Por que são microservices?** Cada um roda em processo próprio, com porta e banco próprios, e só se
comunica por requisições REST. Compartilhar o arquivo `comum.py` (funções utilitárias) não compartilha dados.

**Para que serve o gateway?** É a entrada única: autentica as operações do administrador e encaminha cada
recurso ao serviço correto. Não tem regra de negócio, como validade de senha. Também limita o que fica
público: rotas internas (`/senhas/interno/verificar`, `/quartos/fechadura/<id>`) não estão em `ROTAS` e por
isso respondem 404 por ele.

**Por que o serviço de senhas não lê o banco de pessoas diretamente?** Isso quebraria a separação dos dados.
O serviço de pessoas é o dono do cadastro e responde por REST.

**Por que não há chave estrangeira para `pessoa_id` e `quarto_id`?** Os registros estão em outros bancos. A
referência é validada por requisição na hora de cadastrar a senha, e não por uma foreign key.

**Como a validade é comparada?** As datas recebidas precisam ter fuso e são convertidas para ISO em UTC; nesse
formato, comparar as strings equivale a comparar as datas. A senha vale quando `inicio <= agora < fim`, com
`agora` medido no servidor, para que o cliente não escolha o horário da tentativa.

**Por que a senha é enviada como texto?** Um número JSON eliminaria o zero à esquerda (`012345` viraria
`12345`). Por isso números são rejeitados com 400.

**Por que hash com salt?** O banco não guarda o código original. `hashlib.pbkdf2_hmac` deriva um hash com um
salt aleatório (e muitas iterações, para tornar cada tentativa lenta) e `hmac.compare_digest` compara sem
revelar, pelo tempo de resposta, onde as strings diferem. Mesmo assim, um PIN tem poucos dígitos e é fácil
de adivinhar por tentativa e erro; o hash protege o banco, não substitui um limite de tentativas.

**Como o sistema gera uma senha?** Se `senha` não vier no cadastro, `secrets.randbelow` sorteia 6 dígitos que
não conflitem no quarto. O código aparece uma única vez na resposta, porque depois só existe o hash.

**Duas pessoas podem ter a mesma senha no mesmo quarto?** Só se os períodos não se sobrepuserem. Se
coincidissem, a fechadura não saberia quem entrou.

**O que são parâmetros `?` no SQL?** O SQL tem marcadores `?` e os valores vão separados, na tupla de
parâmetros. A entrada do usuário nunca é concatenada ao SQL (isso evita SQL injection). Os nomes de tabela em
`buscar` são constantes do código.

**O que acontece se um serviço cair?** `chamar` tem timeout. Se senhas ou quartos não respondem, acessos
registra `SERVICO_INDISPONIVEL`, responde 503 e a porta não abre. Se o próprio serviço de acessos cair, o
gateway responde 503 e nada é registrado, porque quem registra é ele.

**Por que exclusão lógica?** `DELETE` marca quarto e pessoa como inativos e a senha como revogada. Assim o
histórico continua apontando para registros existentes e, mesmo que a senha continue válida pela data,
ela deixa de abrir se a pessoa ou o quarto estiver inativo.

**Por que `POST /acessos` não pede a chave de administrador?** A fechadura não é o administrador: ela só
envia a tentativa e recebe a decisão. Em uma instalação real, a fechadura teria uma credencial própria.

**Por que a fechadura recebe 403 e não 200 quando a senha está errada?** É uma escolha de projeto: o status
HTTP já indica a decisão, e o corpo (`autorizado`, `motivo`) também. Outra opção seria responder sempre 200
e olhar apenas o campo `autorizado`.

**Por que cada operação do `Banco` abre a sua conexão?** O servidor atende várias requisições ao mesmo tempo
(threads), e uma conexão SQLite não deve ser compartilhada entre threads. Abrir e fechar a cada operação é
simples e seguro para o tamanho deste projeto.

**Como o código chega ao hóspede?** O administrador define ou gera o código e o repassa. O projeto
implementa cadastro e validação; não envia mensagens.

**Quais são os limites do projeto?** Não há limite de tentativas por fechadura, nem HTTPS, nem credencial
própria para cada fechadura, a fechadura é só simulada e o servidor é o de desenvolvimento do Flask. Vale
citá-los na apresentação.

## Antes da apresentação

Leia cada serviço, altere um cadastro pelo REST Client e acompanhe o fluxo acima no código. Faça uma pequena
modificação por conta própria (por exemplo, um novo filtro em `GET /acessos`) e explique o efeito. Siga as
regras da disciplina sobre autoria e uso de ferramentas.
