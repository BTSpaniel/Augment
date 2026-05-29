"""Tests for host-environment detection and the compat command interceptor.

Covers detect_environment / environment_prompt_block and every compat verb
(mkdir / touch / rm / ls / cat / echo redirect / py_compile) plus the
fall-through behavior that lets real shell commands pass untouched.
"""
from __future__ import annotations

import platform
from pathlib import Path

from augment.context.environment import detect_environment, environment_prompt_block
from augment.tools.compat import try_compat_command


def _ctx(tmp_path: Path) -> dict:
    return {"workspace_root": str(tmp_path)}


# ── environment detection ───────────────────────────────────────────


def test_detect_environment_keys_present():
    env = detect_environment(refresh=True)
    for key in ("os", "shell", "is_windows", "available_tools", "missing_tools", "python_version"):
        assert key in env
    assert env["is_windows"] == platform.system().lower().startswith("win")


def test_environment_prompt_block_has_header_and_shell():
    block = environment_prompt_block(refresh=True)
    assert block.startswith("[ENVIRONMENT]")
    assert "shell:" in block
    if detect_environment()["is_windows"]:
        assert "mkdir -p" in block  # Windows guidance is present


# ── compat: mkdir / touch ───────────────────────────────────────────


def test_mkdir_creates_nested_dir(tmp_path):
    out = try_compat_command("mkdir -p a/b/c", ".", _ctx(tmp_path))
    assert out is not None and "exit code: 0" in out
    assert (tmp_path / "a" / "b" / "c").is_dir()


def test_touch_creates_file(tmp_path):
    out = try_compat_command("touch notes.txt", ".", _ctx(tmp_path))
    assert out is not None and "exit code: 0" in out
    assert (tmp_path / "notes.txt").is_file()


# ── compat: rm guards ───────────────────────────────────────────────


def test_rm_file_and_dir(tmp_path):
    (tmp_path / "f.txt").write_text("x", encoding="utf-8")
    (tmp_path / "d").mkdir()
    (tmp_path / "d" / "inner.txt").write_text("y", encoding="utf-8")
    assert "exit code: 0" in try_compat_command("rm f.txt", ".", _ctx(tmp_path))
    assert not (tmp_path / "f.txt").exists()
    # Dir without -r is refused.
    refused = try_compat_command("rm d", ".", _ctx(tmp_path))
    assert "is a directory" in refused
    assert (tmp_path / "d").exists()
    # With -r it succeeds.
    assert "exit code: 0" in try_compat_command("rm -rf d", ".", _ctx(tmp_path))
    assert not (tmp_path / "d").exists()


def test_rm_refuses_drive_root(tmp_path):
    anchor = Path(tmp_path).anchor or "/"
    out = try_compat_command(f"rm -rf {anchor}", ".", _ctx(tmp_path))
    assert "refused dangerous path" in out


# ── compat: ls / cat / echo ─────────────────────────────────────────


def test_ls_lists_entries(tmp_path):
    (tmp_path / "one.txt").write_text("1", encoding="utf-8")
    (tmp_path / "sub").mkdir()
    out = try_compat_command("ls", ".", _ctx(tmp_path))
    assert "one.txt" in out and "sub" in out


def test_cat_reads_file(tmp_path):
    (tmp_path / "r.txt").write_text("hello world", encoding="utf-8")
    out = try_compat_command("cat r.txt", ".", _ctx(tmp_path))
    assert "hello world" in out


def test_echo_redirect_writes_and_appends(tmp_path):
    try_compat_command('echo "line one" > log.txt', ".", _ctx(tmp_path))
    try_compat_command('echo "line two" >> log.txt', ".", _ctx(tmp_path))
    content = (tmp_path / "log.txt").read_text(encoding="utf-8")
    assert "line one" in content and "line two" in content


def test_plain_echo_without_redirect_falls_through(tmp_path):
    # No redirect => not handled => fall through to the real shell.
    assert try_compat_command("echo hi", ".", _ctx(tmp_path)) is None


# ── compat: py_compile ──────────────────────────────────────────────


def test_py_compile_passes_and_fails(tmp_path):
    good = tmp_path / "good.py"
    good.write_text("x = 1\n", encoding="utf-8")
    assert "passed" in try_compat_command("python -m py_compile good.py", ".", _ctx(tmp_path))
    bad = tmp_path / "bad.py"
    bad.write_text("def (:\n", encoding="utf-8")
    assert "failed" in try_compat_command("python -m py_compile bad.py", ".", _ctx(tmp_path))


# ── compat: fall-through ────────────────────────────────────────────


def test_composition_falls_through(tmp_path):
    assert try_compat_command("ls | sort", ".", _ctx(tmp_path)) is None


def test_unknown_verb_falls_through(tmp_path):
    assert try_compat_command("npm run build", ".", _ctx(tmp_path)) is None


def test_run_command_routes_mkdir_through_compat(tmp_path):
    from augment.tools.commands import run_command
    out = run_command("mkdir -p built/here", ".", _context=_ctx(tmp_path))
    assert "exit code: 0" in out
    assert (tmp_path / "built" / "here").is_dir()
