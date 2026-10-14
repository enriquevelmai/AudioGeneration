"""Registers the podcast-tts MCP server in AI assistants (idempotent).

- **Claude Code**: installs the skill (scripts/install_skill.ps1) and registers the MCP with
  ``claude mcp add --scope user podcast-tts -- <python> -m podcast_tts mcp``.
- **Claude Desktop**: adds ``podcast-tts`` to ``mcpServers`` in ``claude_desktop_config.json``
  (merges without deleting other entries and leaves a ``.bak`` copy before writing).
- **Other clients** (Cursor, VS Code, Windsurf...): prints the JSON ready to paste.

First it checks that the ``mcp`` extra is installed (if missing, ``uv sync`` with the same
extras as ``.venv\\podcast-tts-extras.txt`` plus ``mcp``).

Usage (normally through ``bats\\install_integrations.bat``)::

    python scripts/install_integrations.py                 # interactive: detects and asks
    python scripts/install_integrations.py /y              # everything detected, no questions
    python scripts/install_integrations.py /claude-code    # Claude Code only
    python scripts/install_integrations.py /claude-desktop # Claude Desktop only
    python scripts/install_integrations.py /print          # only prints the JSON
    python scripts/install_integrations.py --uninstall     # removes the registration (not the skill)

Testing without touching the real configuration::

    python scripts/install_integrations.py /claude-desktop --config-path C:\\tmp\\cfg.json
    python scripts/install_integrations.py /claude-code --dry-run

Uses the standard library only.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable, Sequence

SERVER_NAME = "podcast-tts"
ROOT = Path(__file__).resolve().parents[1]
ENV = {"PYTHONUTF8": "1", "COQUI_TOS_AGREED": "1"}

Runner = Callable[[Sequence[str]], "subprocess.CompletedProcess[str]"]


def say(msg: str = "") -> None:
    print(msg, flush=True)


# --------------------------------------------------------------------------- #
# Paths
# --------------------------------------------------------------------------- #


def venv_python(root: Path = ROOT) -> Path:
    if os.name == "nt":
        return root / ".venv" / "Scripts" / "python.exe"
    return root / ".venv" / "bin" / "python"


def server_entry(python: Path, root: Path = ROOT) -> dict[str, Any]:
    """``mcpServers`` entry (Claude Desktop and Cursor format)."""
    return {
        "command": str(python),
        "args": ["-m", "podcast_tts", "mcp"],
        # PYTHONPATH=<repo>\src: same as the bats and the launcher, so that it works even if the
        # project path contains accents (uv's editable .pth fails in that case).
        "env": {"PYTHONPATH": str(root / "src"), **ENV},
    }


def desktop_config_paths() -> list[Path]:
    """Claude Desktop configuration files on this machine (the first one is the standard one).

    Includes the virtualized location of the Microsoft Store (MSIX) version if it exists.
    """
    paths: list[Path] = []
    if os.name == "nt":
        appdata = os.environ.get("APPDATA")
        if appdata:
            paths.append(Path(appdata) / "Claude" / "claude_desktop_config.json")
        local = os.environ.get("LOCALAPPDATA")
        if local:
            packages = Path(local) / "Packages"
            if packages.is_dir():
                for pkg in sorted(packages.glob("Claude_*")):
                    paths.append(pkg / "LocalCache" / "Roaming" / "Claude"
                                 / "claude_desktop_config.json")
    elif sys.platform == "darwin":
        paths.append(Path.home() / "Library" / "Application Support" / "Claude"
                     / "claude_desktop_config.json")
    else:
        paths.append(Path.home() / ".config" / "Claude" / "claude_desktop_config.json")
    return paths


def claude_desktop_installed() -> bool:
    return any(p.parent.is_dir() for p in desktop_config_paths())


def find_claude_cli() -> str | None:
    return shutil.which("claude")


def find_uv() -> str | None:
    found = shutil.which("uv")
    if found:
        return found
    candidate = Path.home() / ".local" / "bin" / ("uv.exe" if os.name == "nt" else "uv")
    return str(candidate) if candidate.is_file() else None


# --------------------------------------------------------------------------- #
# Claude Desktop (JSON merge)
# --------------------------------------------------------------------------- #


class ConfigError(RuntimeError):
    pass


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    text = path.read_text(encoding="utf-8-sig")
    if not text.strip():
        return {}
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{path} is not valid JSON ({exc}); it is left unchanged. "
                          "Fix it by hand or delete it and run again.") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"{path} does not contain a JSON object; it is left unchanged.")
    return data


def _write_json(path: Path, data: dict[str, Any]) -> Path | None:
    """Writes ``data`` (with a prior ``.bak`` copy if the file existed). Returns the backup."""
    backup = None
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        backup = path.with_name(path.name + ".bak")
        shutil.copy2(path, backup)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return backup


def merge_desktop_config(path: Path, entry: dict[str, Any], *, uninstall: bool = False,
                         dry_run: bool = False) -> str:
    """Adds (or removes) ``podcast-tts`` in ``mcpServers`` without touching the rest.

    Returns ``"added"``, ``"updated"``, ``"unchanged"``, ``"removed"`` or ``"absent"``.
    """
    data = _read_json(path)
    servers = data.get("mcpServers")
    if servers is None:
        servers = {}
    if not isinstance(servers, dict):
        raise ConfigError(f"'mcpServers' in {path} is not an object; it is left unchanged.")
    current = servers.get(SERVER_NAME)
    if uninstall:
        if current is None:
            return "absent"
        status = "removed"
        new_servers = {k: v for k, v in servers.items() if k != SERVER_NAME}
    else:
        if current == entry:
            return "unchanged"
        status = "updated" if current is not None else "added"
        new_servers = {**servers, SERVER_NAME: entry}
    if not dry_run:
        _write_json(path, {**data, "mcpServers": new_servers})
    return status


def install_claude_desktop(entry: dict[str, Any], paths: list[Path], *, uninstall: bool,
                           dry_run: bool) -> bool:
    ok = True
    for path in paths:
        try:
            status = merge_desktop_config(path, entry, uninstall=uninstall, dry_run=dry_run)
        except (ConfigError, OSError) as exc:
            say(f"  ERROR: {exc}")
            ok = False
            continue
        prefix = "[dry run] " if dry_run else ""
        messages = {
            "added": "added podcast-tts",
            "updated": "updated the podcast-tts entry",
            "unchanged": "already configured (no changes)",
            "removed": "removed the podcast-tts entry",
            "absent": "there was no podcast-tts entry (nothing to remove)",
        }
        say(f"  {prefix}{path}: {messages[status]}")
        if status in ("added", "updated", "removed") and not dry_run:
            bak = path.with_name(path.name + ".bak")
            if bak.exists():
                say(f"  Backup: {bak}")
    if ok and not dry_run:
        say("  Restart Claude Desktop (also quit it from the system tray) so that "
            "it loads the server.")
    return ok


# --------------------------------------------------------------------------- #
# Claude Code
# --------------------------------------------------------------------------- #


def _run(cmd: Sequence[str]) -> "subprocess.CompletedProcess[str]":
    return subprocess.run(list(cmd), capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=120)


def claude_code_commands(claude: str, python: Path, *, uninstall: bool) -> list[list[str]]:
    if uninstall:
        return [[claude, "mcp", "remove", "--scope", "user", SERVER_NAME]]
    # The -e options go after the name: --env is variadic and, placed before, it would swallow the name.
    env: list[str] = []
    for key, value in server_entry(python)["env"].items():
        env += ["-e", f"{key}={value}"]
    return [[claude, "mcp", "add", "--scope", "user", SERVER_NAME, *env, "--",
             str(python), "-m", "podcast_tts", "mcp"]]


def install_claude_code(python: Path, *, uninstall: bool, dry_run: bool,
                        noninteractive: bool, skill: bool = True,
                        claude: str | None = None, runner: Runner = _run) -> bool:
    ok = True
    if skill and not uninstall and os.name == "nt":
        cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
               str(ROOT / "scripts" / "install_skill.ps1")]
        if noninteractive:
            cmd.append("-NoReplace")
        if dry_run:
            say(f"  [dry run] {subprocess.list2cmdline(cmd)}")
        else:
            res = runner(cmd)
            out = (res.stdout or "").strip() or (res.stderr or "").strip()
            say(f"  Skill: {out}" if out else "  Skill installed.")
            if res.returncode != 0:
                say("  WARNING: could not install the skill (see above).")
                ok = False
    claude = claude or find_claude_cli()
    if not claude:
        say("  The 'claude' CLI was not found on the PATH: skipping the MCP registration.")
        say("  Once you have it: "
            + subprocess.list2cmdline(claude_code_commands("claude", python, uninstall=False)[0]))
        return ok
    if dry_run:
        for cmd in claude_code_commands(claude, python, uninstall=uninstall):
            say(f"  [dry run] {subprocess.list2cmdline(cmd)}")
        return ok
    current = runner([claude, "mcp", "get", SERVER_NAME])
    exists = current.returncode == 0
    if uninstall:
        if not exists:
            say("  Claude Code: there was no podcast-tts server (nothing to remove).")
            return ok
    elif exists:
        if str(python).lower() in (current.stdout or "").lower():
            say("  Claude Code: podcast-tts was already registered (no changes).")
            return ok
        say("  Claude Code: podcast-tts points to another installation; registering it again.")
        runner([claude, "mcp", "remove", "--scope", "user", SERVER_NAME])
    for cmd in claude_code_commands(claude, python, uninstall=uninstall):
        res = runner(cmd)
        out = ((res.stdout or "") + (res.stderr or "")).strip()
        if res.returncode != 0:
            say(f"  ERROR ({res.returncode}): {out}")
            return False
        say(f"  Claude Code: {out or 'done'}")
    return ok


# --------------------------------------------------------------------------- #
# mcp extra and check
# --------------------------------------------------------------------------- #


def mcp_installed(python: Path) -> bool:
    res = subprocess.run([str(python), "-c", "import mcp.server.fastmcp"],
                         capture_output=True, text=True)
    return res.returncode == 0


def read_extras(root: Path = ROOT) -> list[str]:
    path = root / ".venv" / "podcast-tts-extras.txt"
    try:
        extras = path.read_text(encoding="utf-8", errors="replace").split()
    except OSError:
        extras = []
    if not extras:
        variant = "cuda" if shutil.which("nvidia-smi") else "cpu"
        extras = ["local", variant, "desktop", "dev"]
    return extras


def ensure_mcp_extra(python: Path, *, dry_run: bool, root: Path = ROOT) -> bool:
    if python.is_file() and mcp_installed(python):
        say("  The mcp extra is already installed.")
        return True
    extras = read_extras(root)
    if "mcp" not in extras:
        extras.append("mcp")
    uv = find_uv()
    if not uv:
        say("  ERROR: uv not found. Run bats\\install.bat first.")
        return False
    cmd = [uv, "sync", "--locked", "--python", "3.11"]
    for e in extras:
        cmd += ["--extra", e]
    if dry_run:
        say(f"  [dry run] {subprocess.list2cmdline(cmd)}")
        return True
    say(f"  Installing the mcp extra (extras: {' '.join(extras)})...")
    res = subprocess.run(cmd, cwd=str(root))
    if res.returncode != 0:
        say("  ERROR in uv sync (see above).")
        return False
    fix = root / "scripts" / "fix_editable_pth.py"
    if fix.is_file() and python.is_file():
        subprocess.run([str(python), "-I", "-S", str(fix)], cwd=str(root))
    try:
        (root / ".venv" / "podcast-tts-extras.txt").write_text(" ".join(extras) + "\n",
                                                               encoding="utf-8")
    except OSError:
        pass
    return True


CHECK_CODE = r"""
import asyncio, sys
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
async def main():
    p = StdioServerParameters(command=sys.executable, args=["-m", "podcast_tts", "mcp"])
    async with stdio_client(p) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            tools = await s.list_tools()
            print(len(tools.tools))
asyncio.run(main())
"""


def check_server(python: Path) -> bool:
    """Starts the server the way a client would and counts its tools."""
    started = time.perf_counter()
    try:
        res = subprocess.run([str(python), "-c", CHECK_CODE], capture_output=True, text=True,
                             timeout=120, cwd=str(Path.home()),
                             env={**os.environ, **server_entry(python)["env"]})
    except subprocess.TimeoutExpired:
        say("  ERROR: the server did not respond within 120 s.")
        return False
    if res.returncode != 0:
        say("  ERROR: the MCP server does not start:")
        say("  " + (res.stderr or "").strip().replace("\n", "\n  ")[-2000:])
        return False
    say(f"  MCP server OK: {res.stdout.strip()} tools "
        f"({time.perf_counter() - started:.1f} s).")
    return True


# --------------------------------------------------------------------------- #
# JSON for other clients
# --------------------------------------------------------------------------- #


def other_clients_text(entry: dict[str, Any]) -> str:
    desktop = json.dumps({"mcpServers": {SERVER_NAME: entry}}, indent=2, ensure_ascii=False)
    vscode = json.dumps({"servers": {SERVER_NAME: {"type": "stdio", **entry}}}, indent=2,
                        ensure_ascii=False)
    cli = subprocess.list2cmdline([entry["command"], *entry["args"]])
    return f"""Claude Desktop, Cursor (~/.cursor/mcp.json or .cursor/mcp.json), Windsurf and most
clients ("mcpServers" key):

{desktop}

VS Code (.vscode/mcp.json or "MCP: Open User Configuration"; "servers" key):

{vscode}

Server command (stdio), for any other client: {cli}
Environment variables: {", ".join(f"{k}={v}" for k, v in entry["env"].items())}.
Default output: {ROOT / 'output'} (change it with the PODCAST_TTS_OUTPUT_DIR variable)."""


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #


def ask(question: str) -> bool:
    try:
        answer = input(f"  {question}? [Y/n] ").strip().lower()
    except EOFError:
        return True
    return answer not in ("n", "no")


# The .bat files use Windows-style options (/y, /print...). Only these exact words are
# translated: a general "/" prefix would confuse POSIX paths (/tmp/x.json) with options.
SLASH_FLAGS = {"/y": "--yes", "/claude-code": "--claude-code", "/claude-desktop": "--claude-desktop",
               "/print": "--print", "/uninstall": "--uninstall"}


def normalize_argv(argv: Sequence[str]) -> list[str]:
    return [SLASH_FLAGS.get(a.lower(), a) for a in argv]


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="install_integrations",
        description="Registers the podcast-tts MCP server in Claude Code, Claude Desktop and "
                    "other MCP clients (idempotent).")
    p.add_argument("-y", "--yes", dest="yes", action="store_true",
                   help="no questions: configures everything detected")
    p.add_argument("--claude-code", dest="claude_code", action="store_true",
                   help="Claude Code only (skill + claude mcp add)")
    p.add_argument("--claude-desktop", dest="claude_desktop",
                   action="store_true", help="Claude Desktop only (claude_desktop_config.json)")
    p.add_argument("--print", dest="print_only", action="store_true",
                   help="only prints the JSON to paste into other clients")
    p.add_argument("--uninstall", dest="uninstall", action="store_true",
                   help="removes the podcast-tts registration (does not delete the skill)")
    p.add_argument("--config-path", action="append", default=None, metavar="FILE",
                   help="claude_desktop_config.json to use (for testing; repeatable)")
    p.add_argument("--dry-run", action="store_true",
                   help="does not run claude or uv nor write the configuration: shows what it would do")
    p.add_argument("--no-skill", action="store_true", help="does not install the Claude Code skill")
    p.add_argument("--no-check", action="store_true",
                   help="does not start the server to check it")
    p.add_argument("--python", default=None, help=argparse.SUPPRESS)
    return p


def main(argv: Sequence[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        except (AttributeError, ValueError):
            pass
    args = build_parser().parse_args(normalize_argv(sys.argv[1:] if argv is None else argv))
    python = Path(args.python) if args.python else venv_python()
    entry = server_entry(python)
    say("=" * 68)
    say(f" podcast-tts - integrations with AI assistants (MCP)")
    say(f" Project: {ROOT}")
    say("=" * 68)

    if args.print_only:
        say(other_clients_text(entry))
        return 0
    if not args.dry_run and not python.is_file():
        say(f"ERROR: {python} does not exist. Run bats\\install.bat first.")
        return 1

    explicit = args.claude_code or args.claude_desktop
    noninteractive = args.yes or explicit or args.uninstall
    desktop_paths = [Path(p) for p in args.config_path] if args.config_path else None
    cli = find_claude_cli()
    has_code = cli is not None or (Path.home() / ".claude").is_dir()
    has_desktop = bool(desktop_paths) or claude_desktop_installed()

    def wanted(flag: bool, detected: bool, label: str) -> bool:
        if explicit:
            return flag
        if not detected:
            say(f"\n{label}: not detected, skipped.")
            return False
        return True if noninteractive else ask(f"Configure {label}")

    do_code = wanted(args.claude_code, has_code, "Claude Code")
    do_desktop = wanted(args.claude_desktop, has_desktop, "Claude Desktop")
    ok = True

    if not args.uninstall:
        say("\n[1] MCP server dependencies")
        ok = ensure_mcp_extra(python, dry_run=args.dry_run) and ok
        if ok and not args.dry_run and not args.no_check:
            ok = check_server(python) and ok

    if do_code:
        say("\n[2] Claude Code")
        ok = install_claude_code(python, uninstall=args.uninstall, dry_run=args.dry_run,
                                 noninteractive=noninteractive,
                                 skill=not args.no_skill) and ok
    if do_desktop:
        say("\n[3] Claude Desktop")
        paths = desktop_paths or [p for p in desktop_config_paths() if p.parent.is_dir()] \
            or desktop_config_paths()[:1]
        ok = install_claude_desktop(entry, paths, uninstall=args.uninstall,
                                    dry_run=args.dry_run) and ok

    if not args.uninstall and not explicit:
        say("\n[4] Other clients (Cursor, VS Code...): paste this into their MCP configuration")
        say(other_clients_text(entry))
    say("")
    if not args.uninstall:
        say('Try it: open your assistant and ask "make me a 3-minute podcast about the history '
            'of coffee". More information: docs/MCP.md')
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
