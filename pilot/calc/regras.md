# Regras do projeto

Valem para todas as tarefas. A gramática, os valores e as regras da linguagem estão no README.md.

## Código

- Nomes que dizem o que são (`expressao`, `ambiente`, `token`), também em compreensões: nada de `e`,
  `t` ou `x` fora de um lambda de uma linha.
- Uma função, um propósito. Cada regra da gramática é uma função do analisador, e cada tipo de nó tem
  o seu caso no avaliador.
- Não dupliques código. Antes de escrever uma função, procura se já existe, por exemplo para ler um
  token, avaliar uma operação aritmética ou criar um erro com a posição.
- Os números são sempre `Fraction`: nada passa por `float`.
- Não deixes no repositório scripts soltos, código morto, planos nem notas de trabalho: só código,
  testes e os documentos pedidos.

## Erros

- Cada erro do programa é do tipo certo (`ErroSintaxe`, `ErroExecucao` ou, nos tipos, `ErroTipo`) e
  diz o que falhou e onde.
- Nenhum erro interno do Python (`RecursionError`, `KeyError`, `ZeroDivisionError`, `TypeError`)
  chega a quem usa a linguagem.

## Testes

- Cada alteração traz testes dos casos-limite que importam, não só do caso feliz: associatividade,
  negativos e frações, divisão por zero, âmbito das funções, recursão profunda, e erros com a posição.
- Os testes verificam o valor esperado e a mensagem, não só que "não rebenta".
- Antes de acabares, corre `uv run pytest` e deixa tudo a verde.

## Textos

- Quando a tarefa pede um texto, a tua resposta final é o texto e só o texto: sem introdução, sem
  notas e sem comentários sobre como o fizeste. A resposta é guardada tal qual.
- Escreve para o leitor pedido, em português de Portugal, com o mesmo registo do princípio ao fim.
- Os exemplos e os resultados batem certo com a linguagem: confere-os no README.md e no código.
- Nada sobre o processo ou a sessão, e nada na primeira pessoa do autor.
