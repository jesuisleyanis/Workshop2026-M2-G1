"""Charge `scripts/verify_tx` (fichier sans extension .py) comme module de test."""
from __future__ import annotations

import importlib.machinery
import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


@pytest.fixture(scope="session")
def verify_tx():
    loader = importlib.machinery.SourceFileLoader("verify_tx", str(SCRIPTS / "verify_tx"))
    spec = importlib.util.spec_from_loader("verify_tx", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module
