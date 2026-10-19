"""Fabriques de données fictives."""

from __future__ import annotations

import secrets


def new_fake_iban() -> str:
    """IBAN FICTIF (préfixe FR76 + 20 chiffres aléatoires). Ne passe volontairement pas le contrôle mod-97."""
    digits = "".join(str(secrets.randbelow(10)) for _ in range(20))
    return "FR76 " + " ".join(digits[i : i + 4] for i in range(0, 20, 4))
