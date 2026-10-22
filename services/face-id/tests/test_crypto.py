"""Tests du scellement AES-GCM des gabarits/photos et de leur (dé)sérialisation."""

from __future__ import annotations

import base64
import json
import os

import pytest
from face_id.crypto import (
    SealError,
    Sealer,
    pack_photos,
    pack_templates,
    unpack_photos,
    unpack_templates,
)

KEY = bytes(range(32))


def test_seal_open_round_trip():
    s = Sealer(KEY)
    blob = s.seal(b"secret biometrique", b"alice")
    assert s.open(blob, b"alice") == b"secret biometrique"


def test_blob_est_chiffre_et_versionne():
    blob = Sealer(KEY).seal(b"secret biometrique", b"alice")
    assert blob.startswith(b"v1")
    assert b"secret biometrique" not in blob
    assert len(blob) == 2 + 12 + len(b"secret biometrique") + 16  # version + nonce + ct + tag


def test_nonce_aleatoire_deux_scellements_differents():
    s = Sealer(KEY)
    assert s.seal(b"x", b"a") != s.seal(b"x", b"a")


def test_mauvaise_cle_leve_seal_error():
    blob = Sealer(KEY).seal(b"x", b"alice")
    with pytest.raises(SealError):
        Sealer(os.urandom(32)).open(blob, b"alice")


def test_aad_differente_leve_seal_error():
    s = Sealer(KEY)
    blob = s.seal(b"x", b"alice")
    with pytest.raises(SealError):
        s.open(blob, b"bob")


def test_blob_altere_ou_tronque_leve_seal_error():
    s = Sealer(KEY)
    blob = bytearray(s.seal(b"x", b"alice"))
    blob[-1] ^= 0x01
    with pytest.raises(SealError):
        s.open(bytes(blob), b"alice")
    with pytest.raises(SealError):
        s.open(b"v1", b"alice")
    with pytest.raises(SealError):
        s.open(b"v2" + bytes(40), b"alice")


def test_seal_error_est_une_value_error():
    assert issubclass(SealError, ValueError)


def test_cle_de_16_octets_refusee():
    with pytest.raises(ValueError):
        Sealer(b"0" * 16)


def test_from_b64():
    s = Sealer.from_b64(base64.b64encode(KEY).decode())
    assert s.open(Sealer(KEY).seal(b"x", b"a"), b"a") == b"x"


def test_from_b64_invalide_ou_mauvaise_longueur():
    with pytest.raises(ValueError):
        Sealer.from_b64("pas-du-base64!!")
    with pytest.raises(ValueError):
        Sealer.from_b64(base64.b64encode(b"0" * 16).decode())


def test_pack_unpack_templates_round_trip_et_json_compact_trie():
    t = {"gauche": [0.5, -1.0], "face": [1.0, 2.0]}
    raw = pack_templates(t)
    assert raw == b'{"face":[1.0,2.0],"gauche":[0.5,-1.0]}'
    assert unpack_templates(raw) == t


def test_pack_unpack_photos_round_trip():
    p = {"face": b"\x89PNG-face", "droite": b"jpeg-droite"}
    raw = pack_photos(p)
    assert unpack_photos(raw) == p
    # JSON {pose: base64}
    assert base64.b64decode(json.loads(raw)["face"]) == b"\x89PNG-face"
