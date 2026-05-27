from typing import Any

import pytest

from augment.loop.react import ReActLoop
from augment.providers.base import LLMResponse, Message
from augment.tools.default import build_tool_registry


class FakeProvider:
    id = "fake"
    name = "Fake"
    model = "fake-model"

    def __init__(self) -> None:
        self.calls = 0

    async def complete(self, messages: list[Message], **kwargs: Any) -> LLMResponse:
        self.calls += 1
        if self.calls == 1:
            return LLMResponse(content='<tool_plan>[{"tool":"list_dir","args":{"path":"."}}]</tool_plan>')
        return LLMResponse(content="Final answer with evidence.")


@pytest.mark.asyncio
async def test_react_loop_runs_tool_plan(tmp_path):
    (tmp_path / "file.txt").write_text("ok")
    loop = ReActLoop(FakeProvider(), build_tool_registry(), max_iterations=4)
    result = await loop.run("list files", tool_context={"workspace_root": str(tmp_path)})
    assert result.content == "Final answer with evidence."
    assert result.tool_calls == 1
    assert result.stopped_reason == "final_answer"
