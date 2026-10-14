"""Registry of TTS engines (built-in and third-party) with lazy loading.

- Built-in: ``f5``, ``xtts``, ``dummy`` (local) and ``elevenlabs``, ``azure``,
  ``openai`` (cloud, paid).
- Third-party: packages that declare an *entry point* in the
  ``podcast_tts.engines`` group (see ``docs/ENGINES_PLUGINS.md``)::

      [project.entry-points."podcast_tts.engines"]
      myengine = "podcast_tts_myengine:MyEngine"

- At runtime: :func:`register_engine`.

``get_engine("f5")`` imports ``podcast_tts.engines.f5`` only when requested; importing
this package does NOT import torch or any model. Instances are cached (one per
process). The valid names come from :func:`engine_names` (``ENGINE_NAMES``
is computed when read and includes registered engines).
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
    """Registry entry.

    ``target`` is ``"module:Class"``, the class/factory itself or an ``EntryPoint``.
    ``package`` is the package it depends on (to check whether it is installed without
    importing it). ``source`` is ``"built-in"``, ``"plugin (<distribution>)"`` or ``"registered"``.
    """

    name: str
    target: Any
    package: str | None = None
    source: str = "built-in"
    _cls: Any = None
    _error: str | None = None

    def load(self) -> Any:
        """Import and return the engine class (or factory). Raises :class:`EngineError`."""
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
        except Exception as exc:  # ImportError, AttributeError, plugin errors...
            self._error = f"{type(exc).__name__}: {exc}"
            raise EngineError(
                f"could not load engine '{self.name}' ({self.source}): {exc}. "
                "Are its dependencies installed?"
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
_registry: dict[str, EngineSpec] | None = None  # built on first use
_manual: dict[str, EngineSpec] = {}  # registered with register_engine
_instances: dict[str, TTSEngine] = {}


def _norm(name: str) -> str:
    return (name or "").strip().lower()


def _discover_plugins() -> dict[str, EngineSpec]:
    """Read the entry points of the ``podcast_tts.engines`` group (without importing them)."""
    found: dict[str, EngineSpec] = {}
    try:
        eps = metadata.entry_points(group=ENTRY_POINT_GROUP)
    except Exception as exc:  # corrupt metadata in some package
        log.warning("Could not read the engine plugins: %s", exc)
        return found
    for ep in eps:
        name = _norm(ep.name)
        if not name:
            continue
        dist = getattr(getattr(ep, "dist", None), "name", None)
        source = f"plugin ({dist})" if dist else "plugin"
        if name in _BUILTINS:
            log.warning("Plugin '%s' (%s) uses the name of a built-in engine; ignoring it.",
                        name, ep.value)
            continue
        if name in found:
            log.warning("There are two plugins named '%s'; using the first one.", name)
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
    """Look for plugins again (e.g. after installing one) and clear the instance cache."""
    global _registry
    with _lock:
        _registry = None
        _instances.clear()
    return engine_names()


def register_engine(name: str, target: Any, *, package: str | None = None,
                    replace: bool = False) -> None:
    """Register an engine at runtime.

    ``target`` can be ``"module:Class"`` or the engine class (or factory).
    Built-in engines cannot be replaced.
    """
    key = _norm(name)
    if not key or not key.replace("_", "").replace("-", "").isalnum():
        raise EngineError(f"invalid engine name {name!r}")
    if key in _BUILTINS:
        raise EngineError(f"'{key}' is a built-in engine and cannot be replaced")
    reg = _get_registry()
    with _lock:
        if key in reg and not replace:
            raise EngineError(f"there is already an engine named '{key}' (use replace=True)")
        spec = EngineSpec(name=key, target=target, package=package, source="registered")
        _manual[key] = spec
        reg[key] = spec
        _instances.pop(key, None)


def unregister_engine(name: str) -> None:
    """Remove an engine registered with :func:`register_engine` (or a plugin) from the registry."""
    key = _norm(name)
    if key in _BUILTINS:
        raise EngineError(f"'{key}' is a built-in engine and cannot be removed")
    reg = _get_registry()
    with _lock:
        _manual.pop(key, None)
        reg.pop(key, None)
        _instances.pop(key, None)


def engine_names() -> tuple[str, ...]:
    """Names of all engines: built-in first, then third-party ones (sorted)."""
    reg = _get_registry()
    extra = sorted(n for n in reg if n not in _BUILTINS)
    return tuple(n for n in _BUILTINS if n in reg) + tuple(extra)


def __getattr__(attr: str) -> Any:  # PEP 562: dynamic ENGINE_NAMES
    if attr == "ENGINE_NAMES":
        return engine_names()
    raise AttributeError(f"module {__name__!r} has no attribute {attr!r}")


def _spec(name: str) -> EngineSpec:
    key = _norm(name)
    reg = _get_registry()
    if key not in reg:
        raise EngineError(f"unknown engine '{name}' (valid: {', '.join(engine_names())})")
    return reg[key]


def engine_class(name: str) -> Any:
    """Class (or factory) of engine ``name``, importing it if needed."""
    return _spec(name).load()


def engine_kind(name: str) -> str:
    """``"local"`` or ``"cloud"`` (``"local"`` by default if the engine does not declare it)."""
    kind = getattr(engine_class(name), "kind", "local")
    return kind if kind in ("local", "cloud") else "local"


def engine_license(name: str) -> LicenseInfo:
    """The engine's :class:`LicenseInfo` (or :data:`UNKNOWN_LICENSE` if it does not declare one)."""
    info = getattr(engine_class(name), "license_info", None)
    return info if isinstance(info, LicenseInfo) else UNKNOWN_LICENSE


def _required_config(cls: Any) -> tuple[str, ...]:
    req = getattr(cls, "required_config", ()) or ()
    return tuple(str(r) for r in req)


def is_configured(name: str) -> bool:
    """``True`` if every key the engine needs is defined (environment or ``.env``)."""
    from ..config import get_key

    return all(get_key(k) for k in _required_config(engine_class(name)))


def get_engine(name: str, **kwargs: Any) -> TTSEngine:
    """Return (and cache) the instance of engine ``name``.

    If ``kwargs`` are given, a new uncached instance is created.
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
        raise EngineError(f"could not create engine '{key}': {exc}") from exc
    if not callable(getattr(engine, "synthesize", None)) or not hasattr(engine, "sample_rate"):
        raise EngineError(
            f"engine '{key}' ({spec.source}) does not implement the TTSEngine protocol "
            "(synthesize() or sample_rate is missing)"
        )
    if not kwargs:
        _instances[key] = engine
    return engine


def clear_engine_cache() -> None:
    """Forget the cached instances (frees models)."""
    _instances.clear()


def _cuda_info() -> tuple[bool, str | None]:
    try:
        import torch  # lazy: only if engine_info(check_cuda=True) is requested
    except ImportError:
        return False, None
    try:
        if torch.cuda.is_available():
            return True, torch.cuda.get_device_name(0)
    except Exception:  # broken driver, etc.
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
        return True  # there is no model to load
    fn = getattr(spec._cls, "is_loaded", None)
    if callable(fn):
        try:
            return bool(fn())
        except Exception:  # noqa: BLE001
            return False
    return name in _instances


def engine_info(check_cuda: bool = True) -> dict[str, dict[str, Any]]:
    """Availability, kind and license of each engine, without loading models (for the UI/CLI).

    Returns ``{name: {...}}`` with the keys:

    - ``importable`` (bool), ``error`` (str | None), ``loaded`` (bool),
      ``cuda`` (bool), ``device`` (str | None).
    - ``kind``: ``"local"`` or ``"cloud"``.
    - ``license``, ``license_url``, ``license_notes``: license of the model/service.
    - ``commercial_use``: ``True``, ``False`` or ``"depends on plan"``.
    - ``configured``: ``True`` if every key it needs is present (always for local engines).
    - ``required_config``: list of required variables.
    - ``source``: ``"built-in"``, ``"plugin (...)"`` or ``"registered"``.

    For built-in engines it only checks that their package is installed
    (``find_spec``); the engine modules are imported to read their metadata,
    but they do not import torch. ``torch`` is only imported (lazily) if
    ``check_cuda`` is ``True`` and there is some local engine other than ``dummy``.
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
                error = f"package '{spec.package}' is not installed"
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
