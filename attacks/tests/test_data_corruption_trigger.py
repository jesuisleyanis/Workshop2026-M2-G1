"""Contrat du déclencheur data_corruption : réversible, données fictives, non destructif.

Ces tests ne lancent pas Ansible ; ils valident statiquement que la paire de playbooks
(backup / corruption) existe, est du YAML valide, et respecte les garde-fous du sujet
(§2, §3.4) : altération réversible de données FICTIVES, jamais de perte de données.
"""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
PLAYBOOKS = ROOT / "infra" / "ansible" / "playbooks"
BACKUP = PLAYBOOKS / "pg_backup.yml"
CORRUPT = PLAYBOOKS / "db_corrupt_fake.yml"
SCENARIO = ROOT / "attacks" / "scenarios" / "data_corruption.yml"


def _load(path: Path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_playbooks_exist_and_are_valid_yaml() -> None:
    for p in (BACKUP, CORRUPT, SCENARIO):
        assert p.is_file(), f"fichier manquant : {p}"
        assert _load(p) is not None


def test_backup_feeds_the_restore_remediation() -> None:
    # La remédiation restore_pg_dump a besoin d'un dump : le backup doit en produire un.
    text = BACKUP.read_text(encoding="utf-8")
    assert "pg_dump" in text
    assert "backups" in text


def test_corruption_is_reversible() -> None:
    play = _load(CORRUPT)[0]
    modes = play["vars"]["mode"]
    # mode par défaut documenté + présence des deux chemins corrupt / revert.
    text = CORRUPT.read_text(encoding="utf-8")
    assert modes == "corrupt"
    assert "mode == 'corrupt'" in text
    assert "mode == 'revert'" in text


def test_corruption_is_not_destructive() -> None:
    text = CORRUPT.read_text(encoding="utf-8").upper()
    # Corruption par renommage uniquement : jamais de DROP/DELETE/TRUNCATE.
    for forbidden in ("DROP TABLE", "DELETE FROM", "TRUNCATE"):
        assert forbidden not in text, f"opération destructive interdite : {forbidden}"
    assert "RENAME TO" in text


def test_targets_only_the_fictitious_database() -> None:
    play = _load(CORRUPT)[0]
    assert play["vars"]["db_name"] == "resilience"
    # Garde-fou explicite dans le playbook.
    assert "base fictive" in CORRUPT.read_text(encoding="utf-8")


def test_scenario_points_to_the_trigger() -> None:
    scenario = _load(SCENARIO)
    params = scenario["parametres"]
    assert "db_corrupt_fake.yml" in params["declencheur"]
    assert scenario["incident_type"] == "data_corruption"
    # La remédiation attendue reste la restauration (pas un simple redémarrage).
    assert scenario["remediation_attendue"] == ["restore_pg_dump"]
