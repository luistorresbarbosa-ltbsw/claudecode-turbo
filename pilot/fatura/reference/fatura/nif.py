"""Validação do NIF (número de identificação fiscal) português."""

import re

# Prefixos atribuídos pela AT: 1, 2 e 3 pessoas singulares; 45 singulares não residentes;
# 5 pessoas coletivas; 6 administração pública; 70, 74 e 75 heranças indivisas; 71 coletivas
# não residentes; 72 fundos de investimento; 77 atribuição oficiosa; 78 não residentes (reembolso
# de IVA); 79 regime excecional; 90 e 91 condomínios e sociedades irregulares; 98 não residentes
# sem estabelecimento estável; 99 sociedades civis sem personalidade jurídica.
PREFIXOS = (
    "1", "2", "3", "45", "5", "6", "70", "71", "72", "74", "75", "77", "78", "79", "90", "91", "98", "99",
)  # fmt: skip

_NOVE_DIGITOS = re.compile(r"[0-9]{9}")


def valido(nif: str) -> bool:
    """True se `nif` é um NIF português válido. Aceita espaços entre os dígitos."""
    digitos = nif.replace(" ", "")
    if not _NOVE_DIGITOS.fullmatch(digitos):
        return False
    if not digitos.startswith(PREFIXOS):
        return False
    return int(digitos[8]) == digito_de_controlo(digitos[:8])


def digito_de_controlo(oito_digitos: str) -> int:
    """Pesos 9, 8, ..., 2; controlo = 11 − (soma mod 11), e 0 quando isso dá 10 ou 11."""
    soma = sum(int(d) * peso for d, peso in zip(oito_digitos, range(9, 1, -1)))
    controlo = 11 - soma % 11
    return 0 if controlo >= 10 else controlo
