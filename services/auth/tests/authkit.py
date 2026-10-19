"""Constantes et helpers partagés par les tests (importables, contrairement à conftest)."""

from prometheus_client import REGISTRY

JWT_SECRET = "test-secret-test-secret-test-secret-0123"
INTERNAL_TOKEN = "internal-token-for-tests"
PASSWORD = "correct-horse-battery"


def sample(name: str, **labels) -> float:
    """Valeur courante d'une métrique du registre Prometheus par défaut (0 si absente)."""
    return REGISTRY.get_sample_value(name, labels) or 0.0
