"""Interfaz común de los motores TTS y metadatos de licencia."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any, Protocol, Union, runtime_checkable

import numpy as np

if TYPE_CHECKING:
    from ..voices import Voice

__all__ = [
    "COMMERCIAL_DEPENDS",
    "EngineError",
    "LicenseInfo",
    "TTSEngine",
    "UNKNOWN_LICENSE",
]

#: Valor de ``LicenseInfo.commercial_use`` cuando depende del plan contratado con el proveedor.
COMMERCIAL_DEPENDS = "depende del plan"

CommercialUse = Union[bool, str]


class EngineError(RuntimeError):
    """Error de un motor TTS (modelo no disponible, voz incompatible, API caída...)."""


@dataclass(frozen=True)
class LicenseInfo:
    """Licencia que rige el audio generado por un motor (modelo o servicio).

    - ``name``: nombre corto ("CC-BY-NC-4.0", "Coqui Public Model License"...).
    - ``url``: dónde leer la licencia o los términos.
    - ``commercial_use``: ``True``, ``False`` o ``"depende del plan"``.
    - ``notes``: aclaraciones breves (en castellano).
    """

    name: str
    url: str = ""
    commercial_use: CommercialUse = False
    notes: str = ""

    @property
    def is_non_commercial(self) -> bool:
        """``True`` solo si la licencia prohíbe expresamente el uso comercial."""
        return self.commercial_use is False

    def commercial_label(self) -> str:
        """Texto corto para tablas: "sí", "no" o "depende del plan"."""
        if self.commercial_use is True:
            return "sí"
        if self.commercial_use is False:
            return "no"
        return str(self.commercial_use)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


#: Licencia que se asume para motores de terceros que no declaran ``license_info``.
UNKNOWN_LICENSE = LicenseInfo(
    name="no declarada",
    url="",
    commercial_use=False,
    notes="El motor no declara su licencia: trátalo como no comercial hasta comprobarlo.",
)


@runtime_checkable
class TTSEngine(Protocol):
    """Protocolo que implementan todos los motores (integrados y de terceros).

    Atributos de clase:

    - ``name``: identificador corto ("f5", "xtts", "openai"...).
    - ``license_info``: :class:`LicenseInfo` del modelo o servicio.
    - ``kind`` (opcional, por defecto ``"local"``): ``"local"`` o ``"cloud"``.
    - ``required_config`` (opcional, por defecto ``()``): variables de configuración
      necesarias (p.ej. ``("OPENAI_API_KEY",)``), que se leen con :mod:`podcast_tts.config`.

    Métodos:

    - ``sample_rate``: frecuencia de muestreo del audio devuelto.
    - ``synthesize``: devuelve ``np.ndarray`` float32 mono en [-1, 1] a
      ``sample_rate`` Hz. ``lang`` es un código ISO corto ("es", "en"...) y
      ``speed`` un factor (1.0 = normal). La voz aporta ``ref_wav``,
      ``ref_text``, ``xtts_speaker``, ``provider_voice_id`` y ``provider_options``.
    """

    name: str
    license_info: LicenseInfo

    @property
    def sample_rate(self) -> int: ...

    def synthesize(self, text: str, voice: "Voice", lang: str, speed: float = 1.0) -> np.ndarray: ...
