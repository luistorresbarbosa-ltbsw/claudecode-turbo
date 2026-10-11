# Regras do projeto

Valem para todas as tarefas. As convenções do domínio estão no README.md.

## Código

- Nomes que dizem o que são (`linha`, `taxa`, `total_iva`), também em compreensões: nada de `l`,
  `t`, `f` ou `d`.
- Uma função, um propósito. Um cálculo com nome no domínio (o total de uma linha, o IVA de uma
  taxa) é uma função própria, com uma docstring curta.
- Não dupliques código. Antes de escrever uma função, procura se já existe, por exemplo para ler e
  validar uma fatura ou para arredondar ao cêntimo. O arredondamento vive num só sítio.
- Não deixes no repositório scripts soltos, código morto, planos nem notas de trabalho: só código,
  testes e os documentos pedidos.

## Dados que entram

- Valida o que vem de fora (JSON, linha de comando) logo à entrada: campos em falta ou a mais,
  tipos, região e taxa conhecidas.
- Os valores decimais em JSON vêm em texto e passam a `Decimal` sem passar por `float`: recusa
  números JSON, NaN, infinito e expoentes.
- Cada erro diz o campo e o motivo, por exemplo `linhas[0].preco_unitario: esperava um decimal em
  texto`. Nem um `KeyError` nem um traceback chegam a quem usa a linha de comando.
- Os dígitos de um NIF são só os ASCII de 0 a 9 (`str.isdigit()` aceita outros).
- Todo o código que lê faturas usa o mesmo leitor validado.

## Testes

- Cada alteração traz testes dos casos-limite que importam, não só do caso feliz: valores
  exatamente a meio cêntimo, região ou taxa desconhecida, dados inválidos, um ficheiro que não
  existe.
- Os testes verificam o valor esperado, não só o tipo do resultado, e não guardam comentários de
  tentativa e erro.
- Antes de acabares, corre `uv run pytest` e deixa tudo a verde.

## Textos

- Quando a tarefa pede um texto, a tua resposta final é o texto e só o texto: sem introdução, sem
  notas e sem comentários sobre como o fizeste. A resposta é guardada tal qual.
- Escreve para o leitor final, em português de Portugal, com o mesmo registo do princípio ao fim:
  nunca "tu" num documento, e tratamento formal num email a um cliente.
- Confere as taxas com o projeto (`fatura/iva.py` e os testes em `tests/`) e escreve só valores
  confirmados, sem pôr dúvidas no texto.
- Nada sobre o processo ou a sessão (pesquisas bloqueadas, ferramentas, conectores, "escrevi de
  memória") e nada na primeira pessoa do autor.
- As contas batem certo: as parcelas somam o total.
