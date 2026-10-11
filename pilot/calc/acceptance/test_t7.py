"""T7 · Inferência de tipos: calc.tipos.inferir(programa) -> str e calc.tipos.ErroTipo.

Afirma factos, não forma: o tipo devolvido lê-se de forma tolerante (parênteses a mais, espaços,
variáveis com outros nomes, como 'a, t0 ou a1, setas →, um ∀ à frente) e compara-se com o esperado
a menos de nomes das variáveis. Uma implementação que escreve `('t3 -> 't3)` passa onde se espera `a -> a`; uma que troca
a estrutura (`a -> b -> c` em vez de `(a -> b) -> c`) ou junta variáveis distintas não passa.

Os tipos esperados estão derivados à mão nos comentários. Os casos apanham os erros clássicos:
- sem polimorfismo no let (POLIMORFISMO);
- parâmetros de fn polimórficos (MONOMORFICO, `fn f => ... f(true) ... f(1)`);
- generalizar variáveis presas ao contexto, ou calcular as livres do contexto sem aplicar a
  substituição (CONTEXTO);
- sem verificação de ocorrência (INFINITOS);
- recursão polimórfica dentro do let rec, que as regras não permitem (ERROS, `f(true)` e `f(1)`);
- `==` só para números, contra as regras (`a -> a -> bool`).
Nenhum programa usa `%`, `//`, `2^-1` ou cadeias de `^` com tipos diferentes, para a T7 não depender
da T2 nem da T4.
"""

import re

import pytest

from calc.tipos import ErroTipo, inferir

# --- leitura tolerante de um tipo ----------------------------------------------------------------

_TOKEN = re.compile(r"\s*(->|→|\(|\)|'?[^\W\d]\w*'*)")
_QUANTIFICADOR = re.compile(r"^\s*(?:∀|forall\b)[\s\w']*\.")  # "∀a b. a -> b": tira-se
BASE = ("num", "bool")


def _ler(texto: str):
    """Árvore de um tipo: "num" | "bool" | ("var", nome) | ("->", argumento, resultado)."""
    tokens, pos, texto = [], 0, _QUANTIFICADOR.sub("", texto).strip()
    while pos < len(texto):
        token = _TOKEN.match(texto, pos)
        if token is None:
            raise ValueError(f"não percebo {texto[pos:]!r}")
        tokens.append("->" if token.group(1) == "→" else token.group(1))
        pos = token.end()
    arvore, resto = _tipo(tokens)
    if resto:
        raise ValueError(f"sobra {resto!r}")
    return arvore


def _tipo(tokens):
    argumento, resto = _atomo(tokens)
    if resto[:1] == ["->"]:
        resultado, resto = _tipo(resto[1:])  # -> associa à direita
        return ("->", argumento, resultado), resto
    return argumento, resto


def _atomo(tokens):
    if not tokens:
        raise ValueError("falta um tipo")
    primeiro, resto = tokens[0], tokens[1:]
    if primeiro == "(":
        dentro, resto = _tipo(resto)
        if resto[:1] != [")"]:
            raise ValueError("falta um ')'")
        return dentro, resto[1:]
    if primeiro in BASE:
        return primeiro, resto
    if primeiro in ("->", ")"):
        raise ValueError(f"não esperava {primeiro!r}")
    return ("var", primeiro), resto


def _escrever(arvore, nomes: dict) -> str:
    """Forma canónica, com as variáveis renomeadas a, b, c, ... pela ordem em que aparecem."""
    if arvore in BASE:
        return arvore
    if arvore[0] == "var":
        return nomes.setdefault(arvore[1], "abcdefghijklmnopqrstuvwxyz"[len(nomes)])
    _, argumento, resultado = arvore
    esquerda = _escrever(argumento, nomes)
    if argumento not in BASE and argumento[0] == "->":
        esquerda = f"({esquerda})"
    return f"{esquerda} -> {_escrever(resultado, nomes)}"


def canonico(texto) -> str:
    assert isinstance(texto, str), f"inferir devia devolver uma str: {texto!r}"
    try:
        return _escrever(_ler(texto), {})
    except ValueError as erro:
        pytest.fail(f"o tipo {texto!r} não se lê: {erro}", pytrace=False)


# --- tipos -------------------------------------------------------------------------------------------

SIMPLES = [
    ("42", "num"),
    ("true", "bool"),
    ("1 < 2", "bool"),
    ("fn x => x", "a -> a"),
    ("fn x => x + 1", "num -> num"),
    ("fn x => -x", "num -> num"),
    ("fn x => x < 1", "num -> bool"),
    ("fn x => fn y => x", "a -> b -> a"),
    ("fn f => fn x => f(x)", "(a -> b) -> a -> b"),
    # f : r1 -> r2, g : c -> r1: (r1 -> r2) -> (c -> r1) -> c -> r2
    ("fn f => fn g => fn x => f(g(x))", "(a -> b) -> (c -> a) -> c -> b"),
    # o S: x : z -> (yz -> r), y : z -> yz
    ("fn x => fn y => fn z => x(z)(y(z))", "(a -> b -> c) -> (a -> b) -> a -> c"),
    ("fn f => fn x => f(f(x))", "(a -> a) -> a -> a"),
    ("fn f => f(f(1))", "(num -> num) -> num"),
    ("fn x => fn y => x == y", "a -> a -> bool"),  # == aceita qualquer tipo, igual dos dois lados
    ("fn b => b == true", "bool -> bool"),
    ("fn c => if c then 1 else 0", "bool -> num"),
    ("fn b => if b then fn x => x + 1 else fn y => y * 2", "bool -> num -> num"),
    ("fn x => 2 ^ x ^ 2", "num -> num"),
    ("fn x => let x = x < 1 in if x then 1 else 2", "num -> num"),  # o x de dentro é bool
]

POLIMORFISMO = [
    ("let f = fn x => x in f", "a -> a"),
    ("let id = fn x => x in id(1)", "num"),
    ("let id = fn x => x in if id(true) then id(1) else 0", "num"),  # id usado com bool e num
    ("let id = fn x => x in id(id)", "a -> a"),
    ("let k = fn x => fn y => x in k(1)(true) + k(2)(fn z => z)", "num"),
    # par : x -> y -> (x -> y -> r) -> r, instanciado com x = num, y = bool
    ("let par = fn x => fn y => fn f => f(x)(y) in par(1)(true)", "(num -> bool -> a) -> a"),
    ("let compor = fn f => fn g => fn x => f(g(x)) in compor(fn x => x < 3)(fn y => y * 2)", "num -> bool"),
    (
        "let aplicar = fn f => fn x => f(x) in let a = aplicar(fn n => n + 1)(1) in"
        " aplicar(fn b => if b then 1 else 0)(true) + a",
        "num",
    ),
    ("let f = fn x => let g = fn y => y in g(x) in f", "a -> a"),
    ("let n = 5 in fn x => x + n", "num -> num"),
    ("let x = true in let x = 1 in x + 1", "num"),
]

RECURSIVOS = [
    ("let rec tamanho = fn n => if n == 0 then 0 else 1 + tamanho(n - 1) in tamanho", "num -> num"),
    (
        "let rec repetir = fn f => fn n => fn x =>"
        " if n == 0 then x else repetir(f)(n - 1)(f(x)) in repetir",
        "(a -> a) -> num -> a -> a",
    ),
    # depois do let rec, repetir é polimórfico: usa-se com bool e com num
    (
        "let rec repetir = fn f => fn n => fn x =>"
        " if n == 0 then x else repetir(f)(n - 1)(f(x)) in"
        " if repetir(fn b => if b then false else true)(3)(true)"
        " then repetir(fn x => x * 2)(10)(1) else 0",
        "num",
    ),
    ("let rec f = fn n => f(n) in f", "a -> b"),
    ("let rec f = fn n => f(n) in f(1)", "a"),  # nunca acaba se correr: inferir não o corre
]

CONTEXTO = [
    # f = fn y => x : y -> tx, e tx está preso ao contexto (é o tipo de x): só y se generaliza.
    # Generalizar também tx daria a -> bool.
    ("fn x => let f = fn y => x in if f(1) then f(true) else false", "bool -> bool"),
    # x(y) faz tx = y -> r; as livres do contexto, depois da substituição, incluem y e r, que não se
    # generalizam. Sem aplicar a substituição ao contexto daria (a -> b) -> c -> d.
    ("fn x => let g = fn y => x(y) in g", "(a -> b) -> a -> b"),
]


def _ids(casos):
    return [programa[:60] for programa, _ in casos]


@pytest.mark.parametrize(("programa", "tipo"), SIMPLES, ids=_ids(SIMPLES))
def test_tipos_simples(programa, tipo):
    assert canonico(inferir(programa)) == tipo


@pytest.mark.parametrize(("programa", "tipo"), POLIMORFISMO, ids=_ids(POLIMORFISMO))
def test_polimorfismo_no_let(programa, tipo):
    assert canonico(inferir(programa)) == tipo


@pytest.mark.parametrize(("programa", "tipo"), RECURSIVOS, ids=_ids(RECURSIVOS))
def test_let_rec(programa, tipo):
    assert canonico(inferir(programa)) == tipo


@pytest.mark.parametrize(("programa", "tipo"), CONTEXTO, ids=_ids(CONTEXTO))
def test_nao_generaliza_o_que_esta_preso_ao_contexto(programa, tipo):
    assert canonico(inferir(programa)) == tipo


# --- erros -------------------------------------------------------------------------------------------

NUM_E_BOOL = [
    "1 + true",
    "if 1 then 2 else 3",
    "if true then 1 else false",
    "(fn x => x + 1)(true)",
    "1 == true",
    "fn x => if x then x + 1 else 0",
    "fn f => if f(true) then f(1) else 0",  # f é um parâmetro: não é polimórfico
    "let rec f = fn x => if true then x else f(true) in f(1)",  # f : bool -> bool depois do let rec
    "let f = fn x => x + true in 1",  # o erro conta, mesmo numa definição que ninguém usa
]

INFINITOS = [
    "fn x => x(x)",
    "let rec f = fn x => f in f",  # tf = tx -> tf
    "let f = fn x => x(x) in 1",
    "fn f => (fn x => f(x(x)))(fn x => f(x(x)))",  # o combinador Y
]


@pytest.mark.parametrize("programa", NUM_E_BOOL)
def test_tipos_que_nao_casam_dizem_quais_sao(programa):
    with pytest.raises(ErroTipo) as erro:
        inferir(programa)

    mensagem = str(erro.value)
    assert "num" in mensagem and "bool" in mensagem, mensagem


@pytest.mark.parametrize("programa", INFINITOS)
def test_tipo_infinito(programa):
    with pytest.raises(ErroTipo) as erro:
        inferir(programa)

    assert "infinit" in str(erro.value).lower(), str(erro.value)


@pytest.mark.parametrize(
    "programa",
    ["1(2)", "(fn f => f(1)(2))(fn x => x)", "fn x => x(1) + x(true)"],
    ids=["chamar-um-numero", "aridade-errada", "parametro-usado-com-dois-tipos"],
)
def test_outros_programas_sem_tipo(programa):
    with pytest.raises(ErroTipo):
        inferir(programa)


def test_variavel_nao_definida_diz_o_nome():
    with pytest.raises(ErroTipo) as erro:
        inferir("let x = 1 in x + valor_que_nao_existe")

    assert "valor_que_nao_existe" in str(erro.value)
