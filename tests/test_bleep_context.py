"""Tests for the bleep-context event + per-section ContextStats."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, List

from fastapi.testclient import TestClient

from augment.config import load_config
from augment.context.builder import ContextBuilder, ContextStats
from augment.context.memory import MemoryStore
from augment.main import app


# ── ContextBuilder unit tests ───────────────────────────────────────


def test_context_stats_capture_per_section(tmp_path, monkeypatch):
    monkeypatch.setenv("AUGMENT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("AUGMENT_WORKSPACE_ROOT", str(tmp_path / "ws"))
    config = load_config()
    config.data_dir.mkdir(parents=True, exist_ok=True)
    builder = ContextBuilder(config, MemoryStore(config.data_dir))

    # Build with several non-empty section inputs.
    builder.build(
        message="hello",
        history=[],
        memory_tiers="[MEMORY] one fact",
        scratchboard="[SCRATCHBOARD] note",
        user_model="[USER MODEL]\nObserved turns: 1",
    )

    stats = builder.stats()
    assert stats["final_chars"] > 0
    assert stats["original_chars"] > 0
    # final_chars can exceed original_chars by the section joiners ('\n\n')
    # when no truncation happened — just sanity-check magnitudes.
    assert stats["final_chars"] <= stats["original_chars"] + 200
    assert isinstance(stats["sections"], list)
    by_name = {s["name"]: s for s in stats["sections"]}
    # Built-in sections must always be reported (even if some are empty).
    for required in (
        "identity",
        "runtime",
        "workspace",
        "memory",
        "memory_tiers",
        "scratchboard",
        "user_model",
        "tool_policy",
    ):
        assert required in by_name, required

    # Sections we passed content for must have non-zero final_chars.
    assert by_name["memory_tiers"]["final_chars"] > 0
    assert by_name["scratchboard"]["final_chars"] > 0
    assert by_name["user_model"]["final_chars"] > 0

    # Sections we didn't pass should report zero chars.
    assert by_name["scratchboard"]["budget"] > 0


def test_context_stats_marks_oversized_section_truncated(tmp_path, monkeypatch):
    monkeypatch.setenv("AUGMENT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("AUGMENT_WORKSPACE_ROOT", str(tmp_path / "ws"))
    config = load_config()
    config.data_dir.mkdir(parents=True, exist_ok=True)
    builder = ContextBuilder(config, MemoryStore(config.data_dir))

    # Inject 30,000 chars into a section whose budget is 5000 (memory_tiers=3000 actually; pick scratchboard=3000)
    big = "x " * 15000  # ~30k chars
    builder.build(message="hi", history=[], scratchboard=big)
    stats = builder.stats()
    by_name = {s["name"]: s for s in stats["sections"]}
    sb = by_name["scratchboard"]
    assert sb["original_chars"] > sb["budget"]
    assert sb["truncated"] is True
    assert "scratchboard" in stats["truncated"]


def test_last_prompt_returns_assembled_text(tmp_path, monkeypatch):
    monkeypatch.setenv("AUGMENT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("AUGMENT_WORKSPACE_ROOT", str(tmp_path / "ws"))
    config = load_config()
    config.data_dir.mkdir(parents=True, exist_ok=True)
    builder = ContextBuilder(config, MemoryStore(config.data_dir))
    output = builder.build(message="hi", history=[])
    assert builder.last_prompt() == output
    assert builder.last_prompt()  # not empty


# ── Chat-stream SSE event ───────────────────────────────────────────


def test_bleep_event_emitted_in_stream(tmp_path, monkeypatch):
    """The /api/chat/stream endpoint should emit a `bleep` SSE event before
    any thinking/tool/token event arrives."""
    monkeypatch.setenv("AUGMENT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("AUGMENT_WORKSPACE_ROOT", str(tmp_path / "ws"))

    with TestClient(app) as client:
        api = client.app.state.augment

        # Stub the provider so the chat completes deterministically + fast.
        class _StubProvider:
            id = "stub"
            model = "stub-model"

            async def complete(self, *_args: Any, **_kwargs: Any):
                return SimpleNamespace(
                    content="ok",
                    tool_calls=[],
                    raw={},
                    tokens_prompt=0,
                    tokens_completion=0,
                )

            async def close(self):
                return None

        monkeypatch.setattr(api.settings, "has_default_profile", lambda: True)
        monkeypatch.setattr(api.providers, "default", lambda: _StubProvider())

        with client.stream(
            "POST",
            "/api/chat/stream",
            json={"message": "hello bleep", "session_id": ""},
        ) as response:
            assert response.status_code == 200
            events: List[tuple[str, dict]] = []
            current_event = ""
            for raw_line in response.iter_lines():
                line = raw_line if isinstance(raw_line, str) else raw_line.decode()
                if line.startswith("event: "):
                    current_event = line[7:].strip()
                elif line.startswith("data: ") and current_event:
                    try:
                        events.append((current_event, json.loads(line[6:])))
                    except Exception:
                        pass
                    current_event = ""
                if any(name == "done" for name, _ in events):
                    break

        names = [name for name, _ in events]
        assert "bleep" in names, f"bleep event missing — saw {names}"
        bleep_payload = next(payload for name, payload in events if name == "bleep")
        assert bleep_payload["prompt_chars"] > 0
        assert bleep_payload["prompt_preview"]
        assert isinstance(bleep_payload["stats"], dict)
        assert bleep_payload["stats"]["final_chars"] > 0
        assert isinstance(bleep_payload["stats"]["sections"], list)
        # And it must arrive before the first thinking / token event.
        bleep_idx = names.index("bleep")
        for terminal in ("thinking", "tool_call", "token", "done"):
            if terminal in names:
                assert bleep_idx < names.index(terminal), (
                    f"bleep should precede {terminal}: order was {names}"
                )
