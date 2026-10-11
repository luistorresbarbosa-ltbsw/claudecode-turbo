"""JEV: escolhe o modelo e o esforço certos para cada tarefa, e mostra quanto poupaste."""
import os

# O litellm em modo DEV (o defeito) carrega o .env da pasta atual ao ser importado. O mod corre
# o JEV na pasta do projeto do utilizador, e esse .env não é nosso: poderia trazer uma
# ANTHROPIC_API_KEY que poria o `claude -p` a faturar a API em vez da subscrição.
os.environ.setdefault("LITELLM_MODE", "PRODUCTION")
