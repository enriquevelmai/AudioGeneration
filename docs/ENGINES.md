# TTS engines: installation and verified API (2026-10-12)

Tested environment: Windows 11 Pro, RTX 4080 SUPER 16 GB (driver 610.88, CUDA UMD 13.3),
Python 3.11.9, uv 0.12.5, ffmpeg 7.1 (chocolatey, static build). Also tested in CPU mode
(`cpu` extra).

Everything lives in a single venv (`.venv`): F5-TTS and coqui-tts coexist with the pins described below.

## 1. Installation

The supported way is `bats\install.bat` (idempotent; reuses `.venv` if it exists). It detects an NVIDIA
GPU with `nvidia-smi` and runs, depending on the case:

```powershell
uv sync --locked --python 3.11 --extra local --extra cuda --extra dev   # NVIDIA GPU (torch 2.8.0+cu126)
uv sync --locked --python 3.11 --extra local --extra cpu --extra dev    # no GPU (torch 2.8.0+cpu)
.venv\Scripts\python.exe scripts\check_env.py
```

The chosen extras are stored in `.venv\podcast-tts-extras.txt`; `bats\update.bat` reuses them and
`bats\install_gpu.bat` swaps `cpu` for `cuda` (uv only replaces torch/torchaudio).
Plain `uv sync --extra dev` installs only the core (no torch): parser, `dummy` engine, CLI, UI and
fast tests; this is what CI uses.

Layout of `pyproject.toml`:

- `dependencies` (core, no torch): numpy, pydub, gradio, pyyaml, scipy, pyloudnorm, huggingface-hub.
- `local`: f5-tts, coqui-tts, transformers<5, torch/torchaudio 2.8, soundfile.
- `cuda` / `cpu`: torch/torchaudio 2.8 with `[tool.uv.sources]` pointing to the `explicit` indexes
  `pytorch-cu126` (`download.pytorch.org/whl/cu126`) or `pytorch-cpu` (`.../whl/cpu`), and
  `[tool.uv] conflicts = [[{extra="cpu"}, {extra="cuda"}]]` (uv's official pattern for PyTorch).
  With `local` and without `cuda`/`cpu`, torch comes from PyPI (CPU on Windows).
- `dev`: pytest.
- `environments = ["sys_platform == 'win32'", "sys_platform == 'linux'"]`: Windows for real use and
  Linux for CI. The lock contains three torch variants (PyPI, `+cpu`, `+cu126`).

Re-resolving dependencies: `uv lock --python 3.11`, then `bats\update.bat` (or `uv sync` with the extras).
`uv sync` also installs the `podcast-tts` package itself in editable mode (`src/podcast_tts`) and the
`.venv\Scripts\podcast-tts.exe` executable.

Device: `podcast_tts.device.select_device()` picks `cuda` if `torch.cuda.is_available()`, otherwise
`cpu` (it logs a warning that it will be slow); `PODCAST_TTS_DEVICE=cpu|cuda|auto` forces it.

Models: they are not versioned. `podcast-tts models list|status|download|update` (`src/podcast_tts/models.py`,
depends only on `huggingface_hub`) manages them in the standard caches (HF and coqui); see the README.

### Pins and why

| Pin | Reason |
|---|---|
| `torch==2.8.*`, `torchaudio==2.8.*` (cu126) | Since torch/torchaudio 2.9, `torchaudio.load` delegates to **torchcodec**, which on Windows needs the *shared* FFmpeg DLLs (`avcodec-*.dll`...). The chocolatey ffmpeg is static, so `torchaudio.load` failed (`Could not load this library: ...libtorchcodec_core*.dll`) in F5 (`f5_tts/infer/utils_infer.py:403`) and in XTTS (`TTS/tts/models/xtts.py:84`). On top of that, coqui-tts aborts its import with torch>=2.9 if torchcodec is not available. torchaudio 2.8 uses the `soundfile` backend, with no extra native dependencies. cu126 works perfectly on the 4080 (sm_89). |
| `transformers>=4.57,<5` | coqui-tts 0.27.5 does `from transformers.pytorch_utils import isin_mps_friendly`, removed in transformers 5.x (`ImportError` when importing `TTS.api`). Works with 4.57.6. |
| `coqui-tts>=0.27,<0.28` | Fork maintained by idiap; supports py3.11 and XTTS v2. |
| `[tool.uv] constraint-dependencies = ["datasets>=4"]` | Without it, `uv lock` fell back to datasets 2.14.4 (2023), incompatible with modern fsspec (f5-tts imports `datasets`). |

`torchcodec 0.17.0` stays installed because f5-tts declares it as a dependency, but with torch 2.8 nothing
imports it at runtime. Leave it alone.

### Final versions (key packages, `uv pip freeze`)

```
torch==2.8.0+cu126
torchaudio==2.8.0+cu126
torchcodec==0.17.0          (installed, not used)
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

Reference script: `scripts/smoke_f5.py`.

```python
from importlib.resources import files
from f5_tts.api import F5TTS

tts = F5TTS(model="F5TTS_v1_Base", device="cuda")
wav, sr, spec = tts.infer(
    ref_file=str(files("f5_tts").joinpath("infer/examples/basic/basic_ref_en.wav")),
    ref_text="Some call me nature, others call me mother nature.",
    gen_text="Hola, bienvenidos a este podcast generado localmente.",
    nfe_step=32, speed=1.0, seed=42,
    file_wave="output/smoke_f5_es.wav",      # optional: writes the WAV with soundfile
    show_info=lambda *a, **k: None,          # silences the internal prints
)
# wav: np.ndarray float32 mono; sr: int = 24000; spec: np.ndarray (mel)
```

Signatures (read from `.venv/Lib/site-packages/f5_tts/api.py`):

```python
F5TTS(model="F5TTS_v1_Base", ckpt_file="", vocab_file="", ode_method="euler", use_ema=True,
      vocoder_local_path=None, device=None, hf_cache_dir=None)

F5TTS.infer(ref_file, ref_text, gen_text, show_info=print, progress=tqdm, target_rms=0.1,
            cross_fade_duration=0.15, sway_sampling_coef=-1, cfg_strength=2, nfe_step=32,
            speed=1.0, fix_duration=None, remove_silence=False, file_wave=None, file_spec=None,
            seed=None) -> (wav, sr, spec)

F5TTS.export_wav(wav, file_wave, remove_silence=False)
F5TTS.transcribe(ref_audio, language=None)   # Whisper, see below
F5TTS.target_sample_rate                      # 24000
```

- Available models (`f5_tts/configs/*.yaml`): `F5TTS_v1_Base` (default, recommended), `F5TTS_Base`,
  `E2TTS_Base`, `F5TTS_Small`, `F5TTS_v1_Small`, `E2TTS_Small`.
- **Output sample rate: 24000 Hz, mono, float32.**
- Reference audio bundled with the package: `f5_tts/infer/examples/basic/basic_ref_en.wav`
  (text: "Some call me nature, others call me mother nature.") and `basic_ref_zh.wav`.
- `ref_text=""` -> transcribes the reference automatically with `openai/whisper-large-v3-turbo`
  (transformers pipeline; downloads ~1.6 GB the first time). Better to always pass the text.
  **Watch out on Windows**: the transformers ASR pipeline imports **torchcodec** to decode the audio
  when given a path, and fails with `WinError 127` (missing shared FFmpeg DLLs).
  `src/podcast_tts/engines/f5.py` (`_transcribe_reference`) avoids this: it preprocesses the clip with F5
  (trimmed to ~12 s), passes it to the pipeline as a numpy array (`{"raw": ..., "sampling_rate": ...}`) with
  `is_torchcodec_available` forced to `False`, and caches the transcription in memory per clip
  (path + size + mtime). If it still fails, it asks you to write the transcription into `ref.txt`.
- The reference is trimmed to ~12 s (`preprocess_ref_audio_text`); use 5-10 s references.
- Long text is split internally into batches (`infer_process` -> `chunk_text`) and joined with a crossfade.
- The base model is trained on **English and Chinese**: Spanish comes out intelligible but accented.
  For native Spanish there is the community finetune `jpgallegoar/F5-Spanish` (license **CC-BY-NC-4.0**,
  `F5TTS_Base` architecture), tested and working:

  ```python
  from cached_path import cached_path
  ckpt  = str(cached_path("hf://jpgallegoar/F5-Spanish/model_1250000.safetensors"))
  vocab = str(cached_path("hf://jpgallegoar/F5-Spanish/vocab.txt"))
  tts_es = F5TTS(model="F5TTS_Base", ckpt_file=ckpt, vocab_file=vocab, device="cuda")
  ```

  Test output: `output/smoke_f5_spanish_ft_es.wav`.

Model cache (Hugging Face hub, `~/.cache/huggingface/hub`; change it with `HF_HOME` or `hf_cache_dir=`):

- `models--SWivid--F5-TTS` (1.3 GB; `F5TTS_v1_Base/model_1250000.safetensors`)
- `models--charactr--vocos-mel-24khz` (52 MB, vocoder)
- `models--jpgallegoar--F5-Spanish` (optional, ~1.3 GB)

Measured times (RTX 4080 SUPER, model already cached, `nfe_step=32`):

| Case | Audio | Time | RTF |
|---|---|---|---|
| Load `F5TTS_v1_Base` | - | 2.6-2.8 s | - |
| es (base model) | 7.71 s | 1.43-1.70 s | ~0.19-0.22 |
| en (base model) | 7.81 s | 1.00 s | ~0.13 |
| es (F5-Spanish finetune) | 7.71 s | 1.15 s | ~0.15 |

F5 peak VRAM: ~2 GB.

## 3. XTTS v2 (`coqui-tts` 0.27.5, idiap fork)

Reference script: `scripts/smoke_xtts.py`.

```python
import os
os.environ["COQUI_TOS_AGREED"] = "1"     # BEFORE loading the model; accepts the CPML license without a prompt
from TTS.api import TTS

tts = TTS("tts_models/multilingual/multi-dataset/xtts_v2", progress_bar=False).to("cuda")
sr = tts.synthesizer.output_sample_rate     # 24000
tts.speakers                                 # list of 58 built-in speakers
tts.languages                                # ['en','es','fr','de','it','pt','pl','tr','ru','nl','cs','ar','zh-cn','hu','ko','ja','hi']

# Built-in speaker
tts.tts_to_file(text="Hola, bienvenidos.", speaker="Ana Florence", language="es",
                file_path="output/smoke_xtts_es.wav")

# Cloning from a WAV (one reference WAV or a list of them, 6-15 s)
tts.tts_to_file(text="Hola, bienvenidos.", speaker_wav="voices/ana.wav", language="es",
                file_path="output/clone.wav")

# In memory: returns list[np.float32] (mono, 24 kHz); extra kwargs are passed to Xtts.inference
wav = tts.tts(text="...", speaker="Claribel Dervla", language="es", speed=1.2, temperature=0.65)
```

Signatures (`.venv/Lib/site-packages/TTS/api.py`):

```python
TTS(model_name="", *, model_path=None, config_path=None, vocoder_name=None, vocoder_path=None,
    vocoder_config_path=None, encoder_path=None, encoder_config_path=None, speakers_file_path=None,
    language_ids_file_path=None, progress_bar=True, gpu=False)        # use .to("cuda") instead of gpu=
TTS.tts(text, speaker=None, language=None, speaker_wav=None, emotion=None,
        split_sentences=True, **kwargs) -> list[float]
TTS.tts_to_file(text, speaker=None, language=None, speaker_wav=None, emotion=None, pipe_out=None,
                file_path="output.wav", split_sentences=True, **kwargs) -> str
```

Useful kwargs (from `Xtts.inference`): `temperature=0.75, length_penalty=1.0, repetition_penalty=10.0,
top_k=50, top_p=0.85, do_sample=True, speed=1.0`. `speed=` and `temperature=` verified.

Low level: `tts.synthesizer.tts_model` is `Xtts`; the latents of each built-in speaker are in
`tts.synthesizer.tts_model.speaker_manager.speakers[name]` -> `{"gpt_cond_latent", "speaker_embedding"}`.

- **Output sample rate: 24000 Hz, mono.**
- Character limit per sentence: `es` 239, `en` 250 (warns when exceeded). With `split_sentences=True`
  (the default) the text is split into sentences; short paragraphs work best.
- Model cache: `%LOCALAPPDATA%\tts\tts_models--multilingual--multi-dataset--xtts_v2` (1.8 GB)
  (`<TTS_HOME>\tts\...` if `TTS_HOME` is set, or `XDG_DATA_HOME`). `podcast-tts models download xtts`
  fetches the same 5 files from the HF repo `coqui/XTTS-v2` into that folder with `huggingface_hub`; on load,
  coqui sees a correct `hash.md5` and does not download again.
- Model license: Coqui Public Model License (CPML, non-commercial use).

Built-in speakers (58, in the order returned by `tts.speakers`):

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

Measured times (RTX 4080 SUPER):

| Case | Audio | Time | RTF |
|---|---|---|---|
| Model load (first time, includes the 1.8 GB download) | - | 28.6 s | - |
| Model load (cached) | - | 9.4 s | - |
| es, "Ana Florence" | 6.1-9.8 s | 2.1-3.3 s | ~0.34 |
| en, "Ana Florence" | 5.8-6.6 s | 1.7-1.9 s | ~0.29 |
| es, cloning `basic_ref_en.wav` | 8.9 s | 3.2 s | ~0.36 |

XTTS is stochastic (`do_sample=True`): the duration varies between runs.

## 4. Windows gotchas

1. **cp1252 console and Unicode**: `print()` of names like `Eugenio Mataracı` raises
   `UnicodeEncodeError: 'charmap' codec can't encode character '\u0131'` when stdout is a pipe
   (stdout.encoding = cp1252). Run with `PYTHONIOENCODING=utf-8` (or `PYTHONUTF8=1`), or call
   `sys.stdout.reconfigure(encoding="utf-8")` in the entry point. The `.bat` files in `bats/` and the skill wrappers export both variables.
2. **torchaudio >= 2.9 / torchcodec**: see the pins table. Do not upgrade torch beyond 2.8 unless the
   shared FFmpeg DLLs are installed ("shared" build on the PATH) or `torchaudio.load` is replaced
   with `soundfile`.
3. **espeak-ng is not needed**: neither XTTS v2 (own BPE tokenizer) nor F5-TTS (characters / pinyin)
   uses it. Only other phoneme-based Coqui models (VITS...) would need it, and we do not use them.
4. **XTTS license**: without `COQUI_TOS_AGREED=1` the first load asks for confirmation via `input()` and
   hangs in non-interactive processes (Gradio, scripts). Set it before instantiating `TTS(...)`.
5. **F5 temporary files**: on Python 3.11 `preprocess_ref_audio_text` creates temporary WAVs with
   `delete=False` in `%TEMP%` and does not delete them (it caches by reference path in memory).
6. **ffmpeg**: pydub needs it for mp3/ogg; the chocolatey one (`C:\ProgramData\chocolatey\bin\ffmpeg.exe`)
   works. torchaudio 2.8 does not need it (it uses soundfile).
7. **Noisy warnings**: `torch.jit.script is deprecated`, torchaudio warnings and transformers warnings
   (GPT2InferenceModel / `generate`) are harmless; run with `-W ignore` or filter them with `warnings`.
8. **Both models in VRAM at once**: F5 (~2 GB) + XTTS (~2-3 GB) fit comfortably in 16 GB; the app can
   keep both loaded at the same time.
9. **Edge-TTS / SAPI voices**: the project neither uses nor installs them. Microsoft's official option
   is the `azure` engine (Azure AI Speech, paid).
10. **RTX 50 GPUs (Blackwell, sm_120)**: the PyTorch 2.8 cu126 wheels do not include sm_120. For these
    GPUs use the `https://download.pytorch.org/whl/cu128` index (change `pytorch-cu126` in
    `pyproject.toml`, run `uv lock --python 3.11` and reinstall) or, in the meantime, the CPU variant.

## 5. Scripts

- `bats/install.bat`, `bats/update.bat`, `bats/install_gpu.bat`: installation, update and switching
  from CPU to CUDA (see section 1).
- `bats/run.bat` (desktop app; falls back to the browser if pywebview is missing), `bats/run_web.bat` (browser),
  `bats/create_shortcuts.bat` (Desktop and Start menu shortcuts) and `bats/build_launcher.bat`
  (builds `AudioGeneration.exe`).
- `scripts/setup.ps1`: kept for compatibility; calls `bats\install.bat /y` (`-Smoke` generates the test WAVs; `-Recreate` rebuilds `.venv`).
- `scripts/check_env.py`: checks by layer (core, `local`, `cuda`/`cpu`): Python 3.11, ffmpeg, core packages,
  that the core does not import torch and, if the `local` extra is present, torch 2.8, the torchaudio backend, CUDA and
  the imports of both engines. Exit 0 if what is installed is consistent (core only is fine too), 1 otherwise. Downloads nothing.
- `scripts/smoke_f5.py`: generates `output/smoke_f5_es.wav` and `output/smoke_f5_en.wav`.
- `scripts/smoke_xtts.py`: generates `output/smoke_xtts_es.wav` and `output/smoke_xtts_en.wav` and lists the speakers.
