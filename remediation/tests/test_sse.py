"""Flux SSE temps réel (générateur) : rejeu + live sans trou ni doublon."""

from __future__ import annotations

import asyncio
import json

import pytest

from conftest import make_event
from timeline import frame, sse_stream

pytestmark = pytest.mark.anyio


def decode(chunk: str) -> dict:
    lines = dict(line.split(": ", 1) for line in chunk.strip().splitlines())
    return {"id": int(lines["id"]), **json.loads(lines["data"])}


async def test_live_stream_delivers_new_events_after_replay(make_env):
    env = make_env(verify=[True])
    gen = sse_stream(env.journal, env.broker, since=0, keepalive_s=5)
    assert await asyncio.wait_for(anext(gen), 1) == "retry: 3000\n\n"

    task = asyncio.create_task(env.run(make_event("data_corruption", source_ip=None)))
    seen = []
    while not seen or seen[-1]["phase"] != "closure":
        seen.append(decode(await asyncio.wait_for(anext(gen), 2)))
    await task

    assert [e["phase"] for e in seen][:2] == ["detection", "decision"]
    ids = [e["id"] for e in seen]
    assert ids == sorted(set(ids))  # ordre strict, aucun doublon
    assert env.broker.subscribers == 1
    await gen.aclose()
    assert env.broker.subscribers == 0  # désabonnement à la déconnexion


async def test_keepalive_comment_when_idle(make_env):
    env = make_env()
    gen = sse_stream(env.journal, env.broker, since=0, keepalive_s=0.05)
    await anext(gen)
    assert await asyncio.wait_for(anext(gen), 1) == ": keepalive\n\n"
    await gen.aclose()


def test_frame_format():
    out = frame({"id": 7, "incident_id": "i", "phase": "action"})
    assert out.startswith("id: 7\nevent: timeline\ndata: {") and out.endswith("}\n\n")
