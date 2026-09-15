# Let Me Make Your Life Easier v2.2 Extended

Desktop app (Tkinter) that pulls today's merged/in-progress GitLab issues per team member,
reads a local sentiment file, and uses a local Ollama model to draft:

1. Per-person daily progress updates (MERGED / IN PROGRESS, plain text).
2. A team CPO sprint status update (SPRINT STATUS / PROGRESS / TEAM SENTIMENT / BLOCKERS).

## Run from source

```
pip install -r requirements.txt   (none required - stdlib only, tkinter ships with Python)
python app.py
```

## First run

Click **Settings**:
- GitLab URL (e.g. https://gitlab.com) and **your own** personal access token
  (read_api scope is enough). This is saved only to a local file on your machine:
  `%LOCALAPPDATA%\OnpliaProgressApp\config.json` — never sent anywhere except GitLab/Ollama.
- Project path (e.g. `whakatau/onplia`), then "Load members from GitLab" to pick your 3 team members.
- Sentiment file/folder: point at wherever your webhook writes daily sentiment text
  (a folder with one file per username, or a single JSON file: `[{"username":"x","date":"2026-09-15","text":"..."}]`).
- Ollama URL (default `http://localhost:11434`) and model name (must already be pulled, e.g. `ollama pull llama3`).

## Build the .exe

Run `build.bat` (requires PyInstaller). Output: `dist\OnpliaProgressApp.exe`.
Each teammate runs the exe once, fills in Settings with their **own** token — nothing is shared or hardcoded.

## Notes

- "In progress" issues are open issues assigned to the person, optionally filtered to the
  workflow labels configured in `config.json` (`in_progress_labels`), matching board columns
  like "In progress", "Review", "In review".
- Requires Ollama already installed and running locally (`ollama serve`), not managed by this app.
