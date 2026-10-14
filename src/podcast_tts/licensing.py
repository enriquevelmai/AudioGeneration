"""License notices: which engines a script uses and whether any of them is non-commercial."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from .engines import EngineError, LicenseInfo, engine_license
from .i18n import t
from .script_parser import ParsedScript, Speech

__all__ = ["engines_in_script", "license_notice", "noncommercial_engines"]

COMMERCIAL_DOC = "docs/COMMERCIAL_USE.md"


def engines_in_script(script: ParsedScript, voices_dir: str | Path | None = None,
                      engine_override: str | None = None) -> list[str]:
    """Engines each sentence of the script will use (in order of appearance, without repeats).

    Sentences whose voice does not exist are skipped (that error is reported when generating).
    """
    from .assembler import AssembleError, AssembleOptions, resolve_speech

    options = AssembleOptions(engine_override=engine_override)
    root = Path(voices_dir) if voices_dir else None
    seen: list[str] = []
    for seg in script.segments:
        if not isinstance(seg, Speech):
            continue
        try:
            engine = resolve_speech(seg, script, root, options).engine
        except AssembleError:
            continue
        if engine not in seen:
            seen.append(engine)
    return seen


def noncommercial_engines(names: Iterable[str]) -> list[tuple[str, LicenseInfo]]:
    """The engines in ``names`` whose license forbids commercial use."""
    result = []
    for name in dict.fromkeys(names):
        try:
            lic = engine_license(name)
        except EngineError:
            continue
        if lic.is_non_commercial:
            result.append((name, lic))
    return result


def license_notice(names: Iterable[str], *, markdown: bool = False) -> str | None:
    """Short notice if any engine in ``names`` is non-commercial; ``None`` if there is nothing
    to report. Translated to the active UI language (see :mod:`podcast_tts.i18n`)."""
    bad = noncommercial_engines(names)
    if not bad:
        return None
    if markdown:
        items = ", ".join(f"`{n}` ({lic.name})" for n, lic in bad)
    else:
        items = ", ".join(f"'{n}' ({lic.name})" for n, lic in bad)
    key = "license.notice_many" if len(bad) > 1 else "license.notice_one"
    return t(key, items=items, doc=COMMERCIAL_DOC)
