"""Let Me Make Your Life Easier.

A simple always-available desktop GUI:
- First run: enter your own GitLab token/URL/project, pick team members, point at your sentiment file.
- Main window: pull today's merged + in-progress issues per person from GitLab, read sentiment,
  and use a local Ollama model to draft the daily progress update and the CPO sprint status update
  in the exact required plain-text formats. Copy-to-clipboard per box.
"""
import logging
import os
import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

import theme
from config_store import load_config, save_config, CONFIG_DIR
from gitlab_client import GitLabClient, GitLabError
from ollama_client import OllamaClient, OllamaError
from sentiment_reader import read_sentiment_for
from updater import check_for_update, UpdateCheckError
from version import __version__

os.makedirs(CONFIG_DIR, exist_ok=True)
LOG_PATH = os.path.join(CONFIG_DIR, "app.log")
logging.basicConfig(
    filename=LOG_PATH,
    level=logging.DEBUG,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("onplia")
log.info("=== app starting, log file: %s ===", LOG_PATH)

ICON_DIR = os.path.dirname(os.path.abspath(__file__))
ICON_PATH = os.path.join(ICON_DIR, "app_icon.ico")
ICON_PNG_PATH = os.path.join(ICON_DIR, "app_icon.png")
_icon_photo = None


def set_icon(window):
    global _icon_photo
    if os.path.exists(ICON_PATH):
        try:
            window.iconbitmap(ICON_PATH)
        except tk.TclError:
            pass
    if os.path.exists(ICON_PNG_PATH):
        try:
            if _icon_photo is None:
                _icon_photo = tk.PhotoImage(file=ICON_PNG_PATH)
            window.iconphoto(True, _icon_photo)
        except tk.TclError:
            pass


class SettingsDialog(tk.Toplevel):
    def __init__(self, parent, config, on_saved):
        super().__init__(parent)
        self.title(">> SETTINGS.SYS")
        self.geometry("760x560")
        self.minsize(700, 520)
        self.resizable(True, True)
        self.configure(bg=theme.BG)
        self.columnconfigure(1, weight=1)
        set_icon(self)
        self.config_data = dict(config)
        self.on_saved = on_saved
        self.member_vars = {}
        self.last_validated_token = None
        self.protocol("WM_DELETE_WINDOW", self.on_close)

        pad = {"padx": 10, "pady": 4}

        ttk.Label(self, text="GitLab URL").grid(row=0, column=0, sticky="w", **pad)
        self.gitlab_url = tk.Entry(self, width=50)
        self.gitlab_url.insert(0, config.get("gitlab_url", ""))
        self.gitlab_url.grid(row=0, column=1, sticky="ew", **pad)
        theme.style_entry(self.gitlab_url)

        ttk.Label(self, text="Your GitLab Token").grid(row=1, column=0, sticky="w", **pad)
        token_frame = ttk.Frame(self)
        token_frame.grid(row=1, column=1, sticky="w", **pad)
        self.token = tk.Entry(token_frame, width=40, show="*")
        self.token.insert(0, config.get("gitlab_token", ""))
        self.token.pack(side="left")
        theme.style_entry(self.token)
        self.token.bind("<FocusOut>", lambda e: self.validate_token(show_error=False))
        ttk.Button(token_frame, text="Validate", command=self.validate_token).pack(side="left", padx=4)
        self.token_status = ttk.Label(self, text="")
        self.token_status.grid(row=1, column=2, sticky="w")
        self.token_valid = False

        ttk.Label(self, text="Project path (group/project)").grid(row=2, column=0, sticky="w", **pad)
        known_paths = list(dict.fromkeys(
            [p for p in [config.get("project_path", "")] + config.get("recent_project_paths", []) if p]
        ))
        self.project_path = ttk.Combobox(self, width=48, values=known_paths)
        self.project_path.insert(0, config.get("project_path", ""))
        self.project_path.grid(row=2, column=1, sticky="ew", **pad)
        self.project_path.bind("<<ComboboxSelected>>", lambda e: self.on_project_selected())

        ttk.Label(self, text="Board scope labels (comma-separated, e.g. team::thor)").grid(
            row=3, column=0, sticky="w", **pad
        )
        board_labels_frame = ttk.Frame(self)
        board_labels_frame.grid(row=3, column=1, sticky="ew", **pad)
        self.board_labels = tk.Entry(board_labels_frame)
        self.board_labels.insert(0, ",".join(config.get("board_labels", [])))
        self.board_labels.pack(side="left", fill="x", expand=True)
        theme.style_entry(self.board_labels)
        ttk.Button(board_labels_frame, text="Suggest...", command=self.suggest_labels).pack(side="left", padx=4)

        load_members_frame = ttk.Frame(self)
        load_members_frame.grid(row=4, column=0, columnspan=2, sticky="w", **pad)
        ttk.Button(load_members_frame, text="Load members from GitLab", command=self.load_members).pack(
            side="left"
        )
        self.load_members_status = ttk.Label(load_members_frame, text="")
        self.load_members_status.pack(side="left", padx=8)

        ttk.Label(self, text="Team members (pick 3)").grid(row=5, column=0, sticky="nw", **pad)
        self.members_frame = ttk.Frame(self)
        self.members_frame.grid(row=5, column=1, sticky="w", **pad)
        self.members_canvas_populate(config.get("team_members", []))

        ttk.Label(self, text="Sentiment file/folder").grid(row=6, column=0, sticky="w", **pad)
        sent_frame = ttk.Frame(self)
        sent_frame.grid(row=6, column=1, sticky="ew", **pad)
        self.sentiment_path = tk.Entry(sent_frame, width=40)
        self.sentiment_path.insert(0, config.get("sentiment_path", ""))
        self.sentiment_path.pack(side="left", fill="x", expand=True)
        theme.style_entry(self.sentiment_path)
        ttk.Button(sent_frame, text="Browse", command=self.browse_sentiment).pack(side="left", padx=4)

        ttk.Label(self, text="Ollama URL").grid(row=7, column=0, sticky="w", **pad)
        self.ollama_url = tk.Entry(self, width=50)
        self.ollama_url.insert(0, config.get("ollama_url", "http://localhost:11434"))
        self.ollama_url.grid(row=7, column=1, sticky="ew", **pad)
        theme.style_entry(self.ollama_url)

        ttk.Label(self, text="Ollama model").grid(row=8, column=0, sticky="w", **pad)
        self.ollama_model = tk.Entry(self, width=50)
        self.ollama_model.insert(0, config.get("ollama_model", "llama3"))
        self.ollama_model.grid(row=8, column=1, sticky="ew", **pad)
        theme.style_entry(self.ollama_model)

        ttk.Button(self, text="Save", command=self.save).grid(row=9, column=0, columnspan=2, sticky="e", **pad)

    def members_canvas_populate(self, preselected, members=None):
        for w in self.members_frame.winfo_children():
            w.destroy()
        self.member_vars = {}
        members = members or [{"username": u, "name": u} for u in preselected]
        for m in members:
            var = tk.BooleanVar(value=m["username"] in preselected)
            cb = ttk.Checkbutton(self.members_frame, text=f'{m["name"]} (@{m["username"]})', variable=var)
            cb.pack(anchor="w")
            self.member_vars[m["username"]] = var

    def validate_token(self, show_error=True, status_label=None):
        status_label = status_label or self.token_status
        token = self.token.get().strip()
        if not token:
            status_label.config(text="")
            self.token_valid = False
            return False
        if self.token_valid and token == self.last_validated_token:
            status_label.config(text="Valid (cached)", foreground="green")
            return True
        status_label.config(text="Checking...", foreground=theme.MUTED)
        self.update_idletasks()
        try:
            client = GitLabClient(self.gitlab_url.get().strip(), token)
            user = client.validate_token()
            status_label.config(text=f"Valid (@{user['username']})", foreground="green")
            self.token_valid = True
            self.last_validated_token = token
            self.populate_project_suggestions(client)
            return True
        except GitLabError as e:
            status_label.config(text="Invalid token - see error", foreground="red")
            self.token_valid = False
            if show_error:
                messagebox.showerror("Invalid GitLab token", str(e))
            return False

    def populate_project_suggestions(self, client):
        def worker():
            try:
                paths = client.list_my_projects()
                log.debug("list_my_projects returned %d paths: %s", len(paths), paths)
            except GitLabError as e:
                log.warning("list_my_projects failed: %s", e)
                return
            self.after(0, lambda: self._apply_project_suggestions(paths))

        threading.Thread(target=worker, daemon=True).start()

    def _apply_project_suggestions(self, paths):
        # The dialog can be saved or closed while this lookup is still in flight, and then the
        # combobox is gone: Tk answers a call on a destroyed widget with "invalid command name".
        if not self.winfo_exists() or not self.project_path.winfo_exists():
            log.debug("dropped project suggestions, dialog/combobox already gone")
            return
        before = list(self.project_path["values"])
        merged = list(dict.fromkeys(before + paths))
        log.debug("combobox values before=%s after=%s", before, merged)
        self.project_path.config(values=merged)

    def on_project_selected(self):
        self.load_members()

    def suggest_labels(self):
        if not self.token_valid:
            if not self.validate_token():
                return
        project_path = self.project_path.get().strip()
        if not project_path:
            messagebox.showwarning("No project", "Enter/select a project path first.")
            return
        try:
            client = GitLabClient(self.gitlab_url.get().strip(), self.token.get().strip())
            project_id = client.get_project_id(project_path)
            labels = client.list_labels(project_id)
        except GitLabError as e:
            messagebox.showerror("GitLab error", str(e))
            return
        if not labels:
            messagebox.showinfo(
                "No labels",
                f"GitLab returned no labels for {project_path}.\n\n"
                "If the project does have labels, the token may not carry the scope to read them.")
            return
        self._show_label_picker(labels)

    def _show_label_picker(self, labels):
        picker = tk.Toplevel(self)
        picker.title(">> PICK LABELS")
        picker.geometry("460x560")
        picker.configure(bg=theme.BG)
        set_icon(picker)
        current = {l.strip() for l in self.board_labels.get().split(",") if l.strip()}

        ttk.Label(picker, text="Select labels that scope your board (e.g. team::thor):").pack(
            anchor="w", padx=10, pady=(8, 2)
        )

        search_var = tk.StringVar()
        search_entry = tk.Entry(picker, textvariable=search_var)
        theme.style_entry(search_entry)
        search_entry.pack(fill="x", padx=10, pady=(0, 8))
        search_entry.focus_set()

        list_container = ttk.Frame(picker)
        list_container.pack(fill="both", expand=True, padx=10)

        canvas = tk.Canvas(list_container, bg=theme.BG, highlightthickness=0)
        scrollbar = ttk.Scrollbar(list_container, orient="vertical", command=canvas.yview)
        frame = ttk.Frame(canvas)
        frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        def on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        canvas.bind_all("<MouseWheel>", on_mousewheel)
        picker.protocol("WM_DELETE_WINDOW", lambda: (canvas.unbind_all("<MouseWheel>"), picker.destroy()))

        vars_by_label = {lbl: tk.BooleanVar(value=lbl in current) for lbl in sorted(labels)}
        checkbuttons = {}

        def fuzzy_match(query, text):
            query = query.lower()
            text = text.lower()
            if not query:
                return True
            pos = 0
            for ch in query:
                pos = text.find(ch, pos)
                if pos == -1:
                    return False
                pos += 1
            return True

        def render(*_args):
            for w in frame.winfo_children():
                w.destroy()
            query = search_var.get()
            matches = [lbl for lbl in vars_by_label if fuzzy_match(query, lbl)]
            matches.sort(key=lambda lbl: (not lbl.lower().startswith(query.lower()), lbl.lower()))
            for lbl in matches:
                cb = ttk.Checkbutton(frame, text=lbl, variable=vars_by_label[lbl])
                cb.pack(anchor="w")
                checkbuttons[lbl] = cb
            canvas.yview_moveto(0)

        search_var.trace_add("write", render)
        render()

        def apply_selection():
            selected = [l for l, v in vars_by_label.items() if v.get()]
            self.board_labels.delete(0, tk.END)
            self.board_labels.insert(0, ",".join(selected))
            canvas.unbind_all("<MouseWheel>")
            picker.destroy()

        ttk.Button(picker, text="Use selected", command=apply_selection).pack(pady=8)

    def load_members(self):
        if not self.validate_token(status_label=self.load_members_status):
            return
        project_path = self.project_path.get().strip()
        if not project_path:
            self.load_members_status.config(text="Enter a project path first", foreground="red")
            return
        self.load_members_status.config(text=f"Loading members of {project_path}...", foreground=theme.MUTED)
        self.update_idletasks()
        try:
            client = GitLabClient(self.gitlab_url.get().strip(), self.token.get().strip())
            project_id = client.get_project_id(project_path)
            members = client.list_project_members(project_id)
            if not members:
                self.load_members_status.config(text="No members found on this project", foreground="orange")
                return
            self.members_canvas_populate(
                [u for u, v in self.member_vars.items() if v.get()], members
            )
            self.load_members_status.config(text=f"Loaded {len(members)} members", foreground="green")
        except GitLabError as e:
            self.load_members_status.config(text="Failed - see error", foreground="red")
            messagebox.showerror("GitLab error", str(e))
        except Exception as e:
            self.load_members_status.config(text="Failed - see error", foreground="red")
            messagebox.showerror("Unexpected error loading members", str(e))

    def browse_sentiment(self):
        path = filedialog.askopenfilename(title="Select sentiment file (or cancel to pick a folder)")
        if not path:
            path = filedialog.askdirectory(title="Select sentiment folder")
        if path:
            self.sentiment_path.delete(0, tk.END)
            self.sentiment_path.insert(0, path)

    def save(self):
        log.info("Save clicked: project_path field='%s'", self.project_path.get().strip())
        if not self.validate_token():
            log.warning("Save aborted: token failed validation")
            messagebox.showwarning("Cannot save", "Enter a valid GitLab token before saving.")
            return
        selected = [u for u, v in self.member_vars.items() if v.get()]
        board_labels = [l.strip() for l in self.board_labels.get().split(",") if l.strip()]
        project_path = self.project_path.get().strip()
        recent = [project_path] + [
            p for p in self.config_data.get("recent_project_paths", []) if p != project_path
        ]
        log.info(
            "Writing config: project_path=%s board_labels=%s team_members=%s recent=%s",
            project_path, board_labels, selected, recent[:10],
        )
        self.config_data.update({
            "gitlab_url": self.gitlab_url.get().strip(),
            "gitlab_token": self.token.get().strip(),
            "project_path": project_path,
            "recent_project_paths": recent[:10],
            "board_labels": board_labels,
            "team_members": selected,
            "sentiment_path": self.sentiment_path.get().strip(),
            "ollama_url": self.ollama_url.get().strip(),
            "ollama_model": self.ollama_model.get().strip(),
        })
        save_config(self.config_data)
        self.on_saved(self.config_data)
        self.saved = True
        self.destroy()

    def on_close(self):
        if getattr(self, "saved", False):
            self.destroy()
            return
        if messagebox.askyesno(
            "Unsaved changes",
            "You have unsaved changes in Settings. Close without saving?",
        ):
            self.destroy()


class MainApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(">> LMMYLE.EXE — LET ME MAKE YOUR LIFE EASIER v2.2 EXTENDED")
        self.geometry("900x700")
        theme.apply(self)
        set_icon(self)
        self.config_data = load_config()

        top = ttk.Frame(self)
        top.pack(fill="x", padx=10, pady=8)
        ttk.Button(top, text="⚙ SETTINGS", command=self.open_settings).pack(side="left")
        self.generate_button = ttk.Button(
            top, text="⚡ GENERATE TODAY'S UPDATES", command=self.generate)
        self.generate_button.pack(side="left", padx=8)
        self.status_label = ttk.Label(top, text="", foreground=theme.ACCENT2)
        self.status_label.pack(side="left", padx=8)

        self.update_banner = ttk.Frame(self)
        self.update_label = ttk.Label(self.update_banner, text="", foreground=theme.ACCENT2)
        self.update_label.pack(side="left", padx=10, pady=(0, 4))
        ttk.Button(
            self.update_banner, text="View release", command=self._open_update_url
        ).pack(side="left", padx=4)
        self._update_url = None
        self.after(500, self.check_for_update)

        self.progress_row = ttk.Frame(self)
        self.progress_row.pack(fill="x", padx=10)
        self.progress = ttk.Progressbar(
            self.progress_row, mode="determinate", maximum=100,
            style="Neon.Horizontal.TProgressbar")
        self.progress.pack(side="left", fill="x", expand=True)
        # Beside the bar rather than over it: tkinter labels have no transparency, so a percentage
        # placed on top carries its own rectangle across the fill line and reads as a defect.
        self.progress_percent = ttk.Label(
            self.progress_row, text="", width=5, anchor="e", foreground=theme.PROGRESS_BAR)
        self.progress_percent.pack(side="left", padx=(8, 0))
        self.progress_row.pack_forget()

        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True, padx=10, pady=8)

        self.daily_boxes = {}
        self.daily_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.daily_tab, text="DAILY PROGRESS")

        self.cpo_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.cpo_tab, text="CPO UPDATE")
        ttk.Label(
            self.cpo_tab, text="Editable — change anything here before you copy it.",
            foreground=theme.MUTED).pack(anchor="w", padx=8, pady=(8, 0))
        self.cpo_text = tk.Text(self.cpo_tab)
        theme.style_text(self.cpo_text)
        self.cpo_text.pack(fill="both", expand=True, padx=8, pady=8)
        ttk.Button(self.cpo_tab, text="Copy to clipboard", command=lambda: self.copy(self.cpo_text)).pack(
            pady=4
        )

        self.debug_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.debug_tab, text="DATA LOG")
        self.debug_text = tk.Text(self.debug_tab)
        theme.style_text(self.debug_text)
        self.debug_text.pack(fill="both", expand=True, padx=8, pady=8)

        self.settings_dialog = None
        if not self.config_data.get("gitlab_token") or not self.config_data.get("team_members"):
            self.after(200, self.open_settings)

    def check_for_update(self):
        def worker():
            repo = self.config_data.get("github_repo")
            if not repo:
                return
            try:
                result = check_for_update(repo, self.config_data.get("github_token") or None)
            except UpdateCheckError as e:
                log.debug("update check failed: %s", e)
                return
            if result:
                latest_version, url = result
                self.after(0, lambda: self._show_update_banner(latest_version, url))

        threading.Thread(target=worker, daemon=True).start()

    def _show_update_banner(self, latest_version, url):
        self._update_url = url
        self.update_label.config(text=f"⬆ Update available: v{latest_version} (you have v{__version__})")
        self.update_banner.pack(fill="x", before=self.notebook)

    def _open_update_url(self):
        if self._update_url:
            import webbrowser
            webbrowser.open(self._update_url)

    def open_settings(self):
        if self.settings_dialog is not None and self.settings_dialog.winfo_exists():
            self.settings_dialog.lift()
            self.settings_dialog.focus_force()
            return
        self.settings_dialog = SettingsDialog(self, self.config_data, self.on_settings_saved)

    def on_settings_saved(self, new_config):
        self.config_data = new_config

    def copy(self, widget):
        self.clipboard_clear()
        self.clipboard_append(widget.get("1.0", "end").strip())
        messagebox.showinfo("Copied", "Copied to clipboard")

    def generate(self):
        if not self.config_data.get("gitlab_token") or not self.config_data.get("project_path"):
            messagebox.showwarning("Missing settings", "Please configure GitLab settings first.")
            self.open_settings()
            return
        self.generate_button.config(state="disabled")
        self.progress_row.pack(fill="x", padx=10)
        self.set_progress(0)
        self.status_label.config(text="Starting...")
        threading.Thread(target=self._generate_worker, daemon=True).start()

    def say(self, message):
        """Status text from the worker thread."""
        self.after(0, lambda: self.status_label.config(text=message))

    def set_progress(self, fraction):
        """0..1 for a known quantity, or None while the length is unknowable."""
        if fraction is None:
            self.progress.config(mode="indeterminate")
            self.progress_percent.config(text="")
            self.progress.start(12)
            return
        self.progress.stop()
        self.progress.config(mode="determinate")
        percent = max(0, min(100, fraction * 100))
        self.progress["value"] = percent
        self.progress_percent.config(text=f"{percent:.0f}%")

    def step(self, fraction):
        self.after(0, lambda: self.set_progress(fraction))

    def _finish(self, message):
        self.progress.stop()
        self.progress_row.pack_forget()
        self.generate_button.config(state="normal")
        self.status_label.config(text=message)

    def _generate_worker(self):
        ollama = None
        try:
            cfg = self.config_data
            members = cfg["team_members"]
            # The model download is the long pole, so it gets its own band of the bar and the rest
            # of the run shares what is left.
            setup_band = 0.35

            self.say("Checking Ollama...")
            gl = GitLabClient(cfg["gitlab_url"], cfg["gitlab_token"])
            project_id = gl.get_project_id(cfg["project_path"])
            ollama = OllamaClient(cfg["ollama_url"], cfg["ollama_model"])
            ollama.ensure_running(
                log=self.say,
                progress=lambda fraction: self.step(fraction * setup_band),
            )
            self.step(setup_band)

            steps_left = len(members) + 1
            done_steps = 0

            def advance():
                nonlocal done_steps
                done_steps += 1
                self.step(setup_band + (1 - setup_band) * done_steps / steps_left)

            debug_lines = []
            total_merged = 0
            total_in_progress = 0
            all_merged_refs = []
            all_in_progress_refs = []
            sentiment_notes = []
            daily_results = {}

            for username in members:
                self.say(f"Reading GitLab for {username}...")
                merged = gl.merged_today(project_id, username, board_labels=cfg.get("board_labels"))
                # No in_progress_labels: "In progress" and "Review" are work-item statuses here
                # rather than labels, so filtering on them matches nothing — and the point is what
                # the person moved today, which includes an issue they pushed into review.
                in_progress = gl.in_progress_issues(
                    project_id, cfg["project_path"], username, board_labels=cfg.get("board_labels")
                )
                total_merged += len(merged)
                total_in_progress += len(in_progress)

                merged_lines = [f'#{m["iid"]} {m["title"]}' for m in merged]
                progress_lines = [f'#{i["iid"]} {i["title"]}' for i in in_progress]
                all_merged_refs.extend(f'#{m["iid"]}' for m in merged)
                all_in_progress_refs.extend(f'#{i["iid"]}' for i in in_progress)

                debug_lines.append(f"--- {username} ---")
                debug_lines.append(f"Merged ({len(merged)}): " + "; ".join(merged_lines) if merged_lines else f"Merged (0): none")
                debug_lines.append(f"In progress ({len(in_progress)}): " + "; ".join(progress_lines) if progress_lines else f"In progress (0): none")

                sentiment_text = read_sentiment_for(cfg.get("sentiment_path"), username)
                if sentiment_text:
                    sentiment_notes.append(f"{username}: {sentiment_text}")
                    debug_lines.append(f"Sentiment: {sentiment_text}")
                else:
                    debug_lines.append("Sentiment: (none found)")

                self.say(f"Writing {username}'s update...")
                daily = ollama.build_daily_update(username, merged_lines, progress_lines)
                daily_results[username] = daily
                advance()

            self.say("Writing the CPO update...")
            status_emoji = "🟢" if total_in_progress <= total_merged else "🟡"
            cpo_update = ollama.build_cpo_update(
                merged_count=total_merged,
                in_progress_count=total_in_progress,
                sentiment_notes="\n".join(sentiment_notes),
                blockers_notes="",
                status_emoji=status_emoji,
                daily_updates="\n\n".join(
                    f"{name}:\n{text}" for name, text in daily_results.items()),
                merged_refs=sorted(set(all_merged_refs), key=lambda r: int(r.lstrip("#"))),
                in_progress_refs=sorted(set(all_in_progress_refs), key=lambda r: int(r.lstrip("#"))),
            )
            advance()

            self.after(0, self._apply_results, daily_results, cpo_update, "\n".join(debug_lines))
        except (GitLabError, OllamaError) as e:
            message = str(e)
            self.after(0, lambda: messagebox.showerror("Error", message))
            self.after(0, lambda: self._finish("Error"))
        except Exception as e:
            message = str(e)
            self.after(0, lambda: messagebox.showerror("Unexpected error", message))
            self.after(0, lambda: self._finish("Error"))
        finally:
            if ollama is not None:
                ollama.shutdown(log=self.say)

    def _apply_results(self, daily_results, cpo_update, debug_text):
        for w in self.daily_tab.winfo_children():
            w.destroy()
        self.daily_boxes = {}

        person_notebook = ttk.Notebook(self.daily_tab)
        person_notebook.pack(fill="both", expand=True)
        for username, text in daily_results.items():
            frame = ttk.Frame(person_notebook)
            person_notebook.add(frame, text=username)
            ttk.Label(
                frame, text="Editable — change anything here before you copy it.",
                foreground=theme.MUTED).pack(anchor="w", padx=8, pady=(8, 0))
            box = tk.Text(frame)
            theme.style_text(box)
            box.insert("1.0", text)
            box.pack(fill="both", expand=True, padx=8, pady=8)
            ttk.Button(frame, text="Copy to clipboard", command=lambda b=box: self.copy(b)).pack(pady=4)
            self.daily_boxes[username] = box

        self.cpo_text.delete("1.0", "end")
        self.cpo_text.insert("1.0", cpo_update)

        self.debug_text.delete("1.0", "end")
        self.debug_text.insert("1.0", debug_text)

        self._finish("Done")


if __name__ == "__main__":
    MainApp().mainloop()
