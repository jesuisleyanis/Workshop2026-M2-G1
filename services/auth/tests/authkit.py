"""Constantes et helpers partagés par les tests (importables, contrairement à conftest)."""

from prometheus_client import REGISTRY

JWT_SECRET = "test-secret-test-secret-test-secret-0123"
INTERNAL_TOKEN = "internal-token-for-tests"
PASSWORD = "correct-horse-battery"
# IP FIXE du WAF sur le réseau app (compose) : seul pair dont X-Forwarded-For est cru.
WAF_IP = "172.31.0.10"
WAF_PEER = (WAF_IP, 40000)


def sample(name: str, **labels) -> float:
    """Valeur courante d'une métrique du registre Prometheus par défaut (0 si absente)."""
    return REGISTRY.get_sample_value(name, labels) or 0.0
