# fatura

Mini-biblioteca de faturas portuguesas: continente, Madeira e Açores.

## Convenções

- **`Decimal` em todo o lado.** Quantidades, preços, percentagens, taxas e valores em euros são
  `Decimal`, nunca `float`.
- **Arredondamento `ROUND_HALF_UP` a 2 casas decimais** (ao cêntimo): `Decimal("2.675")` dá `2.68`.
- `preco_unitario` é sem IVA.
- `desconto_pct` é uma percentagem: `Decimal("12.5")` quer dizer 12,5 %.
- Regiões: `PT` (continente), `PT-MA` (Madeira) e `PT-AC` (Açores).
- Taxas de IVA: `NOR` (normal), `INT` (intermédia) e `RED` (reduzida). Os valores estão em
  `fatura/iva.py`, em `TAXAS[regiao][taxa]`.

## Testes

```
uv run pytest
```
