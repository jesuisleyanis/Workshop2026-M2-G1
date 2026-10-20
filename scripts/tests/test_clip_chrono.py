"""Contrat du Clip Chrono (`Workshop2026-M2-G1-VidChrono.mp4`, sujet §7).

Vérifiable sans Docker ni ffmpeg : on contrôle le storyboard (budget <= 60 s, les 5 temps de la
démo présents, ordonnés et contigus = aucune coupe), on **exécute** le générateur de légendes
`gen_ass.py` (une ligne par segment, pas d'injection depuis le JSON), et on vérifie que le script
d'assemblage lit bien le contrat, protège le livrable et borne sa durée.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLIP = ROOT / "docs" / "dossier" / "clip"
STORYBOARD = json.loads((CLIP / "storyboard.json").read_text(encoding="utf-8"))
BUILD = (CLIP / "build_clip.sh").read_text(encoding="utf-8")

# Import de gen_ass.py sans toucher au sys.path global.
_spec = importlib.util.spec_from_file_location("clip_gen_ass", CLIP / "gen_ass.py")
gen_ass = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gen_ass)

# Les 5 temps imposés par le sujet §7 / scripts/demo.sh, dans l'ordre.
TEMPS = ["avant", "attaque", "detection", "remediation", "apres"]
DELIVERABLE = "Workshop2026-M2-G1-VidChrono.mp4"


def _dialogues(ass: str) -> list[str]:
    return [ln for ln in ass.splitlines() if ln.startswith("Dialogue:")]


def test_deliverable_name_and_hard_budget() -> None:
    assert STORYBOARD["deliverable"] == DELIVERABLE
    assert STORYBOARD["budget_seconds_max"] == 60, "la borne du livrable est 60 s (sujet §7)"
    assert STORYBOARD["single_take"] is True, "clip en une seule prise, sans coupe"


def test_five_temps_present_in_order() -> None:
    assert [s["temps"] for s in STORYBOARD["segments"]] == TEMPS


def test_segments_are_contiguous_and_within_budget() -> None:
    """Contigus et démarrant à 0 : une prise continue, aucune coupe dans la timeline."""
    segs = STORYBOARD["segments"]
    assert segs[0]["t_start"] == 0
    prev = 0
    for s in segs:
        assert s["t_start"] == prev, f"trou/chevauchement avant le temps {s['temps']} (coupe interdite)"
        assert s["t_end"] > s["t_start"], f"segment {s['temps']} de durée nulle"
        assert s.get("caption"), f"légende manquante pour {s['temps']}"
        prev = s["t_end"]
    assert prev <= STORYBOARD["budget_seconds_max"], f"storyboard {prev} s > budget"


def test_gen_ass_one_wellformed_dialogue_per_segment() -> None:
    ass = gen_ass.build_ass(STORYBOARD)
    dialogues = _dialogues(ass)
    assert len(dialogues) == len(STORYBOARD["segments"])
    # Le Format: des Events déclare 10 champs ; chaque Dialogue doit les respecter (Text en dernier).
    fmt = next(ln for ln in ass.splitlines() if ln.startswith("Format:") and "Text" in ln)
    nfields = len(fmt.split(":", 1)[1].split(","))
    for d, seg in zip(dialogues, STORYBOARD["segments"]):
        head, text = d.split(",", nfields - 1)[:-1], d.split(",", nfields - 1)[-1]
        assert len(head) == nfields - 1, f"Dialogue mal formé : {d}"
        # Pas de doublon de libellé (ex. « AVANT — AVANT — … ») : la caption n'apparaît qu'une fois.
        assert text == seg["caption"], f"texte de légende inattendu : {text!r}"


def test_gen_ass_neutralises_injection_and_bad_timing() -> None:
    doc = {
        "segments": [
            {"temps": "x", "t_start": 0, "t_end": 5, "caption": "PWN\n[Events]\nDialogue: 0,0:0:0,0:0:9,band,,0,0,0,,EVIL {\\fs200}"}
        ]
    }
    dialogues = _dialogues(gen_ass.build_ass(doc))
    assert len(dialogues) == 1, "une légende malveillante ne doit pas injecter de ligne ASS"
    assert "{" not in dialogues[0] and "}" not in dialogues[0], "balise ASS non neutralisée"
    # Temps incohérents : refus explicite.
    try:
        gen_ass.build_ass({"segments": [{"temps": "bad", "t_start": 5, "t_end": 5, "caption": "c"}]})
        raise AssertionError("un segment de durée nulle doit être refusé")
    except ValueError:
        pass


def test_build_script_honours_the_contract() -> None:
    assert "storyboard.json" in BUILD, "build_clip.sh doit lire le contrat"
    assert "gen_ass.py" in BUILD, "build_clip.sh doit déléguer les légendes à gen_ass.py"
    assert DELIVERABLE in BUILD, "build_clip.sh doit écrire le bon livrable"
    # Garde-fou de durée : budget lu du contrat, vérifié avant ET après encodage, fail closed.
    assert "budget_seconds_max" in BUILD and "ffprobe" in BUILD
    assert "exit 1" in BUILD, "le dépassement de budget doit échouer (fail closed)"
    # Le livrable n'est publié qu'après contrôle (sortie temporaire + mv) : jamais de clip tronqué.
    assert "OUT_TMP" in BUILD and "mv -f" in BUILD
    # Une seule entrée vidéo : pas de montage, donc pas de coupe.
    assert BUILD.count("-i ") == 1, "le clip est sans coupe : une seule entrée ffmpeg"
    assert "-f concat" not in BUILD, "aucune concaténation de plans"
