# Precedência e associatividade dos operadores

Quando uma conta tem vários operadores, há duas regras que dizem por que ordem se faz:

- a **precedência** diz que operadores se aplicam primeiro (a potência antes da multiplicação, a
  multiplicação antes da soma);
- a **associatividade** diz como se agrupam vários operadores do mesmo nível seguidos: se se começa
  pela esquerda ou pela direita.

| Ordem | Operador | O que faz | Associatividade |
|---|---|---|---|
| 1.º (aplica-se primeiro) | `^` | potência | à direita |
| 2.º | `−` unário | simétrico: o menos à frente de um número | — |
| 3.º | `*` e `/` | multiplicação e divisão | à esquerda |
| 4.º (aplica-se por último) | `+` e `−` | soma e subtração | à esquerda |

## Exemplos, passo a passo

- **2^3^2 = 512.** A potência associa à direita, por isso começa-se por cima: 3^2 = 9 e depois
  2^9 = 512. Se se começasse pela esquerda, daria (2^3)^2 = 8^2 = 64.
- **−2^2 = −4.** A potência aplica-se antes do menos unário: primeiro 2^2 = 4 e depois o simétrico,
  −4. Para elevar −2 ao quadrado é preciso escrever (−2)^2, que dá 4.
- **100 − 20 − 5 = 75.** A subtração associa à esquerda: primeiro 100 − 20 = 80 e depois
  80 − 5 = 75. Agrupar pela direita daria 100 − (20 − 5) = 100 − 15 = 85.

Os parênteses passam à frente de todas estas regras: o que está dentro deles calcula-se primeiro.
