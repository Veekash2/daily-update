"""Calls a locally running Ollama instance to turn raw GitLab + sentiment data into the two required formats."""
import json
import subprocess
import time
import urllib.error
import urllib.request

DAILY_PROMPT_TEMPLATE = """You write a daily progress update. Use PLAIN TEXT ONLY \
(no markdown bold, no asterisks, no headers) in exactly this format:

MERGED
<one line per merged issue/MR: "#IID [TYPE] - short description">

IN PROGRESS
<one line per in-progress issue: "#IID [TYPE] - short description">

Rules:
- Every line MUST start with the issue number exactly as given in the raw data (e.g. "#2207"),
  never omit it and never invent one.
- TYPE is the class label if present (e.g. BE, DB, Design), else omit it.
- Keep each line to the issue title as given, do not invent details.
- If a section is empty, write "None".
- Do not add any commentary, headers, or extra sections beyond MERGED and IN PROGRESS.

Raw data for {name}:
MERGED ITEMS:
{merged_items}

IN PROGRESS ITEMS:
{in_progress_items}
"""

CPO_PROMPT_TEMPLATE = """You write a team CPO sprint status update. Use PLAIN TEXT ONLY \
(no markdown bold, no asterisks) in exactly this format:

SPRINT STATUS: {status_emoji}

PROGRESS

{merged_count} issues merged into main ({merged_refs})
{in_progress_count} in progress ({in_progress_refs})

TEAM SENTIMENT

{sentiment_summary}

BLOCKERS

{blockers}

Rules:
- The issue number lists in parentheses after each PROGRESS line must be copied exactly as given
  below (e.g. "#2207, #1606") — never invent, reorder meaning, or drop any of them. If a list is
  empty, write "none" in the parentheses instead.
- Only output the text in that exact structure, nothing else.

The team's own daily updates, for context on what actually moved:
{daily_updates}
"""

IMAGE = "ollama/ollama"


class OllamaError(Exception):
    pass


class OllamaClient:
    def __init__(self, base_url, model):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.container_name = None
        self.started_container = False
        self.created_container = False

    # -- reachability ------------------------------------------------------

    def is_reachable(self):
        try:
            req = urllib.request.Request(f"{self.base_url}/api/tags")
            with urllib.request.urlopen(req, timeout=3):
                return True
        except (urllib.error.URLError, OSError):
            return False

    # -- docker ------------------------------------------------------------

    @staticmethod
    def _docker(args, timeout=30):
        try:
            return subprocess.run(
                ["docker", *args], capture_output=True, text=True, timeout=timeout,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except (OSError, subprocess.SubprocessError) as e:
            raise OllamaError(f"Docker is not available: {e}")

    def image_present(self):
        return self._docker(["image", "inspect", IMAGE]).returncode == 0

    def container_state(self, name):
        result = self._docker(
            ["ps", "-a", "--filter", f"name=^{name}$", "--format", "{{.State}}"])
        state = result.stdout.strip()
        if not state:
            return "absent"
        return "running" if state == "running" else "stopped"

    # -- lifecycle ---------------------------------------------------------

    def ensure_running(self, container_name="onplia-ollama", startup_timeout=120,
                       log=None, progress=None):
        """Make Ollama reachable, reusing whatever already exists.

        Records what it had to do, so shutdown() can stop only what this run started and
        leave an Ollama somebody else was already using alone.
        """
        log = log or (lambda msg: None)
        progress = progress or (lambda fraction: None)
        self.container_name = container_name

        if self.is_reachable():
            log("Ollama is already running.")
            self._ensure_model(log, progress)
            return

        if "localhost" not in self.base_url and "127.0.0.1" not in self.base_url:
            raise OllamaError(
                f"Could not reach Ollama at {self.base_url} and it is not localhost, "
                "so it cannot be auto-started.")

        port = self.base_url.rsplit(":", 1)[-1]
        state = self.container_state(container_name)

        if state == "running":
            log(f"Container '{container_name}' is running but not answering yet, waiting...")
        elif state == "stopped":
            log(f"Starting the existing container '{container_name}'...")
            result = self._docker(["start", container_name])
            if result.returncode != 0:
                raise OllamaError(f"Could not start '{container_name}': {result.stderr.strip()}")
            self.started_container = True
        else:
            if not self.image_present():
                log(f"Downloading the {IMAGE} image (first run only, several hundred MB)...")
                pull = self._docker(["pull", IMAGE], timeout=1800)
                if pull.returncode != 0:
                    raise OllamaError(f"Could not download {IMAGE}: {pull.stderr.strip()}")
            log(f"Creating container '{container_name}' on port {port}...")
            result = self._docker(
                ["run", "-d", "--name", container_name, "-p", f"{port}:11434", IMAGE], timeout=120)
            if result.returncode != 0:
                raise OllamaError(f"Failed to start Ollama container: {result.stderr.strip()}")
            self.started_container = True
            self.created_container = True

        deadline = time.time() + startup_timeout
        while time.time() < deadline:
            if self.is_reachable():
                log("Ollama is up.")
                self._ensure_model(log, progress)
                return
            time.sleep(2)
        raise OllamaError(
            f"Ollama container started but did not answer within {startup_timeout}s.")

    def shutdown(self, log=None):
        """Stop the container, but only when this run is what started it."""
        log = log or (lambda msg: None)
        if not self.started_container or not self.container_name:
            return
        log(f"Stopping '{self.container_name}'...")
        self._docker(["stop", self.container_name], timeout=60)
        self.started_container = False

    # -- model -------------------------------------------------------------

    def model_present(self):
        try:
            req = urllib.request.Request(f"{self.base_url}/api/tags")
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, OSError, json.JSONDecodeError):
            return False
        wanted = self.model.split(":")[0]
        return any(m.get("name", "").split(":")[0] == wanted for m in data.get("models", []))

    def _ensure_model(self, log, progress):
        if self.model_present():
            log(f"Model '{self.model}' is already downloaded.")
            return

        log(f"Downloading model '{self.model}' (first run only)...")
        payload = json.dumps({"name": self.model, "stream": True}).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/api/pull", data=payload, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=3600) as resp:
                for raw in resp:
                    line = raw.decode("utf-8").strip()
                    if not line:
                        continue
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if event.get("error"):
                        raise OllamaError(f"Pulling '{self.model}' failed: {event['error']}")
                    total = event.get("total")
                    completed = event.get("completed")
                    if total:
                        fraction = (completed or 0) / total
                        progress(fraction)
                        log(f"Downloading '{self.model}' — {fraction * 100:.0f}% of "
                            f"{total / 1e9:.1f} GB")
                    elif event.get("status"):
                        log(f"{event['status']}...")
        except urllib.error.URLError as e:
            raise OllamaError(f"Failed to pull model '{self.model}': {e.reason}")
        progress(1.0)

    # -- generation --------------------------------------------------------

    def generate(self, prompt):
        url = f"{self.base_url}/api/generate"
        payload = json.dumps({"model": self.model, "prompt": prompt, "stream": False}).encode("utf-8")
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=300) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return data.get("response", "").strip()
        except urllib.error.URLError as e:
            raise OllamaError(
                f"Could not reach Ollama at {self.base_url}. Is it running? ({e.reason})")

    def build_daily_update(self, name, merged_items, in_progress_items):
        merged_text = "\n".join(merged_items) if merged_items else "None"
        progress_text = "\n".join(in_progress_items) if in_progress_items else "None"
        prompt = DAILY_PROMPT_TEMPLATE.format(
            name=name, merged_items=merged_text, in_progress_items=progress_text)
        return self.generate(prompt)

    def build_cpo_update(self, merged_count, in_progress_count, sentiment_notes, blockers_notes,
                         status_emoji, daily_updates="", merged_refs=None, in_progress_refs=None):
        sentiment_summary = sentiment_notes.strip() if sentiment_notes else \
            "There are more issues than we think we can finish in the sprint, monitoring as days go by."
        blockers = blockers_notes.strip() if blockers_notes else "N/A"
        prompt = CPO_PROMPT_TEMPLATE.format(
            status_emoji=status_emoji,
            merged_count=merged_count,
            in_progress_count=in_progress_count,
            merged_refs=", ".join(merged_refs) if merged_refs else "none",
            in_progress_refs=", ".join(in_progress_refs) if in_progress_refs else "none",
            sentiment_summary=sentiment_summary,
            blockers=blockers,
            daily_updates=daily_updates.strip() or "(none)",
        )
        return self.generate(prompt)
