# Motores TTS: instalación y API verificada (2026-10-12)

Entorno probado: Windows 11 Pro, RTX 4080 SUPER 16 GB (driver 610.88, CUDA UMD 13.3),
Python 3.11.9, uv 0.12.5, ffmpeg 7.1 (chocolatey, build estática). También probado en modo CPU
(extra `cpu`).

Todo está en un único venv (`.venv`): **no hace falta `.venv-xtts`**. F5-TTS y coqui-tts conviven
con los pins descritos abajo.

## 1. Instalación

La forma soportada es `bats\install.bat` (idempotente; reutiliza `.venv` si existe). Detecta GPU
NVIDIA con `nvidia-smi` y ejecuta, según el caso:

```powershell
uv sync --locked --python 3.11 --extra local --extra cuda --extra dev   # GPU NVIDIA (torch 2.8.0+cu126)
uv sync --locked --python 3.11 --extra local --extra cpu --extra dev    # sin GPU (torch 2.8.0+cpu)
.venv\Scripts\python.exe scripts\check_env.py
```

Los extras elegidos quedan en `.venv\podcast-tts-extras.txt`; `bats\update.bat` los reutiliza y
`bats\install_gpu.bat` cambia `cpu` por `cuda` (uv solo sustituye torch/torchaudio).
`uv sync --extra dev` a secas instala solo el núcleo (sin torch): parser, motor `dummy`, CLI, UI y
tests rápidos; es lo que usa la CI.

Estructura de `pyproject.toml`:

- `dependencies` (núcleo, sin torch): numpy, pydub, gradio, pyyaml, scipy, pyloudnorm, huggingface-hub.
- `local`: f5-tts, coqui-tts, transformers<5, torch/torchaudio 2.8, soundfile.
- `cuda` / `cpu`: torch/torchaudio 2.8 con `[tool.uv.sources]` apuntando a los índices `explicit`
  `pytorch-cu126` (`download.pytorch.org/whl/cu126`) o `pytorch-cpu` (`.../whl/cpu`), y
  `[tool.uv] conflicts = [[{extra="cpu"}, {extra="cuda"}]]` (patrón oficial de uv para PyTorch).
  Con `local` y sin `cuda`/`cpu`, torch viene de PyPI (CPU en Windows).
- `dev`: pytest.
- `environments = ["sys_platform == 'win32'", "sys_platform == 'linux'"]`: Windows para el uso real y
  Linux para la CI. El lock contiene tres variantes de torch (PyPI, `+cpu`, `+cu126`).

Re-resolver dependencias: `uv lock --python 3.11` y luego `bats\update.bat` (o `uv sync` con los extras).
`uv sync` instala además el propio paquete `podcast-tts` en modo editable (`src/podcast_tts`) y el
ejecutable `.venv\Scripts\podcast-tts.exe`.

Dispositivo: `podcast_tts.device.select_device()` elige `cuda` si `torch.cuda.is_available()` y si no
`cpu` (avisa por logging de que irá lento); `PODCAST_TTS_DEVICE=cpu|cuda|auto` lo fuerza.

Modelos: no se versionan. `podcast-tts models list|status|download|update` (`src/podcast_tts/models.py`,
solo depende de `huggingface_hub`) los gestiona en las cachés estándar (HF y coqui); ver README.

### Pins y por qué

| Pin | Motivo |
|---|---|
| `torch==2.8.*`, `torchaudio==2.8.*` (cu126) | Desde torch/torchaudio 2.9, `torchaudio.load` delega en **torchcodec**, que en Windows necesita las DLL *compartidas* de FFmpeg (`avcodec-*.dll`...). El ffmpeg de chocolatey es estático, así que `torchaudio.load` fallaba (`Could not load this library: ...libtorchcodec_core*.dll`) en F5 (`f5_tts/infer/utils_infer.py:403`) y en XTTS (`TTS/tts/models/xtts.py:84`). Además coqui-tts aborta el import con torch>=2.9 si torchcodec no está disponible. torchaudio 2.8 usa el backend `soundfile`, sin dependencias nativas extra. cu126 funciona perfectamente en la 4080 (sm_89). |
| `transformers>=4.57,<5` | coqui-tts 0.27.5 hace `from transformers.pytorch_utils import isin_mps_friendly`, eliminado en transformers 5.x (`ImportError` al importar `TTS.api`). Con 4.57.6 funciona. |
| `coqui-tts>=0.27,<0.28` | Fork mantenido por idiap, soporta py3.11 y XTTS v2. |
| `[tool.uv] constraint-dependencies = ["datasets>=4"]` | Sin esto, `uv lock` retrocedía a datasets 2.14.4 (2023), incompatible con fsspec moderno (f5-tts importa `datasets`). |

`torchcodec 0.17.0` queda instalado porque f5-tts lo declara como dependencia, pero con torch 2.8 nadie
lo importa en runtime. No hay que tocarlo.

### Versiones finales (paquetes clave, `uv pip freeze`)

```
torch==2.8.0+cu126
torchaudio==2.8.0+cu126
torchcodec==0.17.0          (instalado, no usado)
f5-tts==1.1.22
coqui-tts==0.27.5
coqui-tts-trainer==0.3.3
transformers==4.57.6
tokenizers==0.22.2
huggingface-hub==0.36.2
accelerate==1.15.0
vocos==0.1.0
x-transformers==2.31.7
cached-path==1.8.10
librosa==0.11.0
gradio==6.17.3
pydub==0.25.1
soundfile==0.14.0
numpy==2.4.6
scipy==1.17.1
pytest==9.1.1
```

`torch.cuda.is_available()` -> `True`, `torch.cuda.get_device_name(0)` -> `NVIDIA GeForce RTX 4080 SUPER`,
`torch.version.cuda` -> `12.6`.

## 2. F5-TTS (`f5-tts` 1.1.22)

Script de referencia: `scripts/smoke_f5.py`.

```python
from importlib.resources import files
from f5_tts.api import F5TTS

tts = F5TTS(model="F5TTS_v1_Base", device="cuda")
wav, sr, spec = tts.infer(
    ref_file=str(files("f5_tts").joinpath("infer/examples/basic/basic_ref_en.wav")),
    ref_text="Some call me nature, others call me mother nature.",
    gen_text="Hola, bienvenidos a este podcast generado localmente.",
    nfe_step=32, speed=1.0, seed=42,
    file_wave="output/smoke_f5_es.wav",      # opcional: escribe el WAV con soundfile
    show_info=lambda *a, **k: None,          # silencia los prints internos
)
# wav: np.ndarray float32 mono; sr: int = 24000; spec: np.ndarray (mel)
```

Firmas (leídas de `.venv/Lib/site-packages/f5_tts/api.py`):

```python
F5TTS(model="F5TTS_v1_Base", ckpt_file="", vocab_file="", ode_method="euler", use_ema=True,
      vocoder_local_path=None, device=None, hf_cache_dir=None)

F5TTS.infer(ref_file, ref_text, gen_text, show_info=print, progress=tqdm, target_rms=0.1,
            cross_fade_duration=0.15, sway_sampling_coef=-1, cfg_strength=2, nfe_step=32,
            speed=1.0, fix_duration=None, remove_silence=False, file_wave=None, file_spec=None,
            seed=None) -> (wav, sr, spec)

F5TTS.export_wav(wav, file_wave, remove_silence=False)
F5TTS.transcribe(ref_audio, language=None)   # Whisper, ver abajo
F5TTS.target_sample_rate                      # 24000
```

- Modelos disponibles (`f5_tts/configs/*.yaml`): `F5TTS_v1_Base` (por defecto, recomendado), `F5TTS_Base`,
  `E2TTS_Base`, `F5TTS_Small`, `F5TTS_v1_Small`, `E2TTS_Small`.
- **Sample rate de salida: 24000 Hz, mono, float32.**
- Audios de referencia del paquete: `f5_tts/infer/examples/basic/basic_ref_en.wav`
  (texto: "Some call me nature, others call me mother nature.") y `basic_ref_zh.wav`.
- `ref_text=""` -> transcribe la referencia automáticamente con `openai/whisper-large-v3-turbo`
  (pipeline de transformers; descarga ~1.6 GB la primera vez). Mejor pasar siempre el texto.
  **Ojo en Windows**: el pipeline ASR de transformers importa **torchcodec** para decodificar el audio
  cuando se le pasa una ruta, y falla con `WinError 127` (faltan las DLL compartidas de FFmpeg).
  `src/podcast_tts/engines/f5.py` (`_transcribe_reference`) lo evita: preprocesa el clip con F5
  (recorte a ~12 s), lo pasa al pipeline como array numpy (`{"raw": ..., "sampling_rate": ...}`) con
  `is_torchcodec_available` forzado a `False` y cachea la transcripción en memoria por clip
  (ruta + tamaño + mtime). Si aun así falla, pide escribir la transcripción en `ref.txt`.
- La referencia se recorta a ~12 s (`preprocess_ref_audio_text`); usar referencias de 5-10 s.
- El texto largo se trocea internamente en lotes (`infer_process` -> `chunk_text`) y se concatena con crossfade.
- El modelo base está entrenado en **inglés y chino**: el castellano sale inteligible pero con acento.
  Para castellano nativo existe el finetune comunitario `jpgallegoar/F5-Spanish` (licencia **CC-BY-NC-4.0**,
  arquitectura `F5TTS_Base`), probado y funcionando:

  ```python
  from cached_path import cached_path
  ckpt  = str(cached_path("hf://jpgallegoar/F5-Spanish/model_1250000.safetensors"))
  vocab = str(cached_path("hf://jpgallegoar/F5-Spanish/vocab.txt"))
  tts_es = F5TTS(model="F5TTS_Base", ckpt_file=ckpt, vocab_file=vocab, device="cuda")
  ```

  Salida de prueba: `output/smoke_f5_spanish_ft_es.wav`.

Caché de modelos (Hugging Face hub, `~/.cache/huggingface/hub`, se cambia con `HF_HOME` o `hf_cache_dir=`):

- `models--SWivid--F5-TTS` (1.3 GB; `F5TTS_v1_Base/model_1250000.safetensors`)
- `models--charactr--vocos-mel-24khz` (52 MB, vocoder)
- `models--jpgallegoar--F5-Spanish` (opcional, ~1.3 GB)

Tiempos medidos (RTX 4080 SUPER, modelo ya en caché, `nfe_step=32`):

| Caso | Audio | Tiempo | RTF |
|---|---|---|---|
| Carga `F5TTS_v1_Base` | - | 2.6-2.8 s | - |
| es (modelo base) | 7.71 s | 1.43-1.70 s | ~0.19-0.22 |
| en (modelo base) | 7.81 s | 1.00 s | ~0.13 |
| es (finetune F5-Spanish) | 7.71 s | 1.15 s | ~0.15 |

VRAM pico de F5: ~2 GB.

## 3. XTTS v2 (`coqui-tts` 0.27.5, fork idiap)

Script de referencia: `scripts/smoke_xtts.py`.

```python
import os
os.environ["COQUI_TOS_AGREED"] = "1"     # ANTES de cargar el modelo; acepta la licencia CPML sin prompt
from TTS.api import TTS

tts = TTS("tts_models/multilingual/multi-dataset/xtts_v2", progress_bar=False).to("cuda")
sr = tts.synthesizer.output_sample_rate     # 24000
tts.speakers                                 # lista de 58 speakers integrados
tts.languages                                # ['en','es','fr','de','it','pt','pl','tr','ru','nl','cs','ar','zh-cn','hu','ko','ja','hi']

# Speaker integrado
tts.tts_to_file(text="Hola, bienvenidos.", speaker="Ana Florence", language="es",
                file_path="output/smoke_xtts_es.wav")

# Clonación desde WAV (uno o lista de WAVs de referencia, 6-15 s)
tts.tts_to_file(text="Hola, bienvenidos.", speaker_wav="voices/ana.wav", language="es",
                file_path="output/clone.wav")

# En memoria: devuelve list[np.float32] (mono, 24 kHz); los kwargs extra llegan a Xtts.inference
wav = tts.tts(text="...", speaker="Claribel Dervla", language="es", speed=1.2, temperature=0.65)
```

Firmas (`.venv/Lib/site-packages/TTS/api.py`):

```python
TTS(model_name="", *, model_path=None, config_path=None, vocoder_name=None, vocoder_path=None,
    vocoder_config_path=None, encoder_path=None, encoder_config_path=None, speakers_file_path=None,
    language_ids_file_path=None, progress_bar=True, gpu=False)        # usar .to("cuda") en vez de gpu=
TTS.tts(text, speaker=None, language=None, speaker_wav=None, emotion=None,
        split_sentences=True, **kwargs) -> list[float]
TTS.tts_to_file(text, speaker=None, language=None, speaker_wav=None, emotion=None, pipe_out=None,
                file_path="output.wav", split_sentences=True, **kwargs) -> str
```

kwargs útiles (de `Xtts.inference`): `temperature=0.75, length_penalty=1.0, repetition_penalty=10.0,
top_k=50, top_p=0.85, do_sample=True, speed=1.0`. `speed=` y `temperature=` verificados.

Bajo nivel: `tts.synthesizer.tts_model` es `Xtts`; los latentes de cada speaker integrado están en
`tts.synthesizer.tts_model.speaker_manager.speakers[name]` -> `{"gpt_cond_latent", "speaker_embedding"}`.

- **Sample rate de salida: 24000 Hz, mono.**
- Límite de caracteres por frase: `es` 239, `en` 250 (avisa si se excede). Con `split_sentences=True`
  (por defecto) el texto se trocea por frases; conviene pasar párrafos cortos.
- Caché del modelo: `%LOCALAPPDATA%\tts\tts_models--multilingual--multi-dataset--xtts_v2` (1.8 GB),
  (`<TTS_HOME>\tts\...` si se define `TTS_HOME`, o `XDG_DATA_HOME`). `podcast-tts models download xtts`
  baja los mismos 5 ficheros del repo HF `coqui/XTTS-v2` a esa carpeta con `huggingface_hub`; al cargar,
  coqui ve `hash.md5` correcto y no vuelve a descargar.
- Licencia del modelo: Coqui Public Model License (CPML, uso no comercial).

Speakers integrados (58, en el orden que devuelve `tts.speakers`):

```
Claribel Dervla, Daisy Studious, Gracie Wise, Tammie Ema, Alison Dietlinde, Ana Florence,
Annmarie Nele, Asya Anara, Brenda Stern, Gitta Nikolina, Henriette Usha, Sofia Hellen, Tammy Grit,
Tanja Adelina, Vjollca Johnnie, Andrew Chipper, Badr Odhiambo, Dionisio Schuyler, Royston Min,
Viktor Eka, Abrahan Mack, Adde Michal, Baldur Sanjin, Craig Gutsy, Damien Black, Gilberto Mathias,
Ilkin Urbano, Kazuhiko Atallah, Ludvig Milivoj, Suad Qasim, Torcull Diarmuid, Viktor Menelaos,
Zacharie Aimilios, Nova Hogarth, Maja Ruoho, Uta Obando, Lidiya Szekeres, Chandra MacFarland,
Szofi Granger, Camilla Holmström, Lilya Stainthorpe, Zofija Kendrick, Narelle Moon, Barbora MacLean,
Alexandra Hisakawa, Alma María, Rosemary Okafor, Ige Behringer, Filip Traverse, Damjan Chapman,
Wulf Carlevaro, Aaron Dreschner, Kumar Dahl, Eugenio Mataracı, Ferran Simen, Xavier Hayasaka,
Luis Moray, Marcos Rudaski
```

Tiempos medidos (RTX 4080 SUPER):

| Caso | Audio | Tiempo | RTF |
|---|---|---|---|
| Carga del modelo (1a vez, incluye descarga de 1.8 GB) | - | 28.6 s | - |
| Carga del modelo (en caché) | - | 9.4 s | - |
| es, "Ana Florence" | 6.1-9.8 s | 2.1-3.3 s | ~0.34 |
| en, "Ana Florence" | 5.8-6.6 s | 1.7-1.9 s | ~0.29 |
| es, clonando `basic_ref_en.wav` | 8.9 s | 3.2 s | ~0.36 |

XTTS es estocástico (`do_sample=True`): la duración varía entre ejecuciones.

## 4. Gotchas de Windows

1. **Consola cp1252 y Unicode**: `print()` de nombres como `Eugenio Mataracı` lanza
   `UnicodeEncodeError: 'charmap' codec can't encode character '\u0131'` cuando stdout es una tubería
   (stdout.encoding = cp1252). Ejecutar con `PYTHONIOENCODING=utf-8` (o `PYTHONUTF8=1`), o hacer
   `sys.stdout.reconfigure(encoding="utf-8")` en el entrypoint. Los `.bat` de `bats/` y los wrappers de la skill exportan ambas variables.
2. **torchaudio >= 2.9 / torchcodec**: ver la tabla de pins. No subir torch por encima de 2.8 salvo que se
   instalen las DLL compartidas de FFmpeg (build "shared" en el PATH) o se sustituya `torchaudio.load`
   por `soundfile`.
3. **espeak-ng no es necesario**: ni XTTS v2 (tokenizador BPE propio) ni F5-TTS (caracteres / pinyin)
   lo usan. Solo lo necesitarían otros modelos Coqui con fonemas (VITS...), que no usamos.
4. **Licencia XTTS**: sin `COQUI_TOS_AGREED=1` la primera carga pide confirmación por `input()` y se
   cuelga en procesos no interactivos (Gradio, scripts). Definirla antes de instanciar `TTS(...)`.
5. **Ficheros temporales de F5**: en Python 3.11 `preprocess_ref_audio_text` crea WAV temporales con
   `delete=False` en `%TEMP%` y no los borra (cachea por ruta de referencia en memoria).
6. **ffmpeg**: pydub lo necesita para mp3/ogg; el de chocolatey (`C:\ProgramData\chocolatey\bin\ffmpeg.exe`)
   vale. torchaudio 2.8 no lo necesita (usa soundfile).
7. **Warnings ruidosos**: `torch.jit.script is deprecated`, avisos de torchaudio y de transformers
   (GPT2InferenceModel / `generate`) son inofensivos; ejecutar con `-W ignore` o filtrarlos con `warnings`.
8. **Ambos modelos en VRAM a la vez**: F5 (~2 GB) + XTTS (~2-3 GB) caben de sobra en 16 GB; se pueden
   mantener cargados simultáneamente en la app.
9. **Edge-TTS / voces Microsoft**: bloqueadas; no se instalan ni se usan.

## 5. Scripts

- `bats/install.bat`, `bats/update.bat`, `bats/install_gpu.bat`, `bats/run.bat`: instalación, actualización,
  cambio CPU -> CUDA y arranque de la UI (ver sección 1).
- `scripts/setup.ps1`: compatibilidad; llama a `bats\install.bat /y` (`-Smoke` genera los WAV de prueba; `-Recreate` rehace `.venv`).
- `scripts/check_env.py`: verifica por capas (núcleo, `local`, `cuda`/`cpu`): Python 3.11, ffmpeg, paquetes del núcleo,
  que el núcleo no importe torch y, si está el extra `local`, torch 2.8, backend de torchaudio, CUDA e imports de
  ambos motores. Exit 0 si lo instalado es coherente (solo núcleo también vale), 1 si no. No descarga nada.
- `scripts/smoke_f5.py`: genera `output/smoke_f5_es.wav` y `output/smoke_f5_en.wav`.
- `scripts/smoke_xtts.py`: genera `output/smoke_xtts_es.wav` y `output/smoke_xtts_en.wav` y lista los speakers.
