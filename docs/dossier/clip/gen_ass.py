#!/usr/bin/env python3
"""Génère la piste de légendes ASS du Clip Chrono depuis le storyboard (source unique de vérité).

Extrait de `build_clip.sh` pour être testable sans ffmpeg (voir scripts/tests/test_clip_chrono.py).
Chaque segment produit UNE ligne `Dialogue` ; le texte est échappé (pas d'injection de balises ni de
ligne ASS depuis le JSON) et les temps sont validés (0 <= t_start < t_end).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# En-tête ASS complet (Format: standard) : plus sûr pour libass qu'un format tronqué.
_HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
WrapStyle: 2

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: band,DejaVu Sans,40,&H00FFFFFF,&H000000FF,&H00000000,&H96000000,-1,0,0,0,100,100,0,0,3,2,0,2,80,80,60,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"""


def esc(value: object) -> str:
    """Neutralise tout ce qui injecterait une balise ou une 2e ligne ASS depuis le JSON."""
    out = str(value)
    for a, b in (("\\", "/"), ("\r", " "), ("\n", " "), ("{", "("), ("}", ")")):
        out = out.replace(a, b)
    return out.strip()


def _ts(t: float) -> str:
    """Secondes -> H:MM:SS.cc (format de temps ASS)."""
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = t % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def build_ass(doc: dict) -> str:
    lines = [_HEADER]
    for seg in doc["segments"]:
        start = float(seg["t_start"])
        end = float(seg["t_end"])
        if not 0 <= start < end:
            raise ValueError(f"segment {seg.get('temps')!r} : temps invalides ({start} -> {end})")
        text = esc(seg["caption"])
        lines.append(f"Dialogue: 0,{_ts(start)},{_ts(end)},band,,0,0,0,,{text}")
    return "\n".join(lines) + "\n"


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(f"Usage : {argv[0]} <storyboard.json>", file=sys.stderr)
        return 2
    doc = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
    sys.stdout.write(build_ass(doc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
