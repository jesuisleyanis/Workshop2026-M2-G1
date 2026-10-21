"""IP source d'un incident : l'IP qui DOMINE les logs du WAF sur la fenêtre de l'anomalie.

Ce n'est pas de la détection (la décision reste au modèle, R8) : une fois l'anomalie décidée,
on cherche QUI la provoque pour que les actions de blocage (`waf_block_ip`, `waf_blacklist_ip`,
`source: from_event`) aient une cible. Sans ce champ, ces actions échouent et l'attaquant n'est
jamais coupé (docs/plan-amelioration-detection.md, D1).

Source : logs JSON d'accès du WAF dans Loki (`client_ip`, `http_path`, `http_status`), filtrés
selon le type d'incident. Garde-fous : une IP n'est retenue que si elle pèse au moins
`min_share` des lignes ET `min_count` lignes ; sinon aucune IP (on ne bloque pas au hasard).
Toute erreur (Loki injoignable, réponse illisible) -> None : l'événement part quand même.
"""

from __future__ import annotations

import ipaddress
import time

import httpx

from resilience_common import IncidentType, get_logger

log = get_logger("detector")

#: Filtre LogQL par type d'incident (logs d'accès du WAF). Pas de filtre = toutes les requêtes.
#: `data_corruption` et `unknown` n'ont pas d'IP pertinente (corruption interne / signature floue).
FILTERS: dict[IncidentType, str | None] = {
    IncidentType.SERVICE_FLOOD: "",
    IncidentType.AUTH_ABUSE: ' | http_path=~"/api/v1/(login|register|auth/.*)" | http_status=~"401|429"',
    IncidentType.WEB_ATTACK: ' | http_status="403"',
    IncidentType.DATA_CORRUPTION: None,
    IncidentType.UNKNOWN: None,
}


def build_query(incident_type: IncidentType, window_s: int) -> str | None:
    """Requête LogQL « nombre de lignes par client_ip » sur la fenêtre, ou None si sans objet."""
    extra = FILTERS.get(incident_type)
    if extra is None:
        return None
    return (
        f'sum by (client_ip) (count_over_time({{service="waf"}} | json | __error__=""{extra} '
        f"[{int(window_s)}s]))"
    )


def parse_networks(spec: str) -> tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]:
    """'172.30.0.0/24,172.31.0.0/24' -> réseaux (IP seule acceptée : /32)."""
    return tuple(ipaddress.ip_network(s.strip(), strict=False) for s in spec.split(",") if s.strip())


def dominant_ip(result: list[dict], min_share: float, min_count: int,
                exclude: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...] = ()) -> str | None:
    """IP dominante d'un résultat Loki `vector` ; None si aucune ne domine assez.

    `exclude` : réseaux Docker internes, jamais candidats (le trafic verify_tx de la remédiation y
    passe — constaté le 21/10 : sans ce filtre, la remédiation a été désignée puis bloquée)."""
    counts: dict[str, float] = {}
    for sample in result:
        raw = sample.get("metric", {}).get("client_ip")
        try:
            addr = ipaddress.ip_address(str(raw))
            n = float(sample["value"][1])
        except (ValueError, KeyError, IndexError, TypeError):
            continue  # ligne sans IP littérale valide : jamais de cible fabriquée
        if any(addr.version == net.version and addr in net for net in exclude):
            continue
        ip = str(addr)
        counts[ip] = counts.get(ip, 0.0) + n
    total = sum(counts.values())
    if not total:
        return None
    ip, n = max(counts.items(), key=lambda kv: kv[1])
    return ip if n >= min_count and n / total >= min_share else None


class LokiSourceResolver:
    """Interroge Loki (requête instantanée) pour l'IP dominante d'un incident."""

    def __init__(
        self,
        url: str,
        *,
        window_s: int = 30,
        min_share: float = 0.6,
        min_count: int = 5,
        exclude: str = "",
        timeout: float = 2.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.url = url.rstrip("/")
        self.window_s, self.min_share, self.min_count = window_s, min_share, min_count
        self.exclude = parse_networks(exclude)
        self._client = httpx.AsyncClient(timeout=timeout, transport=transport)

    async def resolve(self, incident_type: IncidentType) -> str | None:
        query = build_query(incident_type, self.window_s)
        if query is None:
            return None
        try:
            resp = await self._client.get(
                f"{self.url}/loki/api/v1/query", params={"query": query, "time": str(time.time_ns())}
            )
            resp.raise_for_status()
            result = resp.json()["data"]["result"]
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            log.warning(f"IP source non résolue (Loki : {type(exc).__name__})")
            return None
        return dominant_ip(result, self.min_share, self.min_count, self.exclude)

    async def aclose(self) -> None:
        await self._client.aclose()
