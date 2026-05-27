import pytest

from augment.loop.tool_plan import execute_tool_plan, extract_tool_plans, format_plan_results
from augment.tools.default import build_tool_registry


@pytest.mark.asyncio
async def test_tool_plan_extract_and_execute_readonly(tmp_path):
    (tmp_path / "alpha.txt").write_text("alpha")
    registry = build_tool_registry()
    plans = extract_tool_plans('<tool_plan>[{"tool":"list_dir","args":{"path":"."}}, {"tool":"read_file","args":{"path":"alpha.txt"}}]</tool_plan>')
    assert len(plans) == 1
    results = await execute_tool_plan(plans[0], registry, context={"workspace_root": str(tmp_path)})
    assert len(results) == 2
    assert all(item["success"] for item in results)
    formatted = format_plan_results(results)
    assert "tool_result" in formatted
    assert "alpha" in formatted
