"""Scellement AES-256-GCM des données biométriques stockées (gabarits, photos).

Format du blob : `b"v1" + nonce(12) + ciphertext+tag`. L'AAD (ex. identifiant de l'utilisateur)
lie le blob à son propriétaire : un blob recopié sur une autre ligne ne se déchiffre pas.
La clé (32 octets) vient d'un secret monté (SOPS), jamais du code ni des logs.
"""

from __future__ import annotations

import base64
import binascii
import json
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_VERSION = b"v1"
_NONCE_LEN = 12
_KEY_LEN = 32


class SealError(ValueError):
    """Blob altéré, tronqué, de version inconnue, ou clé / AAD incorrecte."""


class Sealer:
    def __init__(self, key: bytes) -> None:
        if len(key) != _KEY_LEN:
            raise ValueError(f"clé de scellement invalide: {_KEY_LEN} octets requis")
        self._aead = AESGCM(key)

    @classmethod
    def from_b64(cls, key_b64: str) -> Sealer:
        try:
            key = base64.b64decode(key_b64.strip(), validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError("clé de scellement: base64 invalide") from exc
        return cls(key)

    def seal(self, plaintext: bytes, aad: bytes) -> bytes:
        nonce = os.urandom(_NONCE_LEN)
        return _VERSION + nonce + self._aead.encrypt(nonce, plaintext, aad)

    def open(self, blob: bytes, aad: bytes) -> bytes:
        header = len(_VERSION) + _NONCE_LEN
        if not blob.startswith(_VERSION) or len(blob) <= header:
            raise SealError("blob scellé invalide")
        nonce = blob[len(_VERSION) : header]
        try:
            return self._aead.decrypt(nonce, blob[header:], aad)
        except InvalidTag as exc:
            raise SealError("déchiffrement impossible (blob altéré, clé ou AAD incorrecte)") from exc


def pack_templates(templates: dict[str, list[float]]) -> bytes:
    """Gabarits par pose -> JSON compact, clés triées (sérialisation déterministe)."""
    return json.dumps(templates, sort_keys=True, separators=(",", ":")).encode()


def unpack_templates(raw: bytes) -> dict[str, list[float]]:
    return {pose: [float(x) for x in vec] for pose, vec in json.loads(raw).items()}


def pack_photos(photos: dict[str, bytes]) -> bytes:
    """Photos par pose -> JSON {pose: base64}."""
    return json.dumps(
        {pose: base64.b64encode(img).decode() for pose, img in photos.items()},
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


def unpack_photos(raw: bytes) -> dict[str, bytes]:
    return {pose: base64.b64decode(b64) for pose, b64 in json.loads(raw).items()}
