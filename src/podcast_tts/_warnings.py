"""Filtros de avisos de terceros que no aportan nada al usuario.

Se aplican al importar :mod:`podcast_tts` y otra vez dentro de los bloques
``warnings.catch_warnings`` de la UI (que reinician los filtros).
"""

from __future__ import annotations

import warnings

__all__ = ["NOISY_WARNINGS", "silence_noisy_warnings"]

#: (expresión regular del mensaje, categoría)
NOISY_WARNINGS: tuple[tuple[str, type[Warning]], ...] = (
    # torchaudio 2.8 avisa en cada carga de audio de que en 2.9 cambiará a torchcodec
    # (no subimos a 2.9: ver docs/DECISIONS.md).
    (r"In 2\.9, this function's implementation", Warning),
    # starlette renombró HTTP_422_UNPROCESSABLE_ENTITY; lo usa gradio internamente.
    (r".*HTTP_422_UNPROCESSABLE_ENTITY", Warning),
)


def silence_noisy_warnings() -> None:
    """Ignora los avisos de :data:`NOISY_WARNINGS` (idempotente en la práctica)."""
    for message, category in NOISY_WARNINGS:
        warnings.filterwarnings("ignore", message=message, category=category)
