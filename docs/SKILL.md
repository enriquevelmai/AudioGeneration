# Claude Code skill `podcast-tts`

The skill that lets Claude Code generate podcasts with this project is versioned in
`skill/podcast-tts/`:

```
skill/podcast-tts/
├── SKILL.md                      # instructions + front matter (name, description)
├── references/script-format.md   # full script format and 3 examples
└── scripts/
    ├── generate.ps1              # CLI wrapper for PowerShell
    ├── generate.sh               # CLI wrapper for Git Bash (and Linux)
    ├── generar.ps1               # compatibility wrapper, forwards to generate.ps1
    └── generar.sh                # compatibility wrapper, forwards to generate.sh
```

`generar.ps1` / `generar.sh` are the old names, kept as thin wrappers so older references keep
working; new references should use `generate.*`.

The skill is portable: it contains no user-specific paths. The wrappers find the project root in
this order:

1. the `PODCAST_TTS_HOME` environment variable;
2. the target of the `%USERPROFILE%\.claude\skills\podcast-tts` junction (`<repo>\skill\podcast-tts` -> `<repo>`);
3. the relative path `../../..` from the script itself (when run inside the repository).

They then set `PYTHONUTF8`, `PYTHONIOENCODING` and `COQUI_TOS_AGREED`, and run
`<repo>\.venv\Scripts\python.exe -m podcast_tts <arguments>`. `generate.ps1 --where` /
`generate.sh --where` print the root that was found.

## Installation

`bats\install.bat` offers to install it if `%USERPROFILE%\.claude` exists (that is, if you use Claude Code).
By hand:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install_skill.ps1          # junction (idempotent)
powershell -ExecutionPolicy Bypass -File scripts\install_skill.ps1 -Copy    # copy, if a junction is not possible
```

By default it creates a directory **junction** (no administrator rights needed):

```
%USERPROFILE%\.claude\skills\podcast-tts  ->  <repo>\skill\podcast-tts
```

Because it is a junction, any change in the repository's `skill/podcast-tts/` is reflected immediately
in Claude Code (in new sessions), and the wrappers find the project by following the link.

The script does nothing if the junction is already correct, recreates it if it points elsewhere
(unless `-NoReplace` is given, which the installer uses in `/y` mode) and, if it finds a regular
folder (an old copy), renames it to `podcast-tts.bak-<date>` before linking.

With `-Copy` it copies the folder and, since a copy does not know where the project is, it also sets
the `PODCAST_TTS_HOME` user variable to the repository root. You need to run it again after every
change to the skill.

If you move the repository, run the script again (or update `PODCAST_TTS_HOME`).

Uninstall: `cmd /c rmdir %USERPROFILE%\.claude\skills\podcast-tts` (removes only the link).
