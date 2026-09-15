"""Checks GitHub for a newer released version than the one currently running.

Does not download or run anything automatically — it only reports whether a newer version
tag exists and points the user at the compare/releases page to update by hand (git pull /
re-download the exe), which keeps this out of "download and execute files automatically"
territory entirely.
"""
import json
import urllib.error
import urllib.request

from version import __version__


class UpdateCheckError(Exception):
    pass


def _parse_version(v):
    v = v.lstrip("v")
    parts = []
    for part in v.split("."):
        digits = "".join(ch for ch in part if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])


def check_for_update(repo, github_token=None):
    """repo: "owner/name". Returns (latest_version_str, compare_url) if newer, else None."""
    url = f"https://api.github.com/repos/{repo}/tags"
    headers = {"Accept": "application/vnd.github+json"}
    if github_token:
        headers["Authorization"] = f"token {github_token}"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            tags = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.HTTPError, urllib.error.URLError) as e:
        raise UpdateCheckError(f"Could not check for updates: {e}")

    if not tags:
        return None

    latest = max(tags, key=lambda t: _parse_version(t["name"]))
    if _parse_version(latest["name"]) > _parse_version(__version__):
        return latest["name"], f"https://github.com/{repo}/releases"
    return None
