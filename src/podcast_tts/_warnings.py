"""Filters for third-party warnings that are of no use to the user.

They are applied when :mod:`podcast_tts` is imported and again inside the UI's
``warnings.catch_warnings`` blocks (which reset the filters).
"""

from __future__ import annotations

import warnings

__all__ = ["NOISY_WARNINGS", "silence_noisy_warnings"]

#: (message regular expression, category)
NOISY_WARNINGS: tuple[tuple[str, type[Warning]], ...] = (
    # torchaudio 2.8 warns on every audio load that 2.9 will switch to torchcodec
    # (we do not upgrade to 2.9: see docs/DECISIONS.md).
    (r"In 2\.9, this function's implementation", Warning),
    # starlette renamed HTTP_422_UNPROCESSABLE_ENTITY; gradio uses it internally.
    (r".*HTTP_422_UNPROCESSABLE_ENTITY", Warning),
)


def silence_noisy_warnings() -> None:
    """Ignore the warnings in :data:`NOISY_WARNINGS` (idempotent in practice)."""
    for message, category in NOISY_WARNINGS:
        warnings.filterwarnings("ignore", message=message, category=category)
