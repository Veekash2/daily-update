"""Reads webhook-captured sentiment text from a local file or folder.

Supports:
- A single .json file: list of {"username": ..., "text": ..., "date": "YYYY-MM-DD"}
- A folder of .txt/.json files, one per person, filename containing the username.
"""
import json
import os
import datetime as dt


def read_sentiment_for(path, username, date=None):
    if not path or not os.path.exists(path):
        return ""
    date = date or dt.date.today().isoformat()

    if os.path.isdir(path):
        for fname in os.listdir(path):
            if username.lower() in fname.lower():
                fpath = os.path.join(path, fname)
                return _read_entry(fpath, username, date)
        return ""
    else:
        return _read_entry(path, username, date)


def _read_entry(fpath, username, date):
    try:
        if fpath.endswith(".json"):
            with open(fpath, "r", encoding="utf-8") as f:
                data = json.load(f)
            entries = data if isinstance(data, list) else [data]
            matches = [
                e for e in entries
                if e.get("username", "").lower() == username.lower()
                and (not e.get("date") or e.get("date") == date)
            ]
            if matches:
                return matches[-1].get("text", "")
            return ""
        else:
            with open(fpath, "r", encoding="utf-8") as f:
                return f.read().strip()
    except (OSError, json.JSONDecodeError):
        return ""
