# calc

Uma pequena linguagem de expressões, em Python: um analisador léxico (`calc/lexico.py`), um
analisador sintático que constrói a árvore do programa (`calc/analisador.py`, `calc/arvore.py`) e
um avaliador que percorre essa árvore (`calc/avaliador.py`).

```python
from calc import avaliar

avaliar("let dobro = fn x => x * 2 in dobro(21)")  # Fraction(42, 1)
```

## Valores

- **Números:** todos são `fractions.Fraction`, para a aritmética ser exata. `1 / 3` é um terço e
  não 0,333…; `0.1 + 0.2 == 0.3` dá `true`. Escrevem-se com algarismos e, se for preciso, um ponto
  decimal: `42`, `2.5`. O expoente de `^` tem de ser inteiro.
- **Booleanos:** `true` e `false`, que são `bool` em Python. Resultam das comparações.
- **Funções:** `fn x => x + 1`. Têm um só parâmetro; chamam-se com `f(3)`. Uma função de dois
  argumentos é uma função que devolve outra: `let somar = fn a => fn b => a + b in somar(2)(3)`.

## Gramática

Da precedência mais fraca para a mais forte:

```
expressao  := "let" NOME "=" expressao "in" expressao
            | "let" "rec" NOME "=" funcao "in" expressao
            | "if" expressao "then" expressao "else" expressao
            | funcao
            | comparacao
funcao     := "fn" NOME "=>" expressao
comparacao := soma [("==" | "!=" | "<" | "<=" | ">" | ">=") soma]
soma       := produto (("+" | "-") produto)*
produto    := unario (("*" | "/") unario)*
unario     := "-" unario | potencia
potencia   := chamada ["^" unario]
chamada    := atomo ("(" expressao ")")*
atomo      := NUMERO | "true" | "false" | NOME | "(" expressao ")"
```

- `+ - * /` associam à esquerda: `10 - 4 - 3` é `(10 - 4) - 3`.
- `^` associa à direita e vem antes do menos unário: `-2 ^ 2` é `-(2 ^ 2)`.
- As comparações não se encadeiam: `1 < 2 < 3` é um erro de sintaxe.
- `#` começa um comentário, até ao fim da linha. Espaços e mudanças de linha não contam.

## Regras

- `let x = e1 in e2` dá o nome `x` ao valor de `e1` dentro de `e2`, e só aí. Em `e1`, `x` ainda é
  o de fora. Para uma função se chamar a si própria usa-se `let rec`.
- **Âmbito léxico:** uma função vê as variáveis do sítio onde foi definida, e não as de quem a
  chama.
- `if` só aceita booleanos na condição; `+ - * / ^ < <= > >=` só aceitam números; `==` e `!=`
  comparam números com números e booleanos com booleanos.

## Erros

Todos descendem de `calc.erros.ErroCalc`:

- `ErroSintaxe`: o programa está mal escrito;
- `ErroExecucao`: o programa falhou a correr (divisão por zero, variável não definida, tipos
  errados, chamar o que não é função...).

## Testes

```
uv run pytest
```
