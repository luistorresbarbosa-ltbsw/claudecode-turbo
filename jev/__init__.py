"""JEV: escolhe o modelo e o esforço certos para cada tarefa, e mostra quanto poupaste."""
import os

# O litellm em modo DEV (o defeito) carrega o .env da pasta atual ao ser importado. O mod corre
# o JEV na pasta do projeto do utilizador, e esse .env não é nosso: poderia trazer uma
# ANTHROPIC_API_KEY que poria o `claude -p` a faturar a API em vez da subscrição.
os.environ.setdefault("LITELLM_MODE", "PRODUCTION")

# E ao ser importado vai buscar a tabela de preços ao GitHub: uma chamada de rede em cada `jev record`,
# lenta e capaz de prender. Usamos a tabela que vem com o pacote (fixa, reprodutível); as correções
# validadas contra o Claude Code estão em jev/pricing.py.
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")
