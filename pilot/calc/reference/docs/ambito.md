# Âmbito léxico e âmbito dinâmico

Quando uma função usa uma variável que não é dela (nem um parâmetro, nem uma variável local), é
preciso saber de onde vem o valor. A regra que decide isso chama-se **âmbito**, e há duas clássicas.

**O exemplo.** A função `custo(n)` devolve `n × taxa` e foi definida num sítio onde existe uma
variável `taxa` que vale 3. Outra função, `faturar`, tem uma variável local também chamada `taxa`,
que vale 7, e chama `custo(5)`. Dentro de `custo`, qual é a `taxa`?

- **Âmbito léxico (ou estático):** a função usa as variáveis do sítio onde foi **escrita**. Quando
  `custo` foi definida, a `taxa` visível valia 3, por isso `custo(5)` dá 5 × 3 = **15**. A `taxa` local
  de `faturar` não conta: é uma variável diferente, que só existe dentro de `faturar`.
- **Âmbito dinâmico:** a função usa as variáveis de quem a **chama**, no momento da chamada. Quem
  chama `custo` é `faturar`, onde `taxa` vale 7, por isso `custo(5)` dá 5 × 7 = **35**.

| Regra | Que `taxa` usa | `custo(5)` |
|---|---|---|
| Âmbito léxico | a do sítio onde `custo` foi definida (3) | 15 |
| Âmbito dinâmico | a de quem chama, `faturar` (7) | 35 |

Com âmbito léxico basta ler o código à volta da função para saber o que ela faz; com âmbito dinâmico,
o resultado muda conforme quem a chama. Por isso quase todas as linguagens atuais, como Python,
JavaScript ou Java, usam âmbito léxico.
