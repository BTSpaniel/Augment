from pathlib import Path

from augment.config import AppConfig, ContextConfig, LoopConfig, ProviderConfig, ServerConfig
from augment.context.builder import ContextBuilder
from augment.context.memory import MemoryStore, SessionStore


def test_memory_and_context(tmp_path: Path):
    memory = MemoryStore(tmp_path)
    memory.remember_from_user("Remember that I prefer concise answers", session_id="s1")
    assert memory.all()

    sessions = SessionStore(tmp_path)
    sessions.append("s1", "user", "hello")
    history = sessions.history("s1")
    config = AppConfig(ServerConfig(), ProviderConfig(api_key="x"), LoopConfig(), ContextConfig(), tmp_path, tmp_path, tmp_path / "temp")
    builder = ContextBuilder(config, memory)
    context = builder.build(message="hi", history=history)
    assert "[AUGMENT]" in context
    assert "[MEMORY]" in context
    assert builder.stats()["final_chars"] > 0
