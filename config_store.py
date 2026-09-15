"""Local per-user config storage. Never committed, never sent anywhere except GitLab/Ollama."""
import json
import os

CONFIG_DIR = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "OnpliaProgressApp")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")

DEFAULT_CONFIG = {
    "gitlab_url": "https://gitlab.com",
    "gitlab_token": "",
    "project_path": "",
    "recent_project_paths": [],
    "board_labels": [],
    "team_members": [],
    "in_progress_labels": ["In progress", "Review", "In review", "Awaiting feedback"],
    "sentiment_path": "",
    "ollama_url": "http://localhost:11434",
    "ollama_model": "llama3",
    "github_repo": "Veekash2/daily-update",
    "github_token": "",
}


def load_config():
    if not os.path.exists(CONFIG_PATH):
        return dict(DEFAULT_CONFIG)
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        merged = dict(DEFAULT_CONFIG)
        merged.update(data)
        return merged
    except (json.JSONDecodeError, OSError):
        return dict(DEFAULT_CONFIG)


def save_config(config):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)
