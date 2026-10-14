"""Registro de motores TTS (integrados y de terceros) con carga perezosa.

- Integrados: ``f5``, ``xtts``, ``dummy`` (locales) y ``elevenlabs``, ``azure``,
  ``openai`` (en la nube, de pago).
- De terceros: paquetes que declaran un *entry point* en el grupo
  ``podcast_tts.engines`` (ver ``docs/ENGINES_PLUGINS.md``)::

      [project.entry-points."podcast_tts.engines"]
      miengine = "podcast_tts_miengine:MiEngine"

- En tiempo de ejecución: :func:`register_engine`.

``get_engine("f5")`` importa ``podcast_tts.engines.f5`` solo cuando se pide; importar
este paquete NO importa torch ni ningún modelo. Las instancias se cachean (una por
proceso). Los nombres válidos se obtienen con :func:`engine_names` (``ENGINE_NAMES``
se calcula al leerlo e incluye los motores registrados).
"""

from __future__ import annotations

import importlib
import importlib.util
import logging
import sys
import threading
from dataclasses import dataclass
from importlib import metadata
from typing import Any, Callable

from .base import COMMERCIAL_DEPENDS, UNKNOWN_LICENSE, EngineError, LicenseInfo, TTSEngine

__all__ = [
    "COMMERCIAL_DEPENDS",
    "ENGINE_NAMES",
    "ENTRY_POINT_GROUP",
    "EngineError",
    "EngineSpec",
    "LicenseInfo",
    "TTSEngine",
    "clear_engine_cache",
    "engine_class",
    "engine_info",
    "engine_kind",
    "engine_license",
    "engine_names",
    "get_engine",
    "is_configured",
    "refresh_engines",
    "register_engine",
    "unregister_engine",
]

log = logging.getLogger(__name__)

ENTRY_POINT_GROUP = "podcast_tts.engines"


@dataclass
class EngineSpec:
    """Entrada del registro.

    ``target`` es ``"modulo:Clase"``, la propia clase/fábrica o un ``EntryPoint``.
    ``package`` es el paquete del que depende (para comprobar si está instalado sin
    importarlo). ``source`` es ``"integrado"``, ``"plugin (<distribución>)"`` o ``"registrado"``.
    """

    name: str
    target: Any
    package: str | None = None
    source: str = "integrado"
    _cls: Any = None
    _error: str | None = None

    def load(self) -> Any:
        """Importa y devuelve la clase (o fábrica) del motor. Lanza :class:`EngineError`."""
        if self._cls is not None:
            return self._cls
        try:
            if isinstance(self.target, str):
                module_name, _, attr = self.target.partition(":")
                obj = getattr(importlib.import_module(module_name), attr)
            elif isinstance(self.target, metadata.EntryPoint):
                obj = self.target.load()
            else:
                obj = self.target
        except Exception as exc:  # ImportError, AttributeError, errores del plugin...
            self._error = f"{type(exc).__name__}: {exc}"
            raise EngineError(
                f"no se pudo cargar el motor '{self.name}' ({self.source}): {exc}. "
                "¿Están instaladas sus dependencias?"
            ) from exc
        self._cls = obj
        self._error = None
        return obj


_BUILTINS: dict[str, tuple[str, str | None]] = {
    "f5": ("podcast_tts.engines.f5:F5Engine", "f5_tts"),
    "xtts": ("podcast_tts.engines.xtts:XTTSEngine", "TTS"),
    "dummy": ("podcast_tts.engines.dummy:DummyEngine", None),
    "elevenlabs": ("podcast_tts.engines.elevenlabs:ElevenLabsEngine", None),
    "azure": ("podcast_tts.engines.azure:AzureEngine", None),
    "openai": ("podcast_tts.engines.openai:OpenAIEngine", None),
}

_lock = threading.RLock()
_registry: dict[str, EngineSpec] | None = None  # se construye en el primer uso
_manual: dict[str, EngineSpec] = {}  # registrados con register_engine
_instances: dict[str, TTSEngine] = {}


def _norm(name: str) -> str:
    return (name or "").strip().lower()


def _discover_plugins() -> dict[str, EngineSpec]:
    """Lee los entry points del grupo ``podcast_tts.engines`` (sin importarlos)."""
    found: dict[str, EngineSpec] = {}
    try:
        eps = metadata.entry_points(group=ENTRY_POINT_GROUP)
    except Exception as exc:  # metadatos corruptos de algún paquete
        log.warning("No se pudieron leer los plugins de motores: %s", exc)
        return found
    for ep in eps:
        name = _norm(ep.name)
        if not name:
            continue
        dist = getattr(getattr(ep, "dist", None), "name", None)
        source = f"plugin ({dist})" if dist else "plugin"
        if name in _BUILTINS:
            log.warning("El plugin '%s' (%s) usa el nombre de un motor integrado; se ignora.",
                        name, ep.value)
            continue
        if name in found:
            log.warning("Hay dos plugins con el nombre '%s'; se usa el primero.", name)
            continue
        found[name] = EngineSpec(name=name, target=ep, source=source)
    return found


def _get_registry() -> dict[str, EngineSpec]:
    global _registry
    with _lock:
        if _registry is None:
            reg = {n: EngineSpec(n, target, package) for n, (target, package) in _BUILTINS.items()}
            reg.update(_discover_plugins())
            reg.update(_manual)
            _registry = reg
        return _registry


def refresh_engines() -> tuple[str, ...]:
    """Vuelve a buscar plugins (p.ej. tras instalar uno) y vacía la caché de instancias."""
    global _registry
    with _lock:
        _registry = None
        _instances.clear()
    return engine_names()


def register_engine(name: str, target: Any, *, package: str | None = None,
                    replace: bool = False) -> None:
    """Registra un motor en tiempo de ejecución.

    ``target`` puede ser ``"modulo:Clase"`` o la clase (o fábrica) del motor.
    No se pueden reemplazar los motores integrados.
    """
    key = _norm(name)
    if not key or not key.replace("_", "").replace("-", "").isalnum():
        raise EngineError(f"nombre de motor inválido {name!r}")
    if key in _BUILTINS:
        raise EngineError(f"'{key}' es un motor integrado y no se puede reemplazar")
    reg = _get_registry()
    with _lock:
        if key in reg and not replace:
            raise EngineError(f"ya hay un motor llamado '{key}' (usa replace=True)")
        spec = EngineSpec(name=key, target=target, package=package, source="registrado")
        _manual[key] = spec
        reg[key] = spec
        _instances.pop(key, None)


def unregister_engine(name: str) -> None:
    """Quita un motor registrado con :func:`register_engine` (o un plugin) del registro."""
    key = _norm(name)
    if key in _BUILTINS:
        raise EngineError(f"'{key}' es un motor integrado y no se puede quitar")
    reg = _get_registry()
    with _lock:
        _manual.pop(key, None)
        reg.pop(key, None)
        _instances.pop(key, None)


def engine_names() -> tuple[str, ...]:
    """Nombres de todos los motores: integrados primero y después los de terceros (ordenados)."""
    reg = _get_registry()
    extra = sorted(n for n in reg if n not in _BUILTINS)
    return tuple(n for n in _BUILTINS if n in reg) + tuple(extra)


def __getattr__(attr: str) -> Any:  # PEP 562: ENGINE_NAMES dinámico
    if attr == "ENGINE_NAMES":
        return engine_names()
    raise AttributeError(f"module {__name__!r} has no attribute {attr!r}")


def _spec(name: str) -> EngineSpec:
    key = _norm(name)
    reg = _get_registry()
    if key not in reg:
        raise EngineError(f"motor desconocido '{name}' (válidos: {', '.join(engine_names())})")
    return reg[key]


def engine_class(name: str) -> Any:
    """Clase (o fábrica) del motor ``name``, importándola si hace falta."""
    return _spec(name).load()


def engine_kind(name: str) -> str:
    """``"local"`` o ``"cloud"`` (por defecto ``"local"`` si el motor no lo declara)."""
    kind = getattr(engine_class(name), "kind", "local")
    return kind if kind in ("local", "cloud") else "local"


def engine_license(name: str) -> LicenseInfo:
    """:class:`LicenseInfo` del motor (o :data:`UNKNOWN_LICENSE` si no la declara)."""
    info = getattr(engine_class(name), "license_info", None)
    return info if isinstance(info, LicenseInfo) else UNKNOWN_LICENSE


def _required_config(cls: Any) -> tuple[str, ...]:
    req = getattr(cls, "required_config", ()) or ()
    return tuple(str(r) for r in req)


def is_configured(name: str) -> bool:
    """``True`` si están definidas todas las claves que necesita el motor (entorno o ``.env``)."""
    from ..config import get_key

    return all(get_key(k) for k in _required_config(engine_class(name)))


def get_engine(name: str, **kwargs: Any) -> TTSEngine:
    """Devuelve (y cachea) la instancia del motor ``name``.

    Si se pasan ``kwargs`` se crea una instancia nueva sin cachear.
    """
    key = _norm(name)
    spec = _spec(key)
    if not kwargs and key in _instances:
        return _instances[key]
    factory = spec.load()
    try:
        engine = factory(**kwargs)
    except EngineError:
        raise
    except Exception as exc:
        raise EngineError(f"no se pudo crear el motor '{key}': {exc}") from exc
    if not callable(getattr(engine, "synthesize", None)) or not hasattr(engine, "sample_rate"):
        raise EngineError(
            f"el motor '{key}' ({spec.source}) no implementa el protocolo TTSEngine "
            "(faltan synthesize() o sample_rate)"
        )
    if not kwargs:
        _instances[key] = engine
    return engine


def clear_engine_cache() -> None:
    """Olvida las instancias cacheadas (libera modelos)."""
    _instances.clear()


def _cuda_info() -> tuple[bool, str | None]:
    try:
        import torch  # perezoso: solo si se pide engine_info(check_cuda=True)
    except ImportError:
        return False, None
    try:
        if torch.cuda.is_available():
            return True, torch.cuda.get_device_name(0)
    except Exception:  # driver roto, etc.
        pass
    return False, None


def _is_loaded(name: str, spec: EngineSpec, kind: str) -> bool:
    if name == "f5":
        module = sys.modules.get("podcast_tts.engines.f5")
        return bool(module is not None and getattr(module, "loaded_models", lambda: [])())
    if name == "xtts":
        module = sys.modules.get("podcast_tts.engines.xtts")
        return bool(module is not None and getattr(module, "is_loaded", lambda: False)())
    if name == "dummy" or kind == "cloud":
        return True  # no hay modelo que cargar
    fn = getattr(spec._cls, "is_loaded", None)
    if callable(fn):
        try:
            return bool(fn())
        except Exception:  # noqa: BLE001
            return False
    return name in _instances


def engine_info(check_cuda: bool = True) -> dict[str, dict[str, Any]]:
    """Disponibilidad, tipo y licencia de cada motor, sin cargar modelos (pensado para la UI/CLI).

    Devuelve ``{nombre: {...}}`` con las claves:

    - ``importable`` (bool), ``error`` (str | None), ``loaded`` (bool),
      ``cuda`` (bool), ``device`` (str | None): como antes.
    - ``kind``: ``"local"`` o ``"cloud"``.
    - ``license``, ``license_url``, ``license_notes``: licencia del modelo/servicio.
    - ``commercial_use``: ``True``, ``False`` o ``"depende del plan"``.
    - ``configured``: ``True`` si están todas las claves que necesita (los locales, siempre).
    - ``required_config``: lista de variables necesarias.
    - ``source``: ``"integrado"``, ``"plugin (...)"`` o ``"registrado"``.

    Para los motores integrados solo comprueba que su paquete está instalado
    (``find_spec``); los módulos de los motores se importan para leer sus metadatos,
    pero no importan torch. ``torch`` solo se importa (perezosamente) si
    ``check_cuda`` es ``True`` y hay algún motor local que no sea ``dummy``.
    """
    from ..config import get_key

    reg = _get_registry()
    cuda, device = False, None
    if check_cuda:
        cuda, device = _cuda_info()
    info: dict[str, dict[str, Any]] = {}
    for name in engine_names():
        spec = reg[name]
        importable, error = True, None
        if spec.package is not None:
            try:
                importable = importlib.util.find_spec(spec.package) is not None
            except (ImportError, ValueError) as exc:
                importable, error = False, str(exc)
            if not importable and error is None:
                error = f"no está instalado el paquete '{spec.package}'"
        cls = None
        try:
            cls = spec.load()
        except EngineError as exc:
            importable = False
            error = error or str(exc)
        kind = getattr(cls, "kind", "local") if cls is not None else "local"
        kind = kind if kind in ("local", "cloud") else "local"
        lic = getattr(cls, "license_info", None)
        lic = lic if isinstance(lic, LicenseInfo) else UNKNOWN_LICENSE
        required = _required_config(cls) if cls is not None else ()
        missing = [k for k in required if not get_key(k)]
        gpu = kind == "local" and name != "dummy"
        info[name] = {
            "importable": importable,
            "cuda": cuda if gpu else False,
            "device": device if gpu else None,
            "loaded": _is_loaded(name, spec, kind) if cls is not None else False,
            "error": error,
            "kind": kind,
            "license": lic.name,
            "license_url": lic.url,
            "license_notes": lic.notes,
            "commercial_use": lic.commercial_use,
            "configured": not missing,
            "missing_config": missing,
            "required_config": list(required),
            "source": spec.source,
        }
    return info
