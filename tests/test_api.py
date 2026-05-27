import json
import re

from fastapi.testclient import TestClient

from augment.main import app


def test_health_and_static_ui(tmp_path, monkeypatch):
    monkeypatch.setenv("AUGMENT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("AUGMENT_WORKSPACE_ROOT", str(tmp_path / "workspace"))
    with TestClient(app) as client:
        health = client.get("/healthz")
        assert health.status_code == 200
        assert health.json()["status"] == "ok"
        page = client.get("/")
        assert page.status_code == 200
        assert "Augment" in page.text
        tools = client.get("/api/tools")
        assert tools.status_code == 200
        assert "read_file" in tools.json()["tools"]


def test_logs_api_records_and_lists_console_events(tmp_path, monkeypatch):
    monkeypatch.setenv("AUGMENT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("AUGMENT_WORKSPACE_ROOT", str(tmp_path / "workspace"))
    with TestClient(app) as client:
        recorded = client.post("/api/logs", json={
            "level": "warn",
            "logger": "ui.console",
            "message": "browser warning",
            "source": "ui",
            "detail": {"file": "app.js"},
        })
        assert recorded.status_code == 200
        listing = client.get("/api/logs?limit=20")
        assert listing.status_code == 200
        payload = listing.json()
        assert payload["path"]
        assert any(event.get("message") == "browser warning" for event in payload["events"])


def test_provider_settings_sessions_and_mailbox_api(tmp_path, monkeypatch):
    monkeypatch.setenv("AUGMENT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("AUGMENT_WORKSPACE_ROOT", str(tmp_path / "workspace"))
    with TestClient(app) as client:
        provider = client.get("/api/providers")
        assert provider.status_code == 200
        assert "provider" in provider.json()

        updated = client.put("/api/providers", json={"preset": "lmstudio", "model": "local-test"})
        assert updated.status_code == 200
        assert updated.json()["provider"]["model"] == "local-test"

        session_id = "test_session_api"
        note = client.post(f"/api/sessions/{session_id}/mailbox", json={"content": "Use concise replies", "kind": "preference"})
        assert note.status_code == 200
        mailbox = client.get(f"/api/sessions/{session_id}/mailbox")
        assert mailbox.status_code == 200
        assert mailbox.json()["mailbox"][0]["content"] == "Use concise replies"

        clear = client.delete(f"/api/sessions/{session_id}/history")
        assert clear.status_code == 200
        sessions = client.get("/api/sessions")
        assert sessions.status_code == 200
        assert "sessions" in sessions.json()


def test_agent_profile_and_tools_endpoints(tmp_path, monkeypatch):
    monkeypatch.setenv("AUGMENT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("AUGMENT_WORKSPACE_ROOT", str(tmp_path / "workspace"))
    with TestClient(app) as client:
        agent = client.get("/api/agent")
        assert agent.status_code == 200
        body = agent.json()
        assert body["agent"]["name"]
        assert isinstance(body["tools"], list)
        assert body["agent"]["capability"]["score"] == 100

        updated = client.put("/api/agent", json={"name": "Luna", "role": "Coding co-pilot"})
        assert updated.status_code == 200
        assert updated.json()["agent"]["name"] == "Luna"

        tools = client.get("/api/tools").json()
        assert "items" in tools
        assert any(item["name"] == "read_file" for item in tools["items"])


def test_provider_presets_and_key_autodetect(tmp_path, monkeypatch):
    monkeypatch.setenv("AUGMENT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("AUGMENT_WORKSPACE_ROOT", str(tmp_path / "workspace"))
    with TestClient(app) as client:
        presets = client.get("/api/providers/presets")
        assert presets.status_code == 200
        ids = {item["id"] for item in presets.json()["presets"]}
        assert {"groq", "openai", "anthropic", "openrouter", "ollama", "lmstudio"}.issubset(ids)

        # Auto-detect groq from key prefix (no preset provided).
        updated = client.put("/api/providers", json={"api_key": "gsk_test_autodetect"})
        assert updated.status_code == 200
        body = updated.json()
        assert body["detected_preset"] == "groq"
        assert body["provider"]["id"] == "groq"
        assert body["provider"]["endpoint"].startswith("https://api.groq.com")
        assert body["provider"]["has_inline_key"] is True

        # Local preset clears key requirement.
        local = client.put("/api/providers", json={"preset": "lmstudio"})
        assert local.status_code == 200
        assert local.json()["provider"]["key_required"] is False


def test_multi_provider_lifecycle(tmp_path, monkeypatch):
    monkeypatch.setenv("AUGMENT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("AUGMENT_WORKSPACE_ROOT", str(tmp_path / "workspace"))
    with TestClient(app) as client:
        listing = client.get("/api/providers").json()
        assert listing["profiles"] == [], "store should start empty"
        assert listing["default_id"] == ""

        added = client.post("/api/providers/add", json={"preset": "lmstudio"})
        assert added.status_code == 200
        body = added.json()
        assert body["profile"]["preset_id"] == "lmstudio"
        assert body["profile"]["key_required"] is False
        assert body["default_id"] == body["profile"]["id"]
        assert any(profile["preset_id"] == "lmstudio" for profile in body["profiles"])

        # Auto-detect Groq from key on add.
        groq = client.post("/api/providers/add", json={"api_key": "gsk_test_demo"})
        assert groq.status_code == 200
        groq_body = groq.json()
        assert groq_body["detected_preset"] == "groq"
        groq_id = groq_body["profile"]["id"]
        assert groq_body["profiles"]
        assert groq_body["default_id"] == groq_id

        # Switch default back to lmstudio.
        switched = client.post(f"/api/providers/{body['profile']['id']}/default")
        assert switched.status_code == 200
        assert switched.json()["default_id"] == body["profile"]["id"]

        # Remove groq.
        removed = client.delete(f"/api/providers/{groq_id}")
        assert removed.status_code == 200
        assert removed.json()["removed"] is True
        assert all(profile["id"] != groq_id for profile in removed.json()["profiles"])

        # Removing the last profile should leave the store empty (no auto-reseed).
        last_id = removed.json()["default_id"]
        cleared = client.delete(f"/api/providers/{last_id}")
        assert cleared.status_code == 200
        assert cleared.json()["profiles"] == []
        assert cleared.json()["default_id"] == ""

        # Chat must refuse to run without a configured provider.
        chat = client.post("/api/chat", json={"message": "hi", "session_id": "empty"})
        assert chat.status_code >= 400
        assert "provider" in chat.text.lower()


def test_discover_from_env_and_fail_keys(tmp_path, monkeypatch):
    import json

    data_dir = tmp_path / "data"
    fail_dir = tmp_path / "fail-import"
    (fail_dir / "providers").mkdir(parents=True)
    (fail_dir / "providers" / "key_overrides.json").write_text(
        json.dumps({"mistral": {"api_key": "mistral-test-key"}}), encoding="utf-8"
    )
    (fail_dir / "providers" / "providers.json").write_text(
        json.dumps({"mistral": {"endpoint": "https://api.mistral.ai/v1", "model": "mistral-large-latest", "display_name": "Mistral AI"}}),
        encoding="utf-8",
    )

    monkeypatch.setenv("AUGMENT_DATA_DIR", str(data_dir))
    monkeypatch.setenv("AUGMENT_WORKSPACE_ROOT", str(tmp_path / "workspace"))
    monkeypatch.setenv("AUGMENT_DISCOVER_SOURCES", str(fail_dir))
    monkeypatch.setenv("GROQ_API_KEY", "gsk_env_test_key")

    with TestClient(app) as client:
        listing = client.get("/api/providers").json()
        preset_ids = {profile["preset_id"] for profile in listing["profiles"]}
        assert "groq" in preset_ids, "GROQ_API_KEY should auto-create a groq profile"
        assert "mistral" in preset_ids, "FAIL key_overrides should be imported"

        groq = next(p for p in listing["profiles"] if p["preset_id"] == "groq")
        assert groq["has_env_key"] is True
        assert groq["source"].startswith("env:GROQ_API_KEY")

        mistral = next(p for p in listing["profiles"] if p["preset_id"] == "mistral")
        assert mistral["has_inline_key"] is True
        assert "fail-import" in mistral["source"].replace("\\", "/")

        # Remove and verify it does not get re-added by discovery.
        client.delete(f"/api/providers/{mistral['id']}")
        rediscover = client.post("/api/providers/discover").json()
        assert all(profile["preset_id"] != "mistral" for profile in rediscover["profiles"])
        assert "mistral" in rediscover["removed_presets"]

        # Restore the preset and re-discover.
        restored = client.post("/api/providers/discover/restore/mistral").json()
        assert any(profile["preset_id"] == "mistral" for profile in restored["profiles"])
        assert "mistral" not in restored["removed_presets"]


def test_tool_packs_and_skills_catalog(tmp_path, monkeypatch):
    monkeypatch.setenv("AUGMENT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("AUGMENT_WORKSPACE_ROOT", str(tmp_path / "workspace"))
    with TestClient(app) as client:
        packs = client.get("/api/toolpacks").json()
        pack_ids = {pack["id"] for pack in packs["packs"]}
        assert {"filesystem", "search"}.issubset(pack_ids)
        assert packs["tool_count"] >= 6
        filesystem_pack = next(pack for pack in packs["packs"] if pack["id"] == "filesystem")
        states = {tool["state"] for tool in filesystem_pack["tools"]}
        assert {"ready", "effectful"}.issubset(states), "read-only vs mutating tools should both surface"

        catalog = client.get("/api/skills/catalog").json()
        assert catalog["dormant_packs"]["categories"]
        assert len(catalog["dormant_packs"]["packs"]) >= 20
        assert catalog["adaptive_skills"] == []

        generated = client.post("/api/skills/generate", json={"objective": "Wire FAIL parity for tool packs and skills"})
        assert generated.status_code == 200
        skills = generated.json()["skills"]
        kinds = {skill["kind"] for skill in skills}
        assert "tool_graph" in kinds
        assert "current_build" in kinds

        ctx = client.get("/api/skills/context").json()["context"]
        assert "ADAPTIVE SKILLS" in ctx
        assert "Tool Graph" in ctx


def test_agent_profile_soul_and_history(tmp_path, monkeypatch):
    monkeypatch.setenv("AUGMENT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("AUGMENT_WORKSPACE_ROOT", str(tmp_path / "workspace"))
    with TestClient(app) as client:
        # Default profile has all the new fields.
        agent = client.get("/api/agent").json()["agent"]
        assert agent["name"] == "Augment"
        assert "description" in agent
        assert agent["soul_enabled"] is True

        # Update profile (description + soul toggle).
        updated = client.put("/api/agent", json={
            "name": "Luna",
            "role": "Commander / Orchestrator",
            "description": "Owns the mission, routes work to the right specialists.",
            "persona": "Commanding, warm, protective, decisive, and honest.",
            "soul_enabled": True,
        }).json()["agent"]
        assert updated["name"] == "Luna"
        assert updated["description"].startswith("Owns the mission")

        # Soul files are auto-generated with Luna identity baked in.
        soul = client.get("/api/agent/soul").json()
        assert soul["enabled"] is True
        assert soul["files"]["soul"].startswith("# Luna Soul")
        assert "Luna Personality" in soul["files"]["personality"]
        assert "Luna History" in soul["files"]["history"]
        assert set(soul["filenames"]) == {"soul", "personality", "history"}

        # Edit a soul file.
        edited = client.put("/api/agent/soul", json={
            "files": {"soul": "# Luna Soul\n\nThe captain of the room."},
            "enabled": True,
        }).json()
        assert edited["files"]["soul"].startswith("# Luna Soul")
        assert "The captain of the room." in edited["files"]["soul"]

        # Record a history lesson and confirm it appears.
        history_payload = client.post("/api/agent/soul/history", json={
            "lesson": "Preserve workspace state when refactoring across sessions.",
            "metadata": {"session": "abc123"},
        }).json()
        assert "Preserve workspace state" in history_payload["files"]["history"]
        assert "session=abc123" in history_payload["files"]["history"]

        # Reset wipes back to defaults.
        reset = client.post("/api/agent/soul/reset").json()
        assert reset["files"]["soul"].startswith("# Luna Soul")
        assert "The captain of the room." not in reset["files"]["soul"]

        # Toggling soul off should disable injection but keep the files.
        toggled = client.put("/api/agent/soul", json={"enabled": False, "files": {}}).json()
        assert toggled["enabled"] is False
        assert toggled["files"]["soul"]


def test_agent_soul_context_block_unit(tmp_path):
    from augment.soul import build_agent_soul_context, read_agent_soul_files

    profile = {"name": "Luna", "role": "Captain", "soul_enabled": True}
    # Reading auto-creates the defaults.
    payload = read_agent_soul_files(tmp_path, profile)
    assert payload["files"]["soul"]
    block = build_agent_soul_context(tmp_path, profile)
    assert "[AGENT SOUL]" in block
    assert "[AGENT PERSONALITY]" in block
    assert "[AGENT HISTORY]" in block

    # Disabled returns empty.
    disabled_profile = {**profile, "soul_enabled": False}
    assert build_agent_soul_context(tmp_path, disabled_profile) == ""


def test_codex_endpoints_without_runtime(tmp_path, monkeypatch):
    monkeypatch.setenv("AUGMENT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("AUGMENT_WORKSPACE_ROOT", str(tmp_path / "workspace"))
    # Point CODEX_BIN at something that definitely does not exist so the
    # resolver returns an empty string regardless of the developer's machine.
    monkeypatch.setenv("CODEX_BIN", str(tmp_path / "does-not-exist" / "codex.exe"))
    with TestClient(app) as client:
        status = client.get("/api/codex/status").json()
        assert status["available"] is False
        assert status["executable_found"] is False
        assert "setup" in status and status["setup"]["summary"]

        account = client.get("/api/codex/account").json()
        # Outcome depends on whether the developer has the openai_codex SDK
        # installed and signed in; we only assert the response shape.
        assert "authenticated" in account
        assert isinstance(account["authenticated"], bool)
        if not account["authenticated"]:
            assert account.get("error")

        login_status = client.get("/api/codex/login").json()
        assert login_status["status"] == "idle"

        cancel = client.post("/api/codex/login/cancel").json()
        assert cancel == {"ok": True, "status": "cancelled"}


def test_codex_resolve_bin_prefers_env(tmp_path, monkeypatch):
    from augment.codex.bridge import _resolve_codex_bin

    fake = tmp_path / "fake-codex.exe"
    fake.write_text("not a real binary", encoding="utf-8")
    monkeypatch.setenv("CODEX_BIN", str(fake))
    assert _resolve_codex_bin() == str(fake.resolve())

    monkeypatch.delenv("CODEX_BIN", raising=False)
    # With nothing configured and no codex on PATH the resolver should yield "".
    monkeypatch.setattr("augment.codex.bridge._find_python_codex_cli_bin", lambda: "")
    monkeypatch.setattr("augment.codex.bridge._find_scriptable_path_codex", lambda: "")
    assert _resolve_codex_bin() == ""


def test_detect_provider_from_key_unit():
    from augment.providers.presets import detect_provider_from_key

    assert detect_provider_from_key("gsk_abc") == "groq"
    assert detect_provider_from_key("sk-ant-xyz") == "anthropic"
    assert detect_provider_from_key("sk-or-foo") == "openrouter"
    assert detect_provider_from_key("sk-bar") == "openai"
    assert detect_provider_from_key("") == ""
    assert detect_provider_from_key("random") == ""


def test_vision_capability_surfaced_on_profile_snapshot(tmp_path, monkeypatch):
    """Profiles snapshot a preset's capabilities + a derived `vision` flag for the UI."""
    monkeypatch.setenv("AUGMENT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("AUGMENT_WORKSPACE_ROOT", str(tmp_path / "workspace"))

    with TestClient(app) as client:
        # OpenAI preset advertises vision.
        client.post("/api/providers/add", json={"preset": "openai", "api_key": "sk-test-vision"})
        # Groq preset does not.
        client.post("/api/providers/add", json={"preset": "groq", "api_key": "gsk_no_vision"})

        profiles = client.get("/api/providers").json()["profiles"]
        by_id = {p["id"]: p for p in profiles}

        assert by_id["openai"]["vision"] is True
        assert "vision" in by_id["openai"]["capabilities"]
        assert by_id["groq"]["vision"] is False
        assert "vision" not in by_id["groq"]["capabilities"]


def test_react_loop_user_content_is_multipart_when_images_supplied():
    """ReAct loop must put text + image_url parts into the active user message."""
    from augment.loop.react import _build_user_content

    assert _build_user_content("look", []) == "look"
    assert _build_user_content("look", None) == "look"

    parts = _build_user_content(
        "what is this?",
        ["data:image/png;base64,AAA", "https://example.com/cat.jpg"],
    )
    assert isinstance(parts, list)
    assert parts[0] == {"type": "text", "text": "what is this?"}
    assert parts[1] == {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAA"}}
    assert parts[2] == {"type": "image_url", "image_url": {"url": "https://example.com/cat.jpg"}}


def test_openai_compat_serialises_multipart_content_through():
    """OpenAI-compat provider must pass multipart content arrays through unchanged."""
    from augment.providers.base import Message
    from augment.providers.openai_compat import _message_to_dict

    multipart = [
        {"type": "text", "text": "what is this?"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAA"}},
    ]
    msg = Message(role="user", content=multipart)
    serialised = _message_to_dict(msg)
    assert serialised["role"] == "user"
    assert serialised["content"] is multipart  # passed through as-is


def test_chat_stream_forwards_images_to_app_chat(tmp_path, monkeypatch):
    """The streaming endpoint must forward the body.images list into AugmentApp.chat."""
    monkeypatch.setenv("AUGMENT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("AUGMENT_WORKSPACE_ROOT", str(tmp_path / "workspace"))

    from augment.service import ChatResult

    captured: dict[str, object] = {}

    async def fake_chat(self, message, *, session_id="", step_callback=None, images=None, **_kwargs):  # type: ignore[no-self-use]
        captured["images"] = list(images or [])
        captured["message"] = message
        if step_callback:
            await step_callback({"kind": "final", "content": "ok"})
        return ChatResult(
            reply="ok",
            session_id=session_id or "sess_x",
            model="stub",
            tool_calls=0,
            iterations=1,
            stopped_reason="final_answer",
            scratchpad=[],
            context_stats={"original_chars": 0, "final_chars": 0, "truncated": []},
        )

    monkeypatch.setattr("augment.service.AugmentApp.chat", fake_chat)
    monkeypatch.setattr("augment.settings.SettingsStore.has_default_profile", lambda self: True)

    payload = {
        "message": "what's in this",
        "session_id": "sess_x",
        "images": ["data:image/png;base64,AAA", "https://example.com/cat.jpg"],
    }
    with TestClient(app) as client:
        with client.stream("POST", "/api/chat/stream", json=payload) as response:
            assert response.status_code == 200
            # Drain the stream.
            for _ in response.iter_lines():
                pass

    assert captured.get("message") == "what's in this"
    assert captured.get("images") == [
        "data:image/png;base64,AAA",
        "https://example.com/cat.jpg",
    ]


def test_codex_preset_in_catalog_and_routes_to_codex_provider():
    """Codex must appear in the preset catalog and route through CodexProvider."""
    from augment.config import ProviderConfig
    from augment.providers.codex_provider import CodexProvider
    from augment.providers.presets import PRESETS, list_presets
    from augment.providers.registry import build_provider

    assert "codex" in PRESETS
    ids = {preset["id"] for preset in list_presets()}
    assert "codex" in ids

    cfg = ProviderConfig(
        id="codex",
        name="ChatGPT / Codex",
        endpoint="",
        api_key_env="",
        api_key="",
        model="gpt-5.5 (medium)",
        timeout_seconds=120.0,
    )
    provider = build_provider(cfg)
    assert isinstance(provider, CodexProvider)
    assert provider.model == "gpt-5.5 (medium)"


def test_codex_auto_discovery_when_authenticated(tmp_path, monkeypatch):
    """When the local Codex login is authenticated, discovery adds a codex profile."""
    monkeypatch.setenv("AUGMENT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("AUGMENT_WORKSPACE_ROOT", str(tmp_path / "workspace"))
    # Override the conftest stub so this test exercises the auth path.
    monkeypatch.setattr(
        "augment.settings.SettingsStore._codex_authenticated",
        staticmethod(lambda: True),
    )
    with TestClient(app) as client:
        listing = client.get("/api/providers").json()
        profile_ids = {profile["id"] for profile in listing["profiles"]}
        assert "codex" in profile_ids, "codex profile should be auto-discovered when authenticated"
        codex_profile = next(p for p in listing["profiles"] if p["id"] == "codex")
        assert codex_profile["endpoint"] == "", "codex profile must not inherit a default endpoint"
        assert codex_profile["api_key_env"] == "", "codex profile must not inherit an api_key_env"
        assert codex_profile["key_required"] is False


def test_sessions_and_mailbox_are_isolated_per_session_id(tmp_path, monkeypatch):
    """Messages and mailbox notes written to one session must never leak into another."""
    monkeypatch.setenv("AUGMENT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("AUGMENT_WORKSPACE_ROOT", str(tmp_path / "workspace"))

    with TestClient(app) as client:
        # Two distinct sessions, each gets one mailbox note.
        assert client.post("/api/sessions/sess_alpha/mailbox", json={"content": "alpha-note"}).status_code == 200
        assert client.post("/api/sessions/sess_beta/mailbox", json={"content": "beta-note"}).status_code == 200

        alpha = client.get("/api/sessions/sess_alpha/mailbox").json()["mailbox"]
        beta = client.get("/api/sessions/sess_beta/mailbox").json()["mailbox"]

        assert len(alpha) == 1 and alpha[0]["content"] == "alpha-note"
        assert len(beta) == 1 and beta[0]["content"] == "beta-note"
        assert alpha[0]["session_id"] == "sess_alpha"
        assert beta[0]["session_id"] == "sess_beta"

        # Clearing one session's mailbox must not affect the other.
        client.delete("/api/sessions/sess_alpha")
        beta_after = client.get("/api/sessions/sess_beta/mailbox").json()["mailbox"]
        assert len(beta_after) == 1 and beta_after[0]["content"] == "beta-note"


def test_chat_stream_emits_resolved_session_id_when_empty(tmp_path, monkeypatch):
    """When the client sends session_id='', the `started` event must carry the resolved id."""
    monkeypatch.setenv("AUGMENT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("AUGMENT_WORKSPACE_ROOT", str(tmp_path / "workspace"))

    from augment.service import ChatResult

    captured: dict[str, str] = {}

    async def fake_chat(self, message, *, session_id="", step_callback=None, **_kwargs):  # type: ignore[no-self-use]
        captured["session_id"] = session_id  # what app.chat actually receives
        if step_callback:
            await step_callback({"kind": "final", "content": "ok"})
        return ChatResult(
            reply="ok",
            session_id=session_id,
            model="stub",
            tool_calls=0,
            iterations=1,
            stopped_reason="final_answer",
            scratchpad=[],
            context_stats={"original_chars": 0, "final_chars": 0, "truncated": []},
        )

    monkeypatch.setattr("augment.service.AugmentApp.chat", fake_chat)
    monkeypatch.setattr("augment.settings.SettingsStore.has_default_profile", lambda self: True)

    with TestClient(app) as client:
        with client.stream("POST", "/api/chat/stream", json={"message": "hi", "session_id": ""}) as response:
            assert response.status_code == 200
            text = "\n".join(list(response.iter_lines()))

    # The started event must include a non-empty resolved session_id…
    started_match = re.search(r"event: started\ndata: ({.*})", text)
    assert started_match, f"started event missing in stream: {text[:400]}"
    started_payload = json.loads(started_match.group(1))
    assert started_payload["session_id"], "started event must echo a resolved session_id"
    # …and that exact id must be what app.chat() received.
    assert captured.get("session_id") == started_payload["session_id"]


def test_chat_stream_emits_typed_sse_events(tmp_path, monkeypatch):
    """The stream endpoint must emit FAIL-style typed SSE events around chat()."""
    monkeypatch.setenv("AUGMENT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("AUGMENT_WORKSPACE_ROOT", str(tmp_path / "workspace"))

    from dataclasses import asdict
    from augment.service import ChatResult

    async def fake_chat(self, message, *, session_id="", step_callback=None, **_kwargs):  # type: ignore[no-self-use]
        sid = session_id or "sess_streamed"
        if step_callback:
            await step_callback({"kind": "thought", "content": "Reading the workspace."})
            await step_callback({
                "kind": "action",
                "tool": "read_file",
                "args": {"path": "README.md"},
                "tool_calls": 1,
            })
            await step_callback({
                "kind": "observation",
                "tool": "read_file",
                "args": {"path": "README.md"},
                "success": True,
                "output": "# augment",
                "error": "",
                "duration_ms": 4.2,
                "tool_calls": 1,
            })
            await step_callback({"kind": "final", "content": "Done."})
        return ChatResult(
            reply="Done.",
            session_id=sid,
            model="stub-model",
            tool_calls=1,
            iterations=1,
            stopped_reason="final_answer",
            scratchpad=[],
            context_stats={"original_chars": 10, "final_chars": 10, "truncated": []},
            tool_count_sources={"result": 1, "scratchpad_actions": 0, "stream_events": 1},
        )

    # Patch chat() and ensure the SSE endpoint thinks a provider is configured.
    monkeypatch.setattr("augment.service.AugmentApp.chat", fake_chat)
    monkeypatch.setattr(
        "augment.settings.SettingsStore.has_default_profile",
        lambda self: True,
    )

    with TestClient(app) as client:
        with client.stream(
            "POST",
            "/api/chat/stream",
            json={"message": "hi", "session_id": "sess_streamed"},
        ) as response:
            assert response.status_code == 200
            assert response.headers.get("content-type", "").startswith("text/event-stream")
            chunks: list[str] = []
            for raw in response.iter_lines():
                chunks.append(raw)
            text = "\n".join(chunks)

    assert "event: started" in text
    assert "event: thinking" in text
    assert "event: tool_call" in text
    assert "event: tool_result" in text
    assert "event: token" in text
    assert "event: done" in text
    tool_call_match = re.search(r"event: tool_call\ndata: ({.*})", text)
    tool_result_match = re.search(r"event: tool_result\ndata: ({.*})", text)
    done_match = re.search(r"event: done\ndata: ({.*})", text)
    assert tool_call_match and json.loads(tool_call_match.group(1))["tool_calls"] == 1
    assert tool_result_match and json.loads(tool_result_match.group(1))["tool_calls"] == 1
    assert done_match and json.loads(done_match.group(1))["tool_calls"] == 1
    done_payload = json.loads(done_match.group(1))
    assert done_payload.get("tool_count_sources", {}).get("result") == 1


def test_codex_model_choice_parsing():
    """parse_codex_model_choice handles labelled + bare model strings."""
    from augment.codex.bridge import codex_available_model_choices, parse_codex_model_choice

    assert parse_codex_model_choice("gpt-5.5 (medium)") == {
        "model": "gpt-5.5",
        "reasoning_effort": "medium",
    }
    assert parse_codex_model_choice("gpt-5.4") == {
        "model": "gpt-5.4",
        "reasoning_effort": "medium",
    }
    # Fallback list (when SDK call fails) always returns labelled choices.
    fallback = codex_available_model_choices()
    assert fallback, "fallback model list must not be empty"
    for entry in fallback:
        assert "label" in entry and "model" in entry and "reasoning_effort" in entry
