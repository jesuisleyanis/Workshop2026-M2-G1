"""Carte « IP bloquées » : deny-list réelle du WAF enrichie par le journal."""

from blocklist import list_blocked_ips, read_deny_file


def test_deny_file_parsing_ignores_comments_duplicates_and_garbage(tmp_path):
    f = tmp_path / "blocked_ips.conf"
    f.write_text("# vidé par make unblock\n192.168.137.115 1;\n192.168.137.115 1;\n"
                 "1.2.3.4; deny all 1;\n\n::ffff:10.0.0.7 1;\n", encoding="utf-8")
    assert read_deny_file(f) == ["192.168.137.115", "10.0.0.7"]  # IPv4-mappée repliée
    assert read_deny_file(tmp_path / "absent.conf") == []


def test_blocked_ips_are_enriched_with_the_latest_journal_block(tmp_path):
    f = tmp_path / "blocked_ips.conf"
    f.write_text("192.168.137.115 1;\n203.0.113.9 1;\n", encoding="utf-8")
    blocks = [  # le plus récent d'abord (Journal.last_blocks)
        {"ts": "2026-10-21T13:40:00.000Z", "action_type": "waf_blacklist_ip",
         "detail": "192.168.137.115 bloquée (permanent)", "incident_id": "i2", "incident_type": "web_attack"},
        {"ts": "2026-10-21T13:30:00.000Z", "action_type": "waf_block_ip",
         "detail": "192.168.137.115 bloquée (temporary)", "incident_id": "i1", "incident_type": "auth_abuse"},
        {"ts": "2026-10-21T12:00:00.000Z", "action_type": "waf_block_ip",
         "detail": "10.9.9.9 bloquée (temporary)", "incident_id": "i0", "incident_type": "auth_abuse"},
    ]
    out = list_blocked_ips(f, blocks)
    assert out == [
        {"ip": "192.168.137.115", "blocked_at": "2026-10-21T13:40:00.000Z", "expires_at": None,
         "list": "permanent", "incident_id": "i2", "incident_type": "web_attack"},
        # ajoutée hors moteur (ou journal purgé) : listée quand même, c'est ce que le WAF bloque
        {"ip": "203.0.113.9", "blocked_at": None, "expires_at": None, "list": "unknown", "incident_id": None,
         "incident_type": None},
    ]
    # 10.9.9.9 a été débloquée (absente du fichier) : jamais listée, même si le journal s'en souvient
    assert all(e["ip"] != "10.9.9.9" for e in out)
