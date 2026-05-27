from pathlib import Path

import pytest

from augment.tools.default import build_tool_registry
from augment.tools.files import resolve_under


def test_resolve_under_blocks_escape(tmp_path: Path):
    with pytest.raises(ValueError):
        resolve_under(tmp_path, "../outside.txt")


@pytest.mark.asyncio
async def test_file_tools_read_write_edit(tmp_path: Path):
    registry = build_tool_registry()
    # New policy: relative write_file lands in <scratch_root>/<session_id>/.
    # read_file / edit_file probe workspace → override → scratch, so the same
    # relative path round-trips without forcing the agent to remember the
    # scratch sub-directory.
    context = {
        "workspace_root": str(tmp_path / "ws"),
        "scratch_root": str(tmp_path / "scratch"),
        "session_id": "sess_demo",
    }

    write = await registry.execute("write_file", {"path": "a.txt", "content": "hello world"}, context=context)
    assert write.success
    landed = tmp_path / "scratch" / "sess_demo" / "a.txt"
    assert landed.exists(), f"expected file at {landed}"
    assert landed.read_text() == "hello world"

    read = await registry.execute("read_file", {"path": "a.txt"}, context=context)
    assert "hello world" in read.output
    assert "[FILE CONTEXT]" in read.output

    edit = await registry.execute("edit_file", {"path": "a.txt", "old_string": "world", "new_string": "augment"}, context=context)
    assert edit.success
    assert landed.read_text() == "hello augment"
