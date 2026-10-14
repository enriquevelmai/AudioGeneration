"""scripts/install_integrations.py con ficheros y comandos falsos (no toca la configuración real)."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def ii() -> Any:
    spec = importlib.util.spec_from_file_location(
        "install_integrations", ROOT / "scripts" / "install_integrations.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


def _entry(ii: Any) -> dict[str, Any]:
    return ii.server_entry(Path("C:/proyecto/.venv/Scripts/python.exe"), Path("C:/proyecto"))


def test_entry_has_env(ii: Any) -> None:
    e = _entry(ii)
    assert e["args"] == ["-m", "podcast_tts", "mcp"]
    assert e["env"]["PYTHONPATH"].endswith("src")
    assert e["env"]["PYTHONUTF8"] == "1" and e["env"]["COQUI_TOS_AGREED"] == "1"


def test_merge_keeps_other_entries_and_backs_up(ii: Any, tmp_path: Path) -> None:
    cfg = tmp_path / "claude_desktop_config.json"
    original = {"mcpServers": {"otro": {"command": "x"}}, "globalShortcut": "Ctrl+Space"}
    cfg.write_text(json.dumps(original), encoding="utf-8")
    entry = _entry(ii)

    assert ii.merge_desktop_config(cfg, entry) == "added"
    data = json.loads(cfg.read_text(encoding="utf-8"))
    assert data["mcpServers"]["otro"] == {"command": "x"}
    assert data["mcpServers"]["podcast-tts"] == entry
    assert data["globalShortcut"] == "Ctrl+Space"
    backup = cfg.with_name(cfg.name + ".bak")
    assert json.loads(backup.read_text(encoding="utf-8")) == original

    # idempotente: sin cambios y sin reescribir
    mtime = cfg.stat().st_mtime_ns
    assert ii.merge_desktop_config(cfg, entry) == "unchanged"
    assert cfg.stat().st_mtime_ns == mtime

    changed = {**entry, "args": ["-m", "podcast_tts", "mcp", "--output-dir", "D:/x"]}
    assert ii.merge_desktop_config(cfg, changed) == "updated"

    assert ii.merge_desktop_config(cfg, entry, uninstall=True) == "removed"
    data = json.loads(cfg.read_text(encoding="utf-8"))
    assert "podcast-tts" not in data["mcpServers"] and "otro" in data["mcpServers"]
    assert ii.merge_desktop_config(cfg, entry, uninstall=True) == "absent"


def test_merge_new_file_and_dry_run(ii: Any, tmp_path: Path) -> None:
    cfg = tmp_path / "sub" / "claude_desktop_config.json"
    assert ii.merge_desktop_config(cfg, _entry(ii), dry_run=True) == "added"
    assert not cfg.exists()
    assert ii.merge_desktop_config(cfg, _entry(ii)) == "added"
    assert not cfg.with_name(cfg.name + ".bak").exists()  # no había nada que copiar
    assert "podcast-tts" in json.loads(cfg.read_text(encoding="utf-8"))["mcpServers"]


def test_invalid_json_is_not_overwritten(ii: Any, tmp_path: Path) -> None:
    cfg = tmp_path / "claude_desktop_config.json"
    cfg.write_text("{ esto no es json", encoding="utf-8")
    with pytest.raises(ii.ConfigError):
        ii.merge_desktop_config(cfg, _entry(ii))
    assert cfg.read_text(encoding="utf-8") == "{ esto no es json"


def test_main_with_config_path(ii: Any, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    cfg = tmp_path / "cfg.json"
    cfg.write_text('{"mcpServers": {}}', encoding="utf-8")
    rc = ii.main(["/claude-desktop", "--config-path", str(cfg), "--no-check",
                  "--python", sys.executable])
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "podcast-tts" in json.loads(cfg.read_text(encoding="utf-8"))["mcpServers"]
    rc = ii.main(["--claude-desktop", "--config-path", str(cfg), "--no-check", "--uninstall",
                  "--python", sys.executable])
    assert rc == 0
    assert json.loads(cfg.read_text(encoding="utf-8"))["mcpServers"] == {}


def test_print_outputs_json_blocks(ii: Any, capsys: pytest.CaptureFixture) -> None:
    assert ii.main(["/print"]) == 0
    out = capsys.readouterr().out
    assert '"mcpServers"' in out and '"servers"' in out and '"type": "stdio"' in out
    assert "podcast_tts" in out


class FakeClaude:
    def __init__(self, existing: str | None = None) -> None:
        self.calls: list[list[str]] = []
        self.existing = existing

    def __call__(self, cmd: Any) -> subprocess.CompletedProcess:
        cmd = list(cmd)
        self.calls.append(cmd)
        if cmd[1:3] == ["mcp", "get"]:
            if self.existing is None:
                return subprocess.CompletedProcess(cmd, 1, "", "not found")
            return subprocess.CompletedProcess(cmd, 0, self.existing, "")
        return subprocess.CompletedProcess(cmd, 0, "ok", "")


def test_claude_code_add_and_idempotent(ii: Any) -> None:
    py = Path("C:/proyecto/.venv/Scripts/python.exe")
    fake = FakeClaude()
    assert ii.install_claude_code(py, uninstall=False, dry_run=False, noninteractive=True,
                                  skill=False, claude="claude", runner=fake)
    add = fake.calls[-1]
    assert add[:6] == ["claude", "mcp", "add", "--scope", "user", "podcast-tts"]
    sep = add.index("--")
    assert add[sep + 1:] == [str(py), "-m", "podcast_tts", "mcp"]
    assert "-e" in add[:sep] and "PYTHONUTF8=1" in add[:sep]

    already = FakeClaude(existing=f"Command: {py}\nArgs: -m podcast_tts mcp")
    assert ii.install_claude_code(py, uninstall=False, dry_run=False, noninteractive=True,
                                  skill=False, claude="claude", runner=already)
    assert [c[2] for c in already.calls] == ["get"]

    other = FakeClaude(existing="Command: D:\\otro\\python.exe")
    ii.install_claude_code(py, uninstall=False, dry_run=False, noninteractive=True,
                           skill=False, claude="claude", runner=other)
    assert [c[2] for c in other.calls] == ["get", "remove", "add"]


def test_claude_code_dry_run_runs_nothing(ii: Any, capsys: pytest.CaptureFixture) -> None:
    fake = FakeClaude()
    ii.install_claude_code(Path("C:/p/python.exe"), uninstall=False, dry_run=True,
                           noninteractive=True, claude="claude", runner=fake)
    assert fake.calls == []
    out = capsys.readouterr().out
    assert "[simulación]" in out and "mcp add --scope user podcast-tts" in out
