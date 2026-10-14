"""MCP server: ``python -m podcast_tts mcp`` is started as a subprocess and driven with the
official SDK client (``ClientSession`` + ``stdio_client``), just like an assistant would."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from conftest import requires_ffmpeg

pytest.importorskip("mcp")

from mcp import ClientSession, StdioServerParameters  # noqa: E402
from mcp.client.stdio import stdio_client  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]

EXPECTED_TOOLS = {
    "list_voices", "list_engines", "get_script_format", "validate_script", "generate_podcast",
    "generate_podcast_from_file", "get_generation_status", "synthesize_text", "add_voice",
    "list_outputs", "open_output_folder",
}

SCRIPT_OK = """---
title: Prueba MCP
---

[voz:ana]
Hola y bienvenidos a esta prueba.

[voz:carlos]
Gracias, Ana. [pausa:0.5] Esto es todo.
"""


def _env(tmp: Path) -> dict[str, str]:
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONPATH": str(ROOT / "src"),
           "PODCAST_TTS_SCRIPTS_DIR": str(tmp / "guiones"),
           "COQUI_TOS_AGREED": "1"}
    # F5-TTS's seed_everything() writes os.environ["PYTHONHASHSEED"] = str(seed) with seeds
    # above 2**32 when the real-engine tests run first; a child Python refuses to start then.
    env.pop("PYTHONHASHSEED", None)
    return env


def _params(tmp: Path) -> StdioServerParameters:
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "podcast_tts", "mcp", "--output-dir", str(tmp / "out")],
        env=_env(tmp), cwd=str(tmp))


def run_client(tmp: Path, body: Any) -> Any:
    async def main() -> Any:
        async with stdio_client(_params(tmp)) as (r, w):
            async with ClientSession(r, w) as session:
                await session.initialize()
                return await body(session)

    return asyncio.run(main())


def _json(result: Any) -> Any:
    assert not result.isError, result.content[0].text
    return json.loads(result.content[0].text)


# --------------------------------------------------------------------------- #


def test_list_tools_prompt_and_format(tmp_path: Path) -> None:
    async def body(s: ClientSession) -> Any:
        tools = await s.list_tools()
        prompts = await s.list_prompts()
        prompt = await s.get_prompt("podcast", {"topic": "la historia del café",
                                                 "voices": "ana, carlos", "minutes": "3"})
        fmt = await s.call_tool("get_script_format", {})
        voices = await s.call_tool("list_voices", {})
        engines = await s.call_tool("list_engines", {})
        return tools, prompts, prompt, fmt, voices, engines

    tools, prompts, prompt, fmt, voices, engines = run_client(tmp_path, body)
    names = {t.name for t in tools.tools}
    assert EXPECTED_TOOLS <= names
    for t in tools.tools:
        assert t.description and len(t.description) > 40, t.name
        assert "ctx" not in t.inputSchema.get("properties", {}), t.name
    assert [p.name for p in prompts.prompts] == ["podcast"]
    text = prompt.messages[0].content.text
    assert "la historia del café" in text and "450" in text and "validate_script" in text
    guide = fmt.content[0].text
    assert "[voice:" in guide and "[voz:" in guide  # English tags + Spanish aliases
    assert "150" in guide and "Front matter" in guide
    vs = {v["name"]: v for v in _json(voices)["voices"]}
    assert {"ana", "carlos"} <= set(vs)
    assert vs["ana"]["lang"] == "es" and vs["ana"]["cloud"] is False
    eng = {e["name"]: e for e in _json(engines)["engines"]}
    assert eng["f5"]["commercial_use"] is False
    assert eng["dummy"]["ready"] is True
    assert eng["openai"]["kind"] == "cloud"


def test_validate_script_reports_lines(tmp_path: Path) -> None:
    async def body(s: ClientSession) -> Any:
        ok = await s.call_tool("validate_script", {"script": SCRIPT_OK})
        bad_tag = await s.call_tool("validate_script",
                                    {"script": "[voz:ana]\nHola.\n[pausaa:1]\n"})
        bad_voice = await s.call_tool("validate_script",
                                      {"script": "[voz:ana]\nHola.\n\n[voz:inventada]\nAdiós.\n"})
        bad_media = await s.call_tool(
            "validate_script", {"script": "[musica:../../secreto.mp3]\n[sfx:C:/x/y.wav]\n"
                                          "[voz:ana] Hola.\n[musica:no_existe.mp3]\n"})
        return ok, bad_tag, bad_voice, bad_media

    ok, bad_tag, bad_voice, bad_media = map(_json, run_client(tmp_path, body))
    assert ok["valid"] is True and ok["errors"] == []
    assert ok["missing_voices"] == []
    assert {v["name"] for v in ok["voices_used"]} == {"ana", "carlos"}
    assert ok["title"] == "Prueba MCP"
    assert 1 < ok["estimated_duration_seconds"] < 15
    assert "f5" in ok["engines"] and ok["license_notice"]
    assert bad_tag["valid"] is False and bad_tag["errors"][0]["line"] == 3
    assert bad_voice["valid"] is False and bad_voice["missing_voices"] == ["inventada"]
    assert bad_voice["errors"][0]["line"] == 5  # first text line of that voice
    lines = sorted(e["line"] for e in bad_media["errors"])
    assert lines == [1, 2, 4]


@requires_ffmpeg
def test_generate_podcast_dummy_progress_and_files(tmp_path: Path) -> None:
    progress: list[tuple[float, float | None, str | None]] = []

    async def on_progress(p: float, total: float | None, msg: str | None) -> None:
        progress.append((p, total, msg))

    async def body(s: ClientSession) -> Any:
        gen = await s.call_tool("generate_podcast",
                                {"script": SCRIPT_OK, "output_name": "prueba", "engine": "dummy"},
                                progress_callback=on_progress)
        again = await s.call_tool("generate_podcast",
                                  {"script": SCRIPT_OK, "output_name": "prueba.mp3",
                                   "engine": "dummy", "format": "wav", "save_script": False})
        traversal = await s.call_tool("generate_podcast",
                                      {"script": SCRIPT_OK, "output_name": "../fuera",
                                       "engine": "dummy"})
        invalid = await s.call_tool("generate_podcast",
                                    {"script": "[voz:ana]\n[foo:1]", "output_name": "x",
                                     "engine": "dummy"})
        tts = await s.call_tool("synthesize_text", {"text": "Hola, esto es una frase.",
                                                    "voice": "ana", "engine": "dummy"})
        outs = await s.call_tool("list_outputs", {})
        return gen, again, traversal, invalid, tts, outs

    gen, again, traversal, invalid, tts, outs = run_client(tmp_path, body)
    g = _json(gen)
    assert g["status"] == "done"
    out = Path(g["output_path"])
    assert out.is_file() and out.parent == (tmp_path / "out").resolve()
    assert out.name == "prueba.mp3"
    assert 1.0 < g["duration_seconds"] < 30 and g["generation_seconds"] >= 0
    assert "license_notice" not in g  # dummy is not a non-commercial engine
    assert Path(g["script_path"]).read_text(encoding="utf-8") == SCRIPT_OK
    # progress per segment, strictly increasing, ending at the total
    values = [p for p, _, _ in progress]
    assert len(progress) >= 5 and values == sorted(set(values))
    assert progress[-1][0] == progress[-1][1]
    # the per-segment message comes from the assembler ("Synthesizing [carlos] ..."); only the
    # voice name is checked so the test does not depend on that message's language
    assert any("[carlos]" in (m or "") for _, _, m in progress)
    a = _json(again)
    assert Path(a["output_path"]).name == "prueba.wav"
    assert traversal.isError and "output_name" in traversal.content[0].text
    assert invalid.isError and "line 2" in invalid.content[0].text
    assert Path(_json(tts)["output_path"]).name == "tts_ana.mp3"
    names = {f["name"] for f in _json(outs)["files"]}
    assert {"prueba.mp3", "prueba.wav", "tts_ana.mp3"} <= names
    assert not (tmp_path / "fuera.mp3").exists()


@requires_ffmpeg
def test_generate_from_file_and_job_polling(tmp_path: Path) -> None:
    script = tmp_path / "episodio.md"
    script.write_text(SCRIPT_OK, encoding="utf-8")

    async def body(s: ClientSession) -> Any:
        first = await s.call_tool("generate_podcast_from_file",
                                  {"path": str(script), "engine": "dummy", "wait_seconds": 0})
        data = _json(first)
        while data["status"] == "running":
            data = _json(await s.call_tool("get_generation_status",
                                           {"job_id": data["job_id"], "wait_seconds": 10}))
        unknown = await s.call_tool("get_generation_status", {"job_id": "nope"})
        return _json(first), data, unknown

    first, final, unknown = run_client(tmp_path, body)
    assert first["status"] in ("running", "done")
    assert final["status"] == "done"
    assert Path(final["output_path"]).name == "episodio.mp3"
    assert unknown.isError


def _raw_session(tmp: Path, calls: list[dict[str, Any]], timeout: float = 120) -> list[str]:
    """Speak JSON-RPC "by hand" and return ALL the lines the server wrote to stdout."""
    msgs: list[dict[str, Any]] = [
        {"jsonrpc": "2.0", "id": 0, "method": "initialize",
         "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                    "clientInfo": {"name": "test", "version": "0"}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
    ]
    for i, (call) in enumerate(calls, start=1):
        msgs.append({"jsonrpc": "2.0", "id": i, "method": "tools/call",
                     "params": {**call, "_meta": {"progressToken": i}}})
    proc = subprocess.Popen(
        [sys.executable, "-m", "podcast_tts", "mcp", "--output-dir", str(tmp / "out")],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        env=_env(tmp), cwd=str(tmp))
    assert proc.stdin and proc.stdout
    lines: list[str] = []
    try:
        for m in msgs[:2]:
            proc.stdin.write((json.dumps(m) + "\n").encode())
        proc.stdin.flush()
        lines.append(proc.stdout.readline().decode("utf-8"))
        pending = {m["id"] for m in msgs[2:]}
        for m in msgs[2:]:
            proc.stdin.write((json.dumps(m) + "\n").encode())
            proc.stdin.flush()
        while pending:
            line = proc.stdout.readline().decode("utf-8")
            if not line:
                break
            lines.append(line)
            try:
                pending.discard(json.loads(line).get("id"))
            except ValueError:
                pass
    finally:
        proc.stdin.close()
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
        rest = proc.stdout.read().decode("utf-8")
        lines += [ln for ln in rest.splitlines(keepends=True) if ln]
    return lines


def _assert_clean(lines: list[str]) -> list[dict[str, Any]]:
    parsed = []
    for line in lines:
        assert line.endswith("\n"), repr(line)
        parsed.append(json.loads(line))  # any library "print" would break this
        assert parsed[-1]["jsonrpc"] == "2.0"
    return parsed


@requires_ffmpeg
def test_stdout_only_has_protocol(tmp_path: Path) -> None:
    lines = _raw_session(tmp_path, [
        {"name": "validate_script", "arguments": {"script": SCRIPT_OK}},
        {"name": "generate_podcast", "arguments": {"script": SCRIPT_OK, "output_name": "raw",
                                                   "engine": "dummy"}},
    ])
    parsed = _assert_clean(lines)
    assert any(p.get("method") == "notifications/progress" for p in parsed)
    assert any(p.get("id") == 2 and "result" in p for p in parsed)


def test_protect_stdio_redirects_prints_and_subprocesses(tmp_path: Path) -> None:
    code = (
        "import os, subprocess, sys\n"
        "from podcast_tts.mcp_server import protect_stdio\n"
        "pin, pout = protect_stdio()\n"
        "print('ruido de print')\n"
        "os.write(1, b'ruido fd1\\n')\n"
        "subprocess.run([sys.executable, '-c', 'print(\"ruido hijo\")'])\n"
        "assert input.__call__ is not None\n"
        "try:\n    input()\nexcept EOFError:\n    pass\n"
        "pout.write('PROTO\\n')\n"
        "pout.flush()\n"
    )
    res = subprocess.run([sys.executable, "-c", code], capture_output=True, env=_env(tmp_path),
                         stdin=subprocess.PIPE, timeout=60)
    assert res.returncode == 0, res.stderr.decode("utf-8", "replace")
    assert res.stdout.decode() == "PROTO\n"
    err = res.stderr.decode("utf-8", "replace")
    assert "ruido de print" in err and "ruido fd1" in err and "ruido hijo" in err


# --------------------------------------------------------------------------- #


@pytest.mark.slow
@requires_ffmpeg
def test_generate_podcast_f5_real(tmp_path: Path) -> None:
    pytest.importorskip("f5_tts")
    lines = _raw_session(tmp_path, [
        {"name": "generate_podcast",
         "arguments": {"script": "[voz:ana]\nHola, esto es una prueba real del servidor MCP.\n",
                       "output_name": "f5_real", "engine": "f5", "wait_seconds": 300}},
    ], timeout=300)
    parsed = _assert_clean(lines)  # torch / f5 must not pollute stdout
    result = next(p for p in parsed if p.get("id") == 1)
    data = json.loads(result["result"]["content"][0]["text"])
    assert data["status"] == "done", data
    assert Path(data["output_path"]).is_file()
    assert data["duration_seconds"] > 1.0
    assert "license_notice" in data
    assert any(p.get("method") == "notifications/progress" for p in parsed)
