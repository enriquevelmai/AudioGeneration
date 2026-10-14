"""Minimal, dependency-free translations for the CLI, the web UI and the desktop app.

English is the primary (source) language; Spanish is an optional secondary language.

Language resolution order (first valid value wins):

1. Environment variable ``PODCAST_TTS_LANG`` (``en`` or ``es``; ``es_ES``/``en-US`` also work).
2. Saved setting ``PODCAST_TTS_LANG`` in the project's ``.env`` file (see :mod:`podcast_tts.config`;
   written by :func:`save_language` or the UI's Settings tab).
3. Default: ``en``. The operating system language is deliberately NOT auto-detected.

The language is resolved once per process and cached; :func:`set_language` changes it for
the current process and :func:`reset_language` forgets the cached value (for tests).

Usage::

    from podcast_tts.i18n import t
    print(t("cli.voice_saved", name="ana", path="voices/ana"))

Missing keys fall back to the key itself; missing translations fall back to English.
"""

from __future__ import annotations

import os
from pathlib import Path

__all__ = [
    "CATALOG",
    "DEFAULT_LANGUAGE",
    "ENV_VAR",
    "LANGUAGE_NAMES",
    "available_languages",
    "get_language",
    "normalize_language",
    "reset_language",
    "save_language",
    "saved_language",
    "set_language",
    "t",
]

ENV_VAR = "PODCAST_TTS_LANG"
DEFAULT_LANGUAGE = "en"
#: Supported UI languages and their native names (for selectors).
LANGUAGE_NAMES: dict[str, str] = {"en": "English", "es": "Español"}

_active: str | None = None


def available_languages() -> tuple[str, ...]:
    """Supported language codes, primary language first: ``("en", "es")``."""
    return tuple(LANGUAGE_NAMES)


def normalize_language(value: str | None) -> str | None:
    """``"es_ES.UTF-8"`` -> ``"es"``; ``None`` if empty or not a supported language."""
    if not value:
        return None
    code = value.strip().lower().replace("-", "_").split("_")[0].split(".")[0]
    return code if code in LANGUAGE_NAMES else None


def saved_language(env_file: str | Path | None = None) -> str | None:
    """Language saved in the ``.env`` file (ignores the environment variable), or ``None``."""
    from .config import read_env_file

    try:
        return normalize_language(read_env_file(env_file).get(ENV_VAR))
    except Exception:  # noqa: BLE001 - an unreadable .env must never break the app
        return None


def _resolve() -> str:
    return (normalize_language(os.environ.get(ENV_VAR)) or saved_language()
            or DEFAULT_LANGUAGE)


def get_language() -> str:
    """Active language code (``"en"`` or ``"es"``), resolved once and cached."""
    global _active
    if _active is None:
        _active = _resolve()
    return _active


def set_language(lang: str, *, persist: bool = False,
                 env_file: str | Path | None = None) -> str:
    """Switch the language of the current process (and save it in ``.env`` if ``persist``).

    :raises ValueError: if ``lang`` is not one of :func:`available_languages`.
    """
    global _active
    code = normalize_language(lang)
    if code is None:
        raise ValueError(f"unsupported language {lang!r} "
                         f"(available: {', '.join(available_languages())})")
    if persist:
        save_language(code, env_file=env_file)
    _active = code
    return code


def save_language(lang: str, env_file: str | Path | None = None) -> Path:
    """Save ``lang`` as the preferred language in ``.env`` without touching the running process.

    It takes effect the next time the app starts (unless ``$PODCAST_TTS_LANG`` overrides it).

    :raises ValueError: if ``lang`` is not supported.
    """
    from .config import set_key

    code = normalize_language(lang)
    if code is None:
        raise ValueError(f"unsupported language {lang!r} "
                         f"(available: {', '.join(available_languages())})")
    return set_key(ENV_VAR, code, env_file)


def reset_language() -> None:
    """Forget the cached language: the next :func:`get_language` resolves it again."""
    global _active
    _active = None


def t(key: str, *, _lang: str | None = None, **kwargs: object) -> str:
    """Translated message for ``key`` in the active language, formatted with ``kwargs``.

    Falls back to English if the translation is missing, and to ``key`` if the key is unknown.
    """
    entry = CATALOG.get(key)
    if entry is None:
        text = key
    else:
        lang = normalize_language(_lang) if _lang else get_language()
        text = entry.get(lang or DEFAULT_LANGUAGE) or entry[DEFAULT_LANGUAGE]
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, IndexError, ValueError):
            return text
    return text


# --------------------------------------------------------------------------- #
# Catalog: key -> (English, Spanish)
# --------------------------------------------------------------------------- #

_MESSAGES: dict[str, tuple[str, str]] = {
    # ---------------------------------------------------------------- common
    "common.yes": ("yes", "sí"),
    "common.no": ("no", "no"),
    "common.NO": ("NO", "NO"),
    "common.depends_on_plan": ("depends on plan", "depende del plan"),
    "common.optional": (" (optional)", " (opcional)"),
    "common.warning": ("Warning: {msg}", "Aviso: {msg}"),
    "common.json_output": ("JSON output", "salida en JSON"),
    "common.voices_dir_help": ("voices directory (default: <project>/voices)",
                               "directorio de voces (por defecto: <proyecto>/voices)"),
    "common.voices_dir_short": ("voices directory", "directorio de voces"),

    # ---------------------------------------------------------------- licensing
    "license.notice_one": (
        "License notice: the engine {items} is for NON-commercial use only. For commercial use, "
        "pick an engine with a commercial license (e.g. elevenlabs, azure or openai on a paid "
        "plan); see {doc}.",
        "Aviso de licencia: el motor {items} es solo para uso NO comercial. Para uso comercial "
        "usa un motor con licencia comercial (p.ej. elevenlabs, azure u openai con plan de "
        "pago); ver {doc}."),
    "license.notice_many": (
        "License notice: the engines {items} are for NON-commercial use only. For commercial "
        "use, pick an engine with a commercial license (e.g. elevenlabs, azure or openai on a "
        "paid plan); see {doc}.",
        "Aviso de licencia: los motores {items} son solo para uso NO comercial. Para uso "
        "comercial usa un motor con licencia comercial (p.ej. elevenlabs, azure u openai con "
        "plan de pago); ver {doc}."),

    # ---------------------------------------------------------------- CLI: messages
    "cli.script_not_found": ("Error: script not found: {path}", "Error: no existe el guion {path}"),
    "cli.generating": ("Generating {output} from {script}...",
                       "Generando {output} a partir de {script}..."),
    "cli.done_duration": ("Done: {path} — duration {duration:.1f} s, generated in {elapsed:.1f} s",
                          "Listo: {path} — duración {duration:.1f} s, generado en {elapsed:.1f} s"),
    "cli.done": ("Done: {path} — generated in {elapsed:.1f} s",
                 "Listo: {path} — generado en {elapsed:.1f} s"),
    "cli.hide_notice": ("(Hide this notice with --no-license-notice.)",
                        "(Oculta este aviso con --no-license-notice.)"),
    "cli.no_voices": ("No voices in {root}. Add one with: python -m podcast_tts voices add ...",
                      "No hay voces en {root}. Añade una con: python -m podcast_tts voices add ..."),
    "cli.voices_in": ("Voices in {root}:", "Voces en {root}:"),
    "cli.provider_voice": ("provider voice '{id}'", "voz del proveedor '{id}'"),
    "cli.no_ref": ("NO ref.wav", "SIN ref.wav"),
    "cli.voice_saved": ("Voice '{name}' saved to {path}", "Voz '{name}' guardada en {path}"),
    "cli.voice_removed": ("Voice '{name}' removed", "Voz '{name}' eliminada"),
    "cli.col_engine": ("Engine", "Motor"),
    "cli.col_type": ("Type", "Tipo"),
    "cli.col_commercial": ("Commercial", "Comercial"),
    "cli.col_status": ("Status", "Estado"),
    "cli.col_license": ("License", "Licencia"),
    "cli.state_unavailable": ("not available", "no disponible"),
    "cli.state_unconfigured": ("not configured", "sin configurar"),
    "cli.state_ready": ("ready", "listo"),
    "cli.missing_config": ("missing: {names} (python -m podcast_tts config set {first})",
                           "falta: {names} (python -m podcast_tts config set {first})"),
    "cli.engines_footer": (
        "\nThe f5 and xtts weights are for NON-commercial use only. See docs/COMMERCIAL_USE.md.",
        "\nLos pesos de f5 y xtts son de uso NO comercial. Ver docs/COMMERCIAL_USE.md."),
    "cli.env_file": ("File .env: {path}", "Fichero .env: {path}"),
    "cli.not_set": ("(not set)", "(sin definir)"),
    "cli.env_priority": ("Environment variables take precedence over the .env file.",
                         "Las variables de entorno tienen prioridad sobre el fichero .env."),
    "cli.unknown_var": ("Warning: {name} is not a known variable; saving it anyway.",
                        "Aviso: {name} no es una variable conocida; se guarda igualmente."),
    "cli.prompt_secret": ("Value of {name} (input is hidden): ",
                          "Valor de {name} (no se mostrará): "),
    "cli.prompt_value": ("Value of {name}: ", "Valor de {name}: "),
    "cli.key_saved": ("{name} saved to {path} ({shown})", "{name} guardada en {path} ({shown})"),
    "cli.env_also_set": (
        "Warning: {name} is also set as an environment variable, which takes precedence.",
        "Aviso: {name} también está definida como variable de entorno y tiene prioridad."),
    "cli.key_deleted": ("{name} removed from {path}", "{name} borrada de {path}"),
    "cli.key_absent": ("{name} was not in {path}", "{name} no estaba en {path}"),
    "cli.env_still_set": (
        "Warning: {name} is still set as an environment variable; remove it from your system.",
        "Aviso: {name} sigue definida como variable de entorno; bórrala de tu sistema."),
    "cli.models_intro": (
        "Local engine models (downloaded automatically the first time they are used):\n",
        "Modelos de los motores locales (se descargan solos la primera vez que se usan):\n"),
    "cli.models_size": ("size ~{size} | license: {license} | commercial use: {commercial}",
                        "tamaño ~{size} | licencia: {license} | uso comercial: {commercial}"),
    "cli.models_used_by": ("used by: {used_by}", "lo usa: {used_by}"),
    "cli.models_note": ("note: {note}", "nota: {note}"),
    "cli.models_footer": (
        "\nDownload now: podcast-tts models download all   |   Status: podcast-tts models status",
        "\nDescargar ya: podcast-tts models download all   |   Estado: podcast-tts models status"),
    "cli.model_downloaded": ("downloaded ({size})", "descargado ({size})"),
    "cli.model_partial": ("INCOMPLETE (missing {files})", "INCOMPLETO (faltan {files})"),
    "cli.model_missing": ("not downloaded", "no descargado"),
    "cli.models_nothing_to_update": (
        "No downloaded models to update (use: podcast-tts models download).",
        "No hay modelos descargados que actualizar (usa: podcast-tts models download)."),
    "cli.xtts_license": (
        "Warning: XTTS v2 is distributed under the Coqui Public Model License (NON-commercial "
        "use).",
        "Aviso: XTTS v2 se distribuye bajo la Coqui Public Model License (uso NO comercial)."),
    "cli.models_failed": ("Failed: {names}", "Fallaron: {names}"),
    "cli.models_ready": ("Models ready.", "Modelos listos."),
    "cli.err_script": ("Script error: {exc}", "Error en el guion: {exc}"),
    "cli.err_generic": ("Error: {exc}", "Error: {exc}"),
    "cli.err_not_implemented": ("Not implemented: {exc}", "No implementado: {exc}"),
    "cli.err_file_not_found": ("Error: file not found: {file}",
                               "Error: fichero no encontrado: {file}"),
    "cli.cancelled_no_value": ("Cancelled: no value was entered.",
                               "Cancelado: no se recibió ningún valor."),
    "cli.cancelled": ("Cancelled.", "Cancelado."),

    # ---------------------------------------------------------------- CLI: argparse help
    "cli.h_description": (
        "Generate podcasts from Markdown scripts with cloned voices (F5-TTS / XTTS v2) or "
        "cloud voices.",
        "Genera podcasts a partir de guiones Markdown con voces clonadas (F5-TTS / XTTS v2) "
        "o voces en la nube."),
    "cli.mv_command": ("command", "comando"),
    "cli.mv_action": ("action", "acción"),
    "cli.mv_name": ("name", "nombre"),
    "cli.mv_key_value": ("KEY=VALUE", "CLAVE=VALOR"),
    "cli.mv_user_pass": ("USER:PASSWORD", "USUARIO:CLAVE"),
    "cli.h_generate": ("generate the audio of a script", "genera el audio de un guion"),
    "cli.h_script": ("script (.md)", "guion .md"),
    "cli.h_output": ("output file .mp3/.wav (default: output/<script>.mp3)",
                     "fichero de salida .mp3/.wav (por defecto output/<guion>.mp3)"),
    "cli.h_engine": ("force one engine for every voice (e.g. dummy for testing)",
                     "fuerza un motor para todas las voces (p.ej. dummy para probar)"),
    "cli.h_max_chars": ("maximum length of each text chunk (default {n})",
                        "longitud máxima de cada trozo de texto (por defecto {n})"),
    "cli.h_bitrate": ("MP3 bitrate (default 192k)", "bitrate MP3 (por defecto 192k)"),
    "cli.h_sample_rate": ("output sample rate (Hz)", "frecuencia de salida (Hz)"),
    "cli.h_lufs": ("target loudness (default -16)", "sonoridad objetivo (por defecto -16)"),
    "cli.h_no_normalize": ("do not normalize loudness", "no normalizar la sonoridad"),
    "cli.h_no_cache": ("do not use the synthesis cache", "no usar la caché de síntesis"),
    "cli.h_cache_dir": ("cache directory (default .cache/tts)",
                        "directorio de caché (por defecto .cache/tts)"),
    "cli.h_quiet": ("do not show progress", "no mostrar el progreso"),
    "cli.h_no_license_notice": ("do not show the license notice for non-commercial engines",
                                "no mostrar el aviso de licencia de los motores no comerciales"),
    "cli.h_parse": ("parse a script and print its segments as JSON",
                    "parsea un guion e imprime los segmentos en JSON"),
    "cli.h_compact": ("single-line JSON", "JSON en una sola línea"),
    "cli.h_voices": ("manage voices", "gestiona las voces"),
    "cli.h_voices_list": ("list the voices", "lista las voces"),
    "cli.h_voices_add": ("add a voice from a clip", "añade una voz a partir de un clip"),
    "cli.h_voice_name": ("voice name (letters, digits, _ or -)",
                         "nombre de la voz (letras, números, _ o -)"),
    "cli.h_wav": ("reference clip (5-15 s; any format ffmpeg reads)",
                  "clip de referencia (5-15 s; cualquier formato de ffmpeg)"),
    "cli.h_text": ("exact transcript of the clip (required by F5)",
                   "transcripción exacta del clip (necesaria para F5)"),
    "cli.h_text_file": ("file with the transcript", "fichero con la transcripción"),
    "cli.h_lang": ("main language (es, en, ...)", "idioma principal (es, en, ...)"),
    "cli.h_voice_engine": ("default engine of the voice", "motor por defecto de la voz"),
    "cli.h_description_free": ("free-form description", "descripción libre"),
    "cli.h_xtts_speaker": ("built-in XTTS speaker (instead of cloning)",
                           "speaker integrado de XTTS (en vez de clonar)"),
    "cli.h_speed": ("default speed", "velocidad por defecto"),
    "cli.h_overwrite": ("overwrite if it already exists", "sobrescribe si ya existe"),
    "cli.h_provider_voice_id": (
        "voice ID or name at the provider (cloud engines: elevenlabs, azure, openai)",
        "ID o nombre de la voz en el proveedor (motores en la nube: elevenlabs, azure, openai)"),
    "cli.h_provider_option": (
        "provider option (repeatable; the value may be JSON), e.g. model_id=eleven_turbo_v2_5",
        "opción del proveedor (repetible; el valor puede ser JSON), "
        "p.ej. model_id=eleven_turbo_v2_5"),
    "cli.h_voices_remove": ("remove a voice", "elimina una voz"),
    "cli.h_engines": ("list the engines: type, license, commercial use and status",
                      "lista los motores: tipo, licencia, uso comercial y estado"),
    "cli.h_cuda": ("also check the GPU (imports torch)",
                   "comprueba también la GPU (importa torch)"),
    "cli.h_config": ("API keys of the cloud engines and settings (.env)",
                     "claves de API de los motores en la nube y ajustes (.env)"),
    "cli.h_config_show": ("show the keys (masked)", "muestra las claves (enmascaradas)"),
    "cli.h_config_set": ("save a key in .env (the value is read without echo)",
                         "guarda una clave en .env (el valor se pide sin eco)"),
    "cli.h_config_unset": ("remove a key from .env", "borra una clave de .env"),
    "cli.h_variable": ("variable, e.g. ELEVENLABS_API_KEY or PODCAST_TTS_LANG",
                       "variable, p.ej. ELEVENLABS_API_KEY o PODCAST_TTS_LANG"),
    "cli.h_ui": ("launch the local web UI (Gradio)", "lanza la interfaz web local (Gradio)"),
    "cli.h_port": ("port (default 7860)", "puerto (por defecto 7860)"),
    "cli.h_host": ("network interface (default 127.0.0.1)",
                   "interfaz de red (por defecto 127.0.0.1)"),
    "cli.h_share": ("create a temporary public Gradio link",
                    "crea un enlace público temporal de Gradio"),
    "cli.h_auth": (
        "access user and password; required with --share or a --host other than "
        "127.0.0.1/localhost (also via the {env} variable)",
        "usuario y clave de acceso; obligatorio con --share o con un --host que no sea "
        "127.0.0.1/localhost (también con la variable {env})"),
    "cli.h_inbrowser": ("open the browser on startup", "abre el navegador al arrancar"),
    "cli.h_desktop": ("open the desktop app (native window; requires the desktop extra)",
                      "abre la app de escritorio (ventana nativa; requiere el extra desktop)"),
    "cli.h_mcp": (
        "MCP server (stdio) for Claude Desktop, Claude Code, Cursor, VS Code... "
        "(requires the mcp extra)",
        "servidor MCP (stdio) para Claude Desktop, Claude Code, Cursor, VS Code... "
        "(requiere el extra mcp)"),
    "cli.h_output_dir": ("output folder (default $PODCAST_TTS_OUTPUT_DIR or <project>/output)",
                         "carpeta de salida (por defecto $PODCAST_TTS_OUTPUT_DIR o "
                         "<proyecto>/output)"),
    "cli.h_models": ("list, check and download the local engine models",
                     "lista, comprueba y descarga los modelos de los motores locales"),
    "cli.h_models_list": ("known models, Hugging Face repo, size and license",
                          "modelos conocidos, repo de Hugging Face, tamaño y licencia"),
    "cli.h_models_status": ("whether each model is downloaded, where and how big",
                            "si cada modelo está descargado, dónde y cuánto ocupa"),
    "cli.h_models_download": ("download the missing models (default: all)",
                              "descarga los modelos que falten (por defecto: all)"),
    "cli.h_models_names": (
        "f5-base, f5-spanish, vocos, xtts, whisper or all (default all; whisper is optional)",
        "f5-base, f5-spanish, vocos, xtts, whisper o all (por defecto all; whisper es "
        "opcional)"),
    "cli.h_models_update": ("fetch the latest revision of the models already downloaded",
                            "baja la última revisión de los modelos ya descargados"),
    "cli.h_models_update_names": ("as in download (default: only the ones already downloaded)",
                                  "como en download (por defecto: solo los ya descargados)"),

    # ---------------------------------------------------------------- UI: general
    "ui.engine_auto_info": ("auto = the engine of each voice",
                            "auto = el motor de cada voz"),
    "ui.tab_script": ("Script → Podcast", "Guion → Podcast"),
    "ui.tab_voices": ("Voices", "Voces"),
    "ui.tab_system": ("System", "Sistema"),
    "ui.tab_settings": ("Settings", "Ajustes"),
    "ui.tagline": (
        "Markdown script → podcast with cloned voices, locally (F5-TTS / XTTS v2) or in the "
        "cloud (ElevenLabs, Azure, OpenAI)",
        "guion Markdown → podcast con voces clonadas en local (F5-TTS / XTTS v2) o en la "
        "nube (ElevenLabs, Azure, OpenAI)"),
    "ui.fallback_script": ("[voice:ana] Hello and welcome.\n", "[voz:ana] Hola y bienvenidos.\n"),
    "ui.help_md": (
        """
### Script format

| Tag | Aliases | Effect | Attributes |
|---|---|---|---|
| `[voice:name]` | `[voz:name]` | Switches speaker until the next voice tag | `lang=en\\|es\\|...`, `speed=1.1`, `engine=f5\\|xtts\\|openai\\|...` |
| `[pause:1.5]` | `[pausa:1.5]` | Silence of N seconds | — |
| `[music:path.mp3]` | `[musica:...]`, `[música:...]` | Inserts a music clip (advances the timeline) | `vol=0-1` (1.0), `fade=sec` (0) |
| `[music:path.mp3 bg]` | `background`, `fondo` | Looping background music under the voices, with *ducking* | `vol=0-1` (0.15), `fade=sec` (1.5) |
| `[music:stop]` | `fin`, `parar` | Stops the background music with a fade-out | `fade=sec` (1.5) |
| `[sfx:path.wav]` | — | One-off sound effect on top (does not advance the timeline) | `vol=0-1` (1.0) |
| `[title:...]` | `[titulo:...]`, `[título:...]` | Metadata (not spoken) | — |

- Optional *front matter* at the top: `title`, `lang`, `default_voice`, `engine`, `paragraph_pause`.
- Lines starting with `#` and `<!-- ... -->` blocks (multi-line too) are comments.
- An empty line separates paragraphs (short automatic pause).
- Music/sfx paths are relative to `examples/`, the current directory or the project (or absolute).
""",
        """
### Formato del guion

| Etiqueta | Alias | Efecto | Atributos |
|---|---|---|---|
| `[voice:nombre]` | `[voz:nombre]` | Cambia de hablante hasta la siguiente etiqueta de voz | `lang=es\\|en\\|...`, `speed=1.1`, `engine=f5\\|xtts\\|openai\\|...` |
| `[pause:1.5]` | `[pausa:1.5]` | Silencio de N segundos | — |
| `[music:ruta.mp3]` | `[musica:...]`, `[música:...]` | Inserta un clip musical (avanza el tiempo) | `vol=0-1` (1.0), `fade=seg` (0) |
| `[music:ruta.mp3 bg]` | `background`, `fondo` | Música de fondo en bucle bajo las voces, con *ducking* | `vol=0-1` (0.15), `fade=seg` (1.5) |
| `[music:stop]` | `fin`, `parar` | Detiene la música de fondo con fundido | `fade=seg` (1.5) |
| `[sfx:ruta.wav]` | — | Efecto puntual superpuesto (no avanza el tiempo) | `vol=0-1` (1.0) |
| `[title:...]` | `[titulo:...]`, `[título:...]` | Metadato (no se sintetiza) | — |

- *Front matter* opcional al principio: `title`, `lang`, `default_voice`, `engine`, `paragraph_pause`.
- Las líneas que empiezan por `#` y los bloques `<!-- ... -->` (también de varias líneas) son
  comentarios.
- Una línea vacía separa párrafos (pausa corta automática).
- Rutas de música/sfx relativas a `examples/`, al directorio actual o al proyecto (o absolutas).
"""),

    # ---------------------------------------------------------------- UI: errors
    "ui.err_script": ("Script error{where}: {msg}", "Error en el guion{where}: {msg}"),
    "ui.err_line": (" (line {line})", " (línea {line})"),
    "ui.err_assemble": ("Error assembling the episode: {exc}", "Error al montar el episodio: {exc}"),
    "ui.err_engine": ("TTS engine error: {exc}", "Error del motor TTS: {exc}"),
    "ui.err_voice": ("Voice error: {exc}", "Error de voz: {exc}"),
    "ui.err_not_implemented": ("Feature not implemented yet: {exc}",
                               "Función no implementada todavía: {exc}"),
    "ui.err_file_not_found": ("File not found: {file}", "Fichero no encontrado: {file}"),
    "ui.err_unexpected": ("Unexpected error ({type}): {exc}", "Error inesperado ({type}): {exc}"),

    # ---------------------------------------------------------------- UI: script tab
    "ui.col_no": ("#", "Nº"),
    "ui.col_type": ("Type", "Tipo"),
    "ui.col_voice": ("Voice", "Voz"),
    "ui.col_language": ("Language", "Idioma"),
    "ui.col_text": ("Text / detail", "Texto / detalle"),
    "ui.col_line": ("Line", "Línea"),
    "ui.seg_voice": ("Voice", "Voz"),
    "ui.seg_pause": ("Pause", "Pausa"),
    "ui.seg_music_stop": ("Music stop", "Fin música"),
    "ui.seg_music_bg": ("Background music", "Música de fondo"),
    "ui.seg_music": ("Music", "Música"),
    "ui.seg_sfx": ("Effect", "Efecto"),
    "ui.script_empty": ("⚠️ The script is empty.", "⚠️ El guion está vacío."),
    "ui.script_valid": (
        "✅ Valid script: **{segments}** segments, **{speech}** sentences, {chars} characters.",
        "✅ Guion válido: **{segments}** segmentos, **{speech}** frases, {chars} caracteres."),
    "ui.title": ("Title: *{title}*", "Título: *{title}*"),
    "ui.voices_used": ("**Voices used:**", "**Voces usadas:**"),
    "ui.voice_missing_dummy": ("- `{name}`: does not exist (irrelevant with the *dummy* engine)",
                               "- `{name}`: no existe (con el motor *dummy* no importa)"),
    "ui.voice_missing": ("- ⚠️ `{name}`: **DOES NOT EXIST** in {dir}",
                         "- ⚠️ `{name}`: **NO EXISTE** en {dir}"),
    "ui.provider_voice": ("provider voice '{id}'", "voz del proveedor '{id}'"),
    "ui.xtts_speaker_src": ("XTTS speaker '{speaker}'", "speaker XTTS '{speaker}'"),
    "ui.no_ref": ("⚠️ no ref.wav", "⚠️ sin ref.wav"),
    "ui.voice_line": ("- `{name}`: language {lang}, engine {engine}, {src}",
                      "- `{name}`: idioma {lang}, motor {engine}, {src}"),
    "ui.none": ("- (none)", "- (ninguna)"),
    "ui.voices_missing_hint": (
        "⚠️ {n} voice(s) missing: create them in the **Voices** tab or pick the *dummy* engine "
        "to test timings.",
        "⚠️ Faltan {n} voz/voces: créalas en la pestaña **Voces** o elige el motor *dummy* "
        "para probar tiempos."),
    "ui.license_more": ("More details in the **Settings** tab.",
                        "Más detalles en la pestaña **Ajustes**."),
    "ui.done": ("Done: {path} — duration {duration:.1f} s, generated in {elapsed:.1f} s",
                "Listo: {path} — duración {duration:.1f} s, generado en {elapsed:.1f} s"),
    "ui.log_start": (
        "Engine: {engine}. The first synthesis with F5/XTTS loads the model (it may take a "
        "while).",
        "Motor: {engine}. La primera síntesis con F5/XTTS carga el modelo (puede tardar un "
        "poco)."),
    "ui.script_not_saved": ("⚠️ The script is empty: nothing saved.",
                            "⚠️ El guion está vacío: no se guarda nada."),
    "ui.script_saved": ("💾 Script saved to `{path}`", "💾 Guion guardado en `{path}`"),
    "ui.default_script_name": ("my_script", "mi_guion"),
    "ui.default_episode_name": ("episode", "episodio"),
    "ui.lbl_script": ("Script (Markdown)", "Guion (Markdown)"),
    "ui.lbl_load_script": ("Load script (.md)", "Cargar guion (.md)"),
    "ui.lbl_save_name": ("Name to save as", "Nombre al guardar"),
    "ui.btn_save_script": ("💾 Save script", "💾 Guardar guion"),
    "ui.lbl_saved_script": ("Saved script", "Guion guardado"),
    "ui.lbl_engine": ("Engine", "Motor"),
    "ui.lbl_output_name": ("Output file name", "Nombre del fichero de salida"),
    "ui.lbl_format": ("Format", "Formato"),
    "ui.lbl_bitrate": ("Bitrate (mp3)", "Bitrate (mp3)"),
    "ui.lbl_normalize": ("Normalize loudness (-16 LUFS)", "Normalizar sonoridad (-16 LUFS)"),
    "ui.btn_validate": ("🔍 Validate", "🔍 Validar"),
    "ui.btn_generate": ("▶️ Generate", "▶️ Generar"),
    "ui.lbl_result": ("Result", "Resultado"),
    "ui.lbl_download": ("Download", "Descargar"),
    "ui.btn_open_output": ("📂 Open output folder", "📂 Abrir carpeta de salida"),
    "ui.lbl_log": ("Log", "Log"),
    "ui.lbl_segments": ("Segments", "Segmentos"),
    "ui.help_title": ("Help: format tags", "Ayuda: etiquetas del formato"),

    # ---------------------------------------------------------------- UI: voices tab
    "ui.vcol_name": ("Name", "Nombre"),
    "ui.vcol_language": ("Language", "Idioma"),
    "ui.vcol_engine": ("Engine", "Motor"),
    "ui.vcol_description": ("Description", "Descripción"),
    "ui.vcol_ref_duration": ("Ref duration (s)", "Duración ref (s)"),
    "ui.vcol_xtts_speaker": ("XTTS speaker", "Speaker XTTS"),
    "ui.vcol_provider_id": ("Provider ID", "ID proveedor"),
    "ui.vcol_speed": ("Speed", "Speed"),
    "ui.select_voice": ("Select a voice.", "Selecciona una voz."),
    "ui.voice_summary": ("**{name}** — language `{lang}`, engine `{engine}`, speed {speed:g}",
                         "**{name}** — idioma `{lang}`, motor `{engine}`, speed {speed:g}"),
    "ui.voice_xtts_speaker": ("Built-in XTTS speaker: `{speaker}`",
                              "Speaker integrado de XTTS: `{speaker}`"),
    "ui.voice_provider_id": ("Provider voice: `{id}`", "Voz del proveedor: `{id}`"),
    "ui.voice_provider_opts": ("Provider options: `{opts}`", "Opciones del proveedor: `{opts}`"),
    "ui.voice_transcript": ("Transcript: *{text}*", "Transcripción: *{text}*"),
    "ui.voice_no_transcript": ("⚠️ No transcript (ref.txt): F5-TTS needs it.",
                               "⚠️ Sin transcripción (ref.txt): F5-TTS la necesita."),
    "ui.need_name": ("⚠️ Enter a name for the voice.", "⚠️ Escribe un nombre para la voz."),
    "ui.need_provider_id": (
        "⚠️ The `{engine}` engine runs in the cloud: enter the provider's voice ID (e.g. `nova` "
        "on OpenAI, `es-ES-AlvaroNeural` on Azure).",
        "⚠️ El motor `{engine}` es en la nube: escribe el ID de la voz del proveedor (p.ej. "
        "`nova` en OpenAI, `es-ES-AlvaroNeural` en Azure)."),
    "ui.need_audio": ("⚠️ Upload or record a reference audio, or pick a built-in XTTS speaker.",
                      "⚠️ Sube o graba un audio de referencia, o elige un speaker integrado de "
                      "XTTS."),
    "ui.voice_saved": ("✅ Voice '{name}' saved to `{path}`", "✅ Voz '{name}' guardada en `{path}`"),
    "ui.voice_deleted": ("🗑️ Voice '{name}' deleted.", "🗑️ Voz '{name}' eliminada."),
    "ui.lbl_voices": ("Available voices", "Voces disponibles"),
    "ui.btn_refresh": ("🔄 Refresh", "🔄 Actualizar"),
    "ui.lbl_selected_voice": ("Selected voice", "Voz seleccionada"),
    "ui.lbl_ref_clip": ("Reference clip (ref.wav)", "Clip de referencia (ref.wav)"),
    "ui.lbl_test_engine": ("Engine for the test", "Motor para la prueba"),
    "ui.lbl_test_phrase": ("Test sentence (empty = a sentence in its language)",
                           "Frase de prueba (vacío = frase en su idioma)"),
    "ui.btn_test_voice": ("🗣️ Test voice", "🗣️ Probar voz"),
    "ui.lbl_test": ("Test", "Prueba"),
    "ui.btn_delete_voice": ("🗑️ Delete voice", "🗑️ Eliminar voz"),
    "ui.btn_confirm_delete": ("Yes, delete", "Sí, eliminar"),
    "ui.btn_cancel": ("Cancel", "Cancelar"),
    "ui.confirm_delete": ("Are you sure you want to delete **{name}**? This cannot be undone.",
                          "¿Seguro que quieres eliminar **{name}**? No se puede deshacer."),
    "ui.cancelled": ("Cancelled.", "Cancelado."),
    "ui.add_voice": ("➕ Add voice", "➕ Añadir voz"),
    "ui.lbl_new_name": ("Name (letters, digits, _ or -)", "Nombre (letras, números, _ o -)"),
    "ui.lbl_new_audio": ("Reference audio (5-15 s, no music)",
                         "Audio de referencia (5-15 s, sin música)"),
    "ui.lbl_new_text": ("Exact transcript of the clip (required by F5)",
                        "Transcripción exacta del clip (necesaria para F5)"),
    "ui.lbl_language": ("Language", "Idioma"),
    "ui.lbl_provider_id": ("Provider voice ID (e.g. `nova`, `es-ES-AlvaroNeural` or the "
                           "ElevenLabs ID)",
                           "ID de voz del proveedor (p.ej. `nova`, `es-ES-AlvaroNeural` o el ID "
                           "de ElevenLabs)"),
    "ui.lbl_description": ("Description", "Descripción"),
    "ui.lbl_speed": ("Speed", "Velocidad"),
    "ui.lbl_speaker": ("…or built-in XTTS speaker (instead of cloning; leave the audio empty)",
                       "…o speaker integrado de XTTS (en vez de clonar; deja el audio vacío)"),
    "ui.lbl_overwrite": ("Overwrite if it exists", "Sobrescribir si existe"),
    "ui.btn_save_voice": ("Save voice", "Guardar voz"),

    # ---------------------------------------------------------------- UI: system tab
    "ui.torch_missing": ("PyTorch not available: {exc}", "PyTorch no disponible: {exc}"),
    "ui.cuda_ok": (" — CUDA {version} available ✅", " — CUDA {version} disponible ✅"),
    "ui.gpu_free": (" ({free:.1f} GB free)", " ({free:.1f} GB libres)"),
    "ui.cuda_missing": (" — CUDA NOT available ⚠️ (synthesis will run on the CPU, very slowly)",
                        " — CUDA NO disponible ⚠️ (la síntesis irá por CPU, muy lenta)"),
    "ui.state_unavailable": ("not available", "no disponible"),
    "ui.state_no_key": ("no key", "sin clave"),
    "ui.state_ready": ("ready", "listo"),
    "ui.engines_info_error": ("Could not get the engine information: {exc}",
                              "No se pudo obtener la información de los motores: {exc}"),
    "ui.model_loaded": ("model loaded", "modelo cargado"),
    "ui.model_not_loaded": ("model not loaded", "modelo sin cargar"),
    "ui.no_info": ("(no information)", "(sin información)"),
    "ui.h_engines": ("### Engines", "### Motores"),
    "ui.h_paths": ("### Paths", "### Rutas"),
    "ui.path_voices": ("- Voices: `{path}` ({n} voices)", "- Voces: `{path}` ({n} voces)"),
    "ui.path_cache": ("- Synthesis cache: `{path}` ({n} sentences, {size})",
                      "- Caché de síntesis: `{path}` ({n} frases, {size})"),
    "ui.cache_disabled": ("(disabled)", "(desactivada)"),
    "ui.path_output": ("- Output: `{path}` ({n} files, {size})",
                       "- Salida: `{path}` ({n} ficheros, {size})"),
    "ui.path_scripts": ("- Saved scripts: `{path}`", "- Guiones guardados: `{path}`"),
    "ui.cache_empty": ("The cache is empty.", "La caché está vacía."),
    "ui.cache_cleared": ("🧹 Cache cleared: {n} sentences ({size}).",
                         "🧹 Caché vaciada: {n} frases ({size})."),
    "ui.open_remote": (
        "ℹ️ In remote mode the folder is not opened on the server: download the audio from "
        "this page.",
        "ℹ️ En modo remoto no se abre la carpeta en el servidor: descarga los audios desde la "
        "propia página."),
    "ui.open_mkdir_failed": ("❌ Could not create `{path}`: {exc}",
                             "❌ No se pudo crear `{path}`: {exc}"),
    "ui.open_failed": ("❌ Could not open `{path}`: {exc}", "❌ No se pudo abrir `{path}`: {exc}"),
    "ui.opened": ("📂 Opened the output folder: `{path}`",
                  "📂 Abierta la carpeta de salida: `{path}`"),
    "ui.system_hint": ("Press **Refresh** to see the system status.",
                       "Pulsa **Actualizar** para ver el estado del sistema."),
    "ui.btn_clear_cache": ("🧹 Clear synthesis cache", "🧹 Vaciar caché de síntesis"),
    "ui.lbl_output_files": ("Files in output/", "Ficheros en output/"),
    "ui.outputs_summary": ("**{n}** files in `{path}`", "**{n}** ficheros en `{path}`"),

    # ---------------------------------------------------------------- UI: settings tab
    "ui.ecol_engine": ("Engine", "Motor"),
    "ui.ecol_type": ("Type", "Tipo"),
    "ui.ecol_license": ("License", "Licencia"),
    "ui.ecol_commercial": ("Commercial use", "Uso comercial"),
    "ui.ecol_configured": ("Configured", "Configurado"),
    "ui.ecol_available": ("Available", "Disponible"),
    "ui.ecol_notes": ("Notes", "Notas"),
    "ui.kind_cloud": ("cloud", "nube"),
    "ui.kind_local": ("local", "local"),
    "ui.missing_config": ("missing {names}", "falta {names}"),
    "ui.env_file": ("File: `{path}` (ignored by git)", "Fichero: `{path}` (ignorado por git)"),
    "ui.source_env": ("environment variable", "variable de entorno"),
    "ui.key_not_set": ("- `{name}`: not set", "- `{name}`: sin definir"),
    "ui.env_priority": ("Environment variables take precedence over `.env`.",
                        "Las variables de entorno tienen prioridad sobre `.env`."),
    "ui.choose_variable": ("⚠️ Choose a variable.", "⚠️ Elige una variable."),
    "ui.enter_value": ("⚠️ Enter the value of the key.", "⚠️ Escribe el valor de la clave."),
    "ui.key_saved": ("✅ `{name}` saved to `.env` (`{shown}`).",
                     "✅ `{name}` guardada en `.env` (`{shown}`)."),
    "ui.key_env_priority": (" ⚠️ It is also set as an environment variable, which takes "
                            "precedence.",
                            " ⚠️ También está definida como variable de entorno, que tiene "
                            "prioridad."),
    "ui.key_deleted": ("🗑️ `{name}` removed from `.env`.", "🗑️ `{name}` borrada de `.env`."),
    "ui.key_absent": ("`{name}` was not in `.env`.", "`{name}` no estaba en `.env`."),
    "ui.key_env_still": (" ⚠️ It is still set as an environment variable.",
                         " ⚠️ Sigue definida como variable de entorno."),
    "ui.settings_remote": (
        "### Settings not available in remote mode\n"
        "API keys can only be managed from this computer (UI on `127.0.0.1`) or with "
        "`python -m podcast_tts config set NAME`.\n\n"
        "The **f5** (CC-BY-NC-4.0) and **xtts** (CPML) weights are for **non-commercial** "
        "use only. See `docs/COMMERCIAL_USE.md`.",
        "### Ajustes no disponibles en modo remoto\n"
        "Las claves de API solo se gestionan desde el propio equipo (UI en `127.0.0.1`) o con "
        "`python -m podcast_tts config set NOMBRE`.\n\n"
        "Los pesos de **f5** (CC-BY-NC-4.0) y **xtts** (CPML) son de uso **no comercial**. "
        "Ver `docs/COMMERCIAL_USE.md`."),
    "ui.settings_keys_intro": (
        "### Cloud engine API keys\n"
        "They are saved in the project's `.env` file (ignored by git) and are only shown "
        "masked. Local engines do not need keys.",
        "### Claves de API de los motores en la nube\n"
        "Se guardan en el fichero `.env` del proyecto (ignorado por git) y solo se muestran "
        "enmascaradas. Los motores locales no necesitan claves."),
    "ui.lbl_variable": ("Variable", "Variable"),
    "ui.lbl_value": ("Value", "Valor"),
    "ui.ph_value": ("paste the key here", "pega aquí la clave"),
    "ui.btn_save_key": ("💾 Save key", "💾 Guardar clave"),
    "ui.btn_delete_key": ("🗑️ Delete key", "🗑️ Borrar clave"),
    "ui.settings_licenses": (
        "### Engines and licenses\n"
        "The **f5** (CC-BY-NC-4.0) and **xtts** (CPML) weights are for **non-commercial** use "
        "only. For commercial use, choose a provider with a paid plan and review its terms. "
        "Cloning another person's voice requires their consent. See `docs/COMMERCIAL_USE.md`.",
        "### Motores y licencias\n"
        "Los pesos de **f5** (CC-BY-NC-4.0) y **xtts** (CPML) son de uso **no comercial**. "
        "Para uso comercial usa un proveedor con plan de pago y revisa sus términos. "
        "Clonar la voz de otra persona requiere su consentimiento. "
        "Ver `docs/COMMERCIAL_USE.md`."),
    "ui.lbl_engines": ("Engines", "Motores"),
    "ui.lang_intro": (
        "### Interface language\n"
        "English is the default. The change is saved in `.env` and **applies after restarting "
        "the app** (or the `ui` command); reloading the page is not enough.",
        "### Idioma de la interfaz\n"
        "El inglés es el idioma por defecto. El cambio se guarda en `.env` y **se aplica al "
        "reiniciar la app** (o el comando `ui`); recargar la página no basta."),
    "ui.lbl_ui_language": ("Language", "Idioma"),
    "ui.btn_save_language": ("💾 Save language", "💾 Guardar idioma"),
    "ui.lang_saved": ("✅ Language saved: **{name}**. Restart the app to apply it.",
                      "✅ Idioma guardado: **{name}**. Reinicia la app para aplicarlo."),
    "ui.lang_env_override": (
        " ⚠️ The `{env}={value}` environment variable is set and takes precedence.",
        " ⚠️ La variable de entorno `{env}={value}` está definida y tiene prioridad."),
    "ui.lang_invalid": ("⚠️ Choose a language.", "⚠️ Elige un idioma."),

    # ---------------------------------------------------------------- UI: launch / auth
    "ui.auth_bad_format": (
        "invalid authentication format: use --auth user:password (or the {env}=user:password "
        "variable)",
        "formato de autenticación inválido: usa --auth usuario:clave (o la variable "
        "{env}=usuario:clave)"),
    "ui.auth_why_share": ("with --share (public link)", "con --share (enlace público)"),
    "ui.auth_why_host": ("on --host {host}", "en --host {host}"),
    "ui.auth_required": (
        "the UI cannot be opened {why} without a user and password: anyone on the network "
        "could generate audio, delete voices or read files. Add --auth user:password (or set "
        "the {env}=user:password variable), or use --host 127.0.0.1 for local use.",
        "la UI no puede abrirse {why} sin usuario y clave: cualquiera en la red podría generar "
        "audio, borrar voces o leer ficheros. Añade --auth usuario:clave (o define la variable "
        "{env}=usuario:clave), o usa --host 127.0.0.1 para uso local."),
    "ui.auth_local_app": (
        "the app was built in local mode: use build_app(UIConfig(remote=True)) to expose it "
        "outside this computer",
        "la app se construyó en modo local: usa build_app(UIConfig(remote=True)) para "
        "exponerla fuera de este equipo"),
    "ui.h_description": ("Launch the local web UI (Gradio).",
                         "Lanza la interfaz web local (Gradio)."),
    "ui.remote_mode": (
        "Remote mode: user/password access; Settings tab disabled and only relative audio "
        "paths.",
        "Modo remoto: acceso con usuario y clave; pestaña Ajustes desactivada y solo rutas de "
        "audio relativas."),
    "ui.launching": ("Launching the UI at http://{host}:{port} (Ctrl+C to quit)",
                     "Lanzando la UI en http://{host}:{port} (Ctrl+C para salir)"),

    # ---------------------------------------------------------------- desktop app
    "desktop.already_starting": (
        "{app} is already starting. Wait a few seconds for the window to appear.",
        "{app} ya se está iniciando. Espera unos segundos a que aparezca la ventana."),
    "desktop.loading": ("Starting… the first time can take a few seconds.",
                        "Arrancando… la primera vez puede tardar unos segundos."),
    "desktop.error_title": ("Could not start {app}", "No se pudo arrancar {app}"),
    "desktop.error_hint": ("Check the environment with {check} or reinstall with {install}.",
                           "Revisa el entorno con {check} o reinstala con {install}."),
    "desktop.running_in_browser": ("{app} is running in the browser",
                                   "{app} se está ejecutando en el navegador"),
    "desktop.open_browser": ("Open browser", "Abrir navegador"),
    "desktop.close_app": ("Close {app}", "Cerrar {app}"),
    "desktop.opening_in_browser": ("{reason}\n\n{app} will open in the browser.",
                                   "{reason}\n\nSe abrirá {app} en el navegador."),
    "desktop.no_pywebview": (
        "The desktop window (pywebview) is not available: {exc}.\n"
        "Install it with: uv sync --extra desktop (or run bats\\install.bat again).",
        "No está disponible la ventana de escritorio (pywebview): {exc}.\n"
        "Instálala con: uv sync --extra desktop (o vuelve a ejecutar bats\\install.bat)."),
    "desktop.webview_failed": ("Could not open the desktop window (WebView2): {exc}",
                               "No se pudo abrir la ventana de escritorio (WebView2): {exc}"),
    "desktop.no_webview2": (
        "Microsoft Edge WebView2 Runtime is missing (it ships with up-to-date Windows 10/11; "
        "download it from https://developer.microsoft.com/microsoft-edge/webview2/).",
        "Falta Microsoft Edge WebView2 Runtime (viene con Windows 10/11 actualizados; se "
        "descarga en https://developer.microsoft.com/microsoft-edge/webview2/)."),
    "desktop.h_description": ("Open the desktop app.", "Abre la app de escritorio."),
    "desktop.h_port": ("port of the internal server (default: a free one)",
                       "puerto del servidor interno (por defecto, uno libre)"),
    "desktop.h_browser": ("do not open a native window: use the browser (as if pywebview were "
                          "missing)",
                          "no abre ventana nativa: usa el navegador (como si faltara pywebview)"),
    "desktop.h_debug": ("open the developer tools", "abre las herramientas de desarrollo"),
}

#: ``key -> {"en": ..., "es": ...}``.
CATALOG: dict[str, dict[str, str]] = {
    key: {"en": en, "es": es} for key, (en, es) in _MESSAGES.items()
}
