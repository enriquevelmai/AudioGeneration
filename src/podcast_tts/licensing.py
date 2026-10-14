"""Avisos de licencia: qué motores usa un guion y si alguno es de uso no comercial."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from .engines import EngineError, LicenseInfo, engine_license
from .script_parser import ParsedScript, Speech

__all__ = ["engines_in_script", "license_notice", "noncommercial_engines"]

COMMERCIAL_DOC = "docs/COMMERCIAL_USE.md"


def engines_in_script(script: ParsedScript, voices_dir: str | Path | None = None,
                      engine_override: str | None = None) -> list[str]:
    """Motores que usará cada frase del guion (en orden de aparición, sin repetir).

    Las frases cuya voz no existe se ignoran (ese error se notifica al generar).
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
    """Los motores de ``names`` cuya licencia prohíbe el uso comercial."""
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
    """Aviso breve si algún motor de ``names`` es no comercial; ``None`` si no hay nada que avisar."""
    bad = noncommercial_engines(names)
    if not bad:
        return None
    if markdown:
        items = ", ".join(f"`{n}` ({lic.name})" for n, lic in bad)
    else:
        items = ", ".join(f"'{n}' ({lic.name})" for n, lic in bad)
    plural = len(bad) > 1
    return (
        f"Aviso de licencia: {'los motores' if plural else 'el motor'} {items} "
        f"{'son' if plural else 'es'} solo para uso NO comercial. Para uso comercial usa un "
        f"motor con licencia comercial (p.ej. elevenlabs, azure u openai con plan de pago); "
        f"ver {COMMERCIAL_DOC}."
    )
