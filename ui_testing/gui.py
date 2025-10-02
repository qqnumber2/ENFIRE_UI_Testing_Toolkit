# ui_testing/gui.py
from __future__ import annotations

import sys, os, logging, threading, time, subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import tkinter as tk
from tkinter import messagebox, filedialog, simpledialog, scrolledtext
import ttkbootstrap as ttk
from ttkbootstrap.constants import *
from PIL import Image, ImageTk

# ---------- tolerant imports for local, package, or flat layouts ----------
try:
    from ui_testing.recorder import Recorder, RecorderConfig
    from ui_testing.player   import Player, PlayerConfig
except Exception:
    try:
        from .recorder import Recorder, RecorderConfig  # type: ignore
        from .player   import Player,   PlayerConfig    # type: ignore
    except Exception:
        from recorder import Recorder, RecorderConfig   # type: ignore
        from player   import Player,   PlayerConfig     # type: ignore

# Optional AI summaries (safe if missing)
try:
    from ui_testing.ai_summarizer import write_run_bug_report, BugNote
except Exception:
    try:
        from .ai_summarizer import write_run_bug_report, BugNote  # type: ignore
    except Exception:
        @dataclass
        class BugNote:
            note_path: Path
            note_text: str
            summary: Optional[str] = None
            recommendations: Optional[List[str]] = None
            analysis: Optional[str] = None

        def write_run_bug_report(*_a, **_k):  # no-op fallback
            return None

# Make source/EXE paths importable
_here = Path(__file__).resolve()
_pkg  = _here.parent
_root = _pkg.parent
for p in (str(_pkg), str(_root)):
    if p not in sys.path:
        sys.path.insert(0, p)

def resource_path(rel: str) -> str:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return str((base / rel).resolve())

@dataclass
class Paths:
    root: Path
    scripts_dir: Path
    images_dir: Path
    results_dir: Path
    tolerance: float = 0.01

# ---------------- New Recording Dialog ----------------
class NewRecordingDialog(simpledialog.Dialog):
    def body(self, master: tk.Misc) -> None:
        ttk.Label(master, text="Procedure (e.g. 1_EBS)").grid(row=0, column=0, sticky="w", padx=4, pady=4)
        ttk.Label(master, text="Section (e.g. 6)").grid(row=1, column=0, sticky="w", padx=4, pady=4)
        ttk.Label(master, text="Test name (e.g. 1.1.1_ATTACHMENTS TAB)").grid(row=2, column=0, sticky="w", padx=4, pady=4)
        self.proc_var = tk.StringVar(master=master)
        self.sec_var  = tk.StringVar(master=master)
        self.test_var = tk.StringVar(master=master)
        ttk.Entry(master, textvariable=self.proc_var, width=40).grid(row=0, column=1, sticky="ew", padx=4, pady=4)
        ttk.Entry(master, textvariable=self.sec_var,  width=40).grid(row=1, column=1, sticky="ew", padx=4, pady=4)
        ttk.Entry(master, textvariable=self.test_var, width=40).grid(row=2, column=1, sticky="ew", padx=4, pady=4)
        master.grid_columnconfigure(1, weight=1)
    def validate(self) -> bool:
        for label, v in (("Procedure", self.proc_var), ("Section", self.sec_var), ("Test name", self.test_var)):
            if not v.get().strip():
                messagebox.showerror("Missing", f"{label} is required.", parent=self)
                return False
        return True
    def apply(self) -> None:
        self.result = (self.proc_var.get().strip(), self.sec_var.get().strip(), self.test_var.get().strip())

class TestRunnerGUI:
    def __init__(self) -> None:
        # Window first (fixes "no default root window")
        self.root = ttk.Window(themename="cosmo")
        self.root.title("UI Testing")
        self.root.geometry("1480x940")
        try:
            self.root.iconbitmap(resource_path("assets/ui_testing.ico"))
        except Exception:
            pass

        # Tk vars (after root)
        self.theme_var             = tk.StringVar(master=self.root, value="cosmo")
        self.default_delay_var     = tk.DoubleVar(master=self.root, value=0.5)
        self.tolerance_var         = tk.DoubleVar(master=self.root, value=0.01)  # % diff to PASS
        self.use_default_delay_var = tk.BooleanVar(master=self.root, value=False)

        # Place artifacts next to app (no Desktop leakage)
        app_dir = (Path(sys.executable).resolve().parent if getattr(sys, "frozen", False)
                   else Path(__file__).resolve().parent)
        self.paths = Paths(
            root=app_dir,
            scripts_dir=(app_dir / "scripts"),
            images_dir=(app_dir / "images"),
            results_dir=(app_dir / "results"),
        )
        self.paths.tolerance = float(self.tolerance_var.get())
        for d in (self.paths.scripts_dir, self.paths.images_dir, self.paths.results_dir):
            d.mkdir(parents=True, exist_ok=True)
        try: os.chdir(self.paths.root)
        except Exception: pass

        # Logging & GUI handler
        self._setup_logging()

        # Player/Recorder
        self.recorder: Optional[Recorder] = None
        self._recorder_watch_thread: Optional[threading.Thread] = None
        self._player_running = False

        self.player = Player(PlayerConfig(
            scripts_dir=self.paths.scripts_dir,
            images_dir=self.paths.images_dir,
            results_dir=self.paths.results_dir,
            taskbar_crop_px=60,
            wait_between_actions=float(self.default_delay_var.get()),
            app_title_regex=r".*ENFIRE.*",
            diff_tolerance=float(self.tolerance_var.get()),
            use_default_delay_always=bool(self.use_default_delay_var.get()),
        ))
        if hasattr(self.player.config, "diff_tolerance_percent"):
            self.player.config.diff_tolerance_percent = float(self.tolerance_var.get())

        # Models
        self.test_map: Dict[str, str] = {}   # tree-id -> "proc/section/test"
        self.trees: Dict[str, ttk.Treeview] = {}
        self.procedures: List[str] = []

        # Preview cache & selection debounce
        self._thumb_cache: dict[tuple[str, float, int, int], ImageTk.PhotoImage] = {}
        self._resize_job: Optional[str] = None
        self._select_job: Optional[str] = None
        self._current_preview_paths: Dict[str, Optional[Path]] = {"O":None,"T":None,"D":None,"H":None}

        # Selection summary for Available Tests
        self.selected_tests_var = tk.StringVar(master=self.root, value="Selected: 0 tests")
        self._tree_select_job: Optional[str] = None

        # Build UI
        self._build_widgets()
        self._load_tests()
        self._build_notebook()

        # Global Esc: stop recording or playback
        self.root.bind("<Escape>", self._global_escape)

    # ---------------- logging ----------------
    def _setup_logging(self) -> None:
        logger = logging.getLogger()
        logger.handlers.clear()
        logger.setLevel(logging.INFO)
        fmt = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
        sh = logging.StreamHandler(stream=sys.stdout); sh.setFormatter(fmt)
        logger.addHandler(sh)

    def _attach_log_handler(self) -> None:
        class TkHandler(logging.Handler):
            def __init__(self, widget: tk.Text):
                super().__init__()
                self.widget = widget
                self.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
            def emit(self, record):
                msg = self.format(record)
                def append():
                    try:
                        self.widget.configure(state="normal")
                        self.widget.insert("end", msg + "\n")
                        self.widget.see("end")
                        if int(self.widget.index('end-1c').split('.')[0]) > 2000:
                            self.widget.delete("1.0", "1000.0")
                        self.widget.configure(state="disabled")
                    except Exception:
                        pass
                try: self.widget.after(0, append)
                except Exception: pass
        h = TkHandler(self.log_text)
        logging.getLogger().addHandler(h)

    # ---------------- layout ----------------
    def _build_widgets(self) -> None:
        # Top
        top = ttk.Frame(self.root, padding=(16, 12)); top.pack(side=tk.TOP, fill=tk.X)
        title_block = ttk.Frame(top); title_block.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Label(title_block, text="UI Testing", font="-size 16 -weight bold").pack(anchor="w")
        ttk.Label(title_block, text="Record • Playback • Pixel-Perfect Compare", bootstyle="secondary").pack(anchor="w", pady=(2, 0))

        toolbar = ttk.Frame(top); toolbar.pack(side=tk.RIGHT)
        ttk.Label(toolbar, text="Theme").grid(row=0, column=0, padx=(0, 6), sticky="e")
        theme_combo = ttk.Combobox(toolbar, state="readonly", width=12,
                                   values=["cosmo","flatly","minty","litera","sandstone","pulse","darkly","cyborg","superhero"])
        theme_combo.set(self.theme_var.get()); theme_combo.grid(row=0, column=1, padx=(0, 12))
        theme_combo.bind("<<ComboboxSelected>>", lambda e: self._on_theme_change(theme_combo.get()))

        dd = ttk.Frame(toolbar); dd.grid(row=0, column=2, padx=(0, 8))
        ttk.Label(dd, text="Default Delay (s)").pack(side=tk.LEFT, padx=(0, 6))
        ttk.Spinbox(dd, from_=0.0, to=5.0, increment=0.1, textvariable=self.default_delay_var, width=6).pack(side=tk.LEFT)

        tol = ttk.Frame(toolbar); tol.grid(row=0, column=3, padx=(0, 8))
        ttk.Label(tol, text="Tolerance (% max diff)").pack(side=tk.LEFT, padx=(0, 6))
        ttk.Spinbox(tol, from_=0.0, to=100.0, increment=0.01, textvariable=self.tolerance_var, width=6).pack(side=tk.LEFT)

        ttk.Checkbutton(toolbar, text="Ignore recorded delays", variable=self.use_default_delay_var, bootstyle="round-toggle").grid(row=0, column=4, padx=(8,0))

        # Body split
        body = ttk.Panedwindow(self.root, orient=tk.HORIZONTAL)
        body.pack(fill=tk.BOTH, expand=True, padx=12, pady=(0,12))

        left = ttk.Frame(body)
        right_panes = ttk.Panedwindow(body, orient=tk.VERTICAL)
        body.add(left, weight=1)
        body.add(right_panes, weight=3)

        # Left column
        card_actions = ttk.Labelframe(left, text="Actions", padding=12)
        card_actions.pack(fill=tk.X, padx=(0, 12), pady=(0, 12))
        actions = ttk.Frame(card_actions); actions.pack(fill=tk.X)

        ttk.Button(actions, text="Record New", command=self.start_recording, bootstyle="primary").grid(row=0, column=0, padx=4, pady=4, sticky="w")
        ttk.Button(actions, text="Stop Recording", command=self.stop_recording, bootstyle="warning").grid(row=0, column=1, padx=4, pady=4, sticky="w")
        ttk.Button(actions, text="Normalize ENFIRE", command=self.normalize_enfire, bootstyle="secondary-outline").grid(row=0, column=2, padx=4, pady=4, sticky="w")
        ttk.Separator(actions, orient=tk.HORIZONTAL).grid(row=1, column=0, columnspan=4, sticky="ew", pady=(8,4))
        ttk.Button(actions, text="Run Selected", command=self.run_selected, bootstyle="success").grid(row=2, column=0, padx=4, pady=4, sticky="w")
        ttk.Button(actions, text="Run All", command=self.run_all, bootstyle="success-outline").grid(row=2, column=1, padx=4, pady=4, sticky="w")
        ttk.Button(actions, text="Instructions", command=self.show_instructions).grid(row=2, column=3, padx=4, pady=4, sticky="e")
        for c in (0,1):
            actions.grid_columnconfigure(c, weight=1)

        card_tests = ttk.Labelframe(left, text="Available Tests", padding=8)
        card_tests.pack(fill=tk.BOTH, expand=True, padx=(0, 12))
        self.nb = ttk.Notebook(card_tests, bootstyle="pills")
        self.nb.pack(fill=tk.BOTH, expand=True)

        sel_info = ttk.Frame(card_tests)
        sel_info.pack(fill=tk.X, pady=(6, 0))
        ttk.Label(sel_info, textvariable=self.selected_tests_var, bootstyle="secondary").pack(anchor="w")

        # Right panes
        right_results = ttk.Frame(right_panes)
        right_preview = ttk.Frame(right_panes)
        right_log     = ttk.Frame(right_panes)
        right_panes.add(right_results, weight=2)
        right_panes.add(right_preview, weight=3)
        right_panes.add(right_log,     weight=1)

        # Results table (add Script col; narrower Original/Test)
        card_results = ttk.Labelframe(right_results, text="Test Results", padding=8)
        card_results.pack(fill=tk.BOTH, expand=True, pady=(0,12))

        cols = ("script", "index", "original", "test", "diff", "status")
        self.result_tree = ttk.Treeview(card_results, columns=cols, show="headings", height=10, bootstyle="info")
        labels = {"script":"Script", "index":"Idx", "original":"Original", "test":"Test", "diff":"Diff (%)", "status":"Status"}
        for cid, width, anchor in (
            ("script", 280, "w"),
            ("index",   60, "center"),
            ("original",220, "w"),
            ("test",    220, "w"),
            ("diff",    90, "e"),
            ("status", 120, "center"),
        ):
            self.result_tree.heading(cid, text=labels[cid])
            self.result_tree.column(cid, width=width, anchor=anchor)
        self.result_tree.pack(fill=tk.BOTH, expand=True)
        self.result_tree.tag_configure("pass", foreground="#0b6e2e", font="-weight bold")
        self.result_tree.tag_configure("fail", foreground="#b00020", font="-weight bold")
        self.result_tree.bind("<<TreeviewSelect>>", self._on_result_select)

        # Screenshot Preview 2×2 (O/T/D/H) + click-to-open
        card_preview = ttk.Labelframe(right_preview, text="Screenshot Preview", padding=8)
        card_preview.pack(fill=tk.BOTH, expand=True)
        grid = ttk.Frame(card_preview); grid.pack(fill=tk.BOTH, expand=True)
        for i in range(2):
            grid.grid_columnconfigure(i, weight=1, uniform="preview")
            grid.grid_rowconfigure(i, weight=1, uniform="preview")

        frame_O = ttk.Frame(grid); frame_O.grid(row=0, column=0, sticky="nsew", padx=4, pady=4)
        ttk.Label(frame_O, text="Original (O)", bootstyle="secondary").pack(anchor="w")
        self.preview_O = ttk.Label(frame_O, anchor="center", relief=tk.SUNKEN, cursor="hand2"); self.preview_O.pack(fill=tk.BOTH, expand=True)
        self.preview_O.bind("<Button-1>", lambda e: self._open_preview_file("O"))

        frame_T = ttk.Frame(grid); frame_T.grid(row=0, column=1, sticky="nsew", padx=4, pady=4)
        ttk.Label(frame_T, text="Playback (T)", bootstyle="secondary").pack(anchor="w")
        self.preview_T = ttk.Label(frame_T, anchor="center", relief=tk.SUNKEN, cursor="hand2"); self.preview_T.pack(fill=tk.BOTH, expand=True)
        self.preview_T.bind("<Button-1>", lambda e: self._open_preview_file("T"))

        frame_D = ttk.Frame(grid); frame_D.grid(row=1, column=0, sticky="nsew", padx=4, pady=4)
        ttk.Label(frame_D, text="Black/White Diff (D)", bootstyle="secondary").pack(anchor="w")
        self.preview_D = ttk.Label(frame_D, anchor="center", relief=tk.SUNKEN, cursor="hand2"); self.preview_D.pack(fill=tk.BOTH, expand=True)
        self.preview_D.bind("<Button-1>", lambda e: self._open_preview_file("D"))

        frame_H = ttk.Frame(grid); frame_H.grid(row=1, column=1, sticky="nsew", padx=4, pady=4)
        ttk.Label(frame_H, text="Highlighted Diff (H)", bootstyle="secondary").pack(anchor="w")
        self.preview_H = ttk.Label(frame_H, anchor="center", relief=tk.SUNKEN, cursor="hand2"); self.preview_H.pack(fill=tk.BOTH, expand=True)
        self.preview_H.bind("<Button-1>", lambda e: self._open_preview_file("H"))

        # Log pane
        card_log = ttk.Labelframe(right_log, text="Log", padding=8)
        card_log.pack(fill=tk.BOTH, expand=True, pady=(12,0))
        self.log_text = scrolledtext.ScrolledText(card_log, height=6, wrap="word")
        self.log_text.pack(fill=tk.BOTH, expand=True)
        self.log_text.configure(state="disabled")
        self._attach_log_handler()

        # Debounced preview refresh to avoid lag/“stuck cursor”
        def _debounced_resize(_evt=None):
            if self._resize_job is not None:
                try: self.root.after_cancel(self._resize_job)
                except Exception: pass
            self._resize_job = self.root.after(160, self._refresh_current_preview)
        self.root.bind("<Configure>", _debounced_resize)

        # Context menu on tests tree
        self.menu = tk.Menu(self.root, tearoff=False)
        self.menu.add_command(label="Open JSON", command=self.open_json)
        self.menu.add_command(label="Delete Test", command=self.delete_test)

    # ---------------- tests notebook ----------------
    def _load_tests(self) -> None:
        self.tests = []
        self.procedures = []
        self._by_proc: Dict[str, List[str]] = {}
        for json_file in sorted(self.paths.scripts_dir.rglob("*.json")):
            rel = json_file.relative_to(self.paths.scripts_dir)
            rel_wo = str(rel.with_suffix(""))
            if not rel_wo:
                continue
            proc = rel_wo.split(os.sep)[0]
            self.tests.append(rel_wo)
            self._by_proc.setdefault(proc, []).append(rel_wo)
        self.procedures = sorted(self._by_proc.keys())

    def _build_notebook(self) -> None:
        for tab in self.nb.tabs():
            self.nb.forget(tab)
        self.trees.clear(); self.test_map.clear()
        for proc in self.procedures:
            frame = ttk.Frame(self.nb, padding=(6, 6))
            self.nb.add(frame, text=proc)
            tree = ttk.Treeview(frame, show="tree", height=18, bootstyle="info")
            tree.pack(fill=tk.BOTH, expand=True)
            self.trees[proc] = tree
            self._populate_tree(tree, self._by_proc[proc])
            tree.bind("<<TreeviewSelect>>", self._on_tree_select_change)
            tree.bind("<Button-3>", self._on_tree_right_click)
        self._update_selected_label()

    def _populate_tree(self, tree: ttk.Treeview, script_list: List[str]) -> None:
        nodes: Dict[Tuple[str, ...], str] = {}
        for rel_wo in sorted(script_list):
            parts = rel_wo.split(os.sep)
            path_tuple: Tuple[str, ...] = tuple()
            for i, part in enumerate(parts):
                path_tuple = (*path_tuple, part)
                if path_tuple not in nodes:
                    if i == 0:
                        node = tree.insert("", tk.END, text=part, open=True)
                    else:
                        parent = nodes[path_tuple[:-1]]
                        node = tree.insert(parent, tk.END, text=part, open=(i < len(parts) - 1))
                    nodes[path_tuple] = node
                if i == len(parts) - 1:
                    self.test_map[nodes[path_tuple]] = rel_wo

    # ---------------- record / stop ----------------
    def start_recording(self) -> None:
        dlg = NewRecordingDialog(self.root, title="New Recording")
        if dlg.result is None:
            return
        proc, sec, test = dlg.result

        def clean(s: str) -> str:
            bad = '<>:"/\\|?*'
            out = "".join(c for c in s if c not in bad)
            return out.strip().replace(" ", "_")

        script_rel = str(Path(clean(proc)) / clean(sec) / clean(test))
        json_path = self.paths.scripts_dir / f"{script_rel}.json"
        img_dir   = self.paths.images_dir  / script_rel

        if json_path.exists() or img_dir.exists():
            if not messagebox.askyesno("Overwrite?", f"{script_rel}\nexists. Overwrite JSON and screenshots?", parent=self.root):
                logging.info("Recording cancelled by user (overwrite declined).")
                return
            try:
                if json_path.exists(): json_path.unlink()
                if img_dir.exists():
                    for p in img_dir.glob("*"):
                        try: p.unlink()
                        except Exception: pass
                    try: img_dir.rmdir()
                    except Exception: pass
                logging.info(f"Cleared previous artifacts for {script_rel}.")
            except Exception as e:
                logging.exception(f"Failed to clear previous artifacts: {e}")
                return

        (self.paths.scripts_dir / Path(script_rel)).parent.mkdir(parents=True, exist_ok=True)

        gui_hwnd = self.root.winfo_id()
        self.recorder = Recorder(RecorderConfig(
            scripts_dir=self.paths.scripts_dir,
            images_dir=self.paths.images_dir,
            results_dir=self.paths.results_dir,
            script_name=script_rel,
            taskbar_crop_px=60,
            gui_hwnd=gui_hwnd,
            always_record_text=True,
            default_delay=float(self.default_delay_var.get()),
        ))
        self.recorder.start()
        logging.info(f"Recording started for: {script_rel}")
        logging.info("Hotkeys: 'p' = screenshot (primary monitor), 'Esc' = STOP (also refreshes Available Tests).")

        # Watcher to detect Esc stop and auto-refresh tree
        if self._recorder_watch_thread is None or not self._recorder_watch_thread.is_alive():
            self._recorder_watch_thread = threading.Thread(target=self._watch_recorder_stopped, daemon=True)
            self._recorder_watch_thread.start()

    def _watch_recorder_stopped(self) -> None:
        while True:
            rec = self.recorder
            if rec is None:
                return
            if not getattr(rec, "running", False):
                try: self.root.after(0, self._on_recorder_stopped)
                except Exception: pass
                return
            time.sleep(0.05)

    def _on_recorder_stopped(self) -> None:
        self.recorder = None
        logging.info("Recorder stopped.")
        self._load_tests()
        self._build_notebook()

    def stop_recording(self) -> None:
        if not self.recorder:
            return
        try:
            self.recorder.stop()
        except Exception as e:
            logging.exception(f"Error stopping recorder: {e}")
        finally:
            self._on_recorder_stopped()

    # ---------------- run / stop playback ----------------
    def run_selected(self) -> None:
        scripts = self._get_selected_scripts()
        if not scripts:
            messagebox.showinfo("No selection", "Select one or more tests to run.", parent=self.root)
            return
        self._run_scripts_async(scripts)

    def run_all(self) -> None:
        self._run_scripts_async(self.tests)

    def normalize_enfire(self) -> None:
        initial = str(self.paths.scripts_dir)
        path = filedialog.askopenfilename(
            title="Select ENFIRE normalization script",
            initialdir=initial,
            filetypes=[("JSON Scripts", "*.json")],
            parent=self.root
        )
        if not path:
            return
        try:
            rel = str(Path(path).resolve().relative_to(self.paths.scripts_dir.resolve())).replace(".json", "")
        except Exception:
            messagebox.showerror("Invalid Selection", "Choose a JSON inside the scripts folder.", parent=self.root)
            return
        self._run_scripts_async([rel])

    def _run_scripts_async(self, scripts: List[str]) -> None:
        # GUI → Player config
        self.player.config.wait_between_actions = float(self.default_delay_var.get())
        tol = float(self.tolerance_var.get())
        self.paths.tolerance = tol
        if hasattr(self.player.config, "diff_tolerance_percent"):
            self.player.config.diff_tolerance_percent = tol
        if hasattr(self.player.config, "diff_tolerance"):
            self.player.config.diff_tolerance = tol
        if hasattr(self.player.config, "use_default_delay_always"):
            self.player.config.use_default_delay_always = bool(self.use_default_delay_var.get())

        self._clear_results()
        self._thumb_cache.clear()
        self._player_running = True
        self.player.request_stop(clear_only=True)  # clear any previous stop signal
        t = threading.Thread(target=self._run_scripts_worker, args=(scripts,), daemon=True)
        t.start()

    def _run_scripts_worker(self, scripts: List[str]) -> None:
        any_fail = False
        for script_rel in scripts:
            if self.player.should_stop():
                logging.info("Playback interrupted by user (Esc).")
                break
            logging.info(f"Running: {script_rel}")
            try:
                results = self.player.play(script_rel)  # returns list of per-screenshot results
                script_failed = any(r.get("status","fail") != "pass" for r in results)
                if script_failed:
                    any_fail = True
                self._append_results(script_rel, results)
                self._thumb_cache.clear()  # ensure fresh previews on selection
                if script_failed:
                    note = write_run_bug_report(self.paths, script_rel, results)
                    if note:
                        logging.info(f"Defect draft saved: {note.note_path}")
                        if note.analysis:
                            for line in note.analysis.splitlines():
                                logging.info(f"AI Analysis: {line}")
                        if note.summary:
                            logging.info(f"AI Summary: {note.summary}")
                        if note.recommendations:
                            for rec in note.recommendations:
                                logging.info(f"AI Recommendation: {rec}")
                        try:
                            self.root.after(0, lambda s=script_rel, p=note.note_path, text=note.note_text: self._deliver_defect_note(s, p, text))
                        except Exception:
                            self._deliver_defect_note(script_rel, note.note_path, note.note_text)
            except Exception as e:
                logging.exception(f"Playback error for {script_rel}: {e}")
        self._player_running = False

    def stop_playback(self) -> None:
        self.player.request_stop()

    def _global_escape(self, _evt=None) -> None:
        # If recording, stop recording; else if playing, stop playback
        if self.recorder and getattr(self.recorder, "running", False):
            self.stop_recording()
        elif self._player_running:
            self.stop_playback()

    # ---------------- results table ----------------
    def _clear_results(self) -> None:
        for i in self.result_tree.get_children(""):
            self.result_tree.delete(i)

    def _append_results(self, script_name: str, results: List[Dict[str, str]]) -> None:
        any_fail = False
        for r in results:
            idx    = r.get("index", 0)
            orig   = r.get("original", "")
            test   = r.get("test", "")
            diffp  = r.get("diff_percent", "")
            status = r.get("status", "fail")
            tag = "pass" if status == "pass" else "fail"
            if tag == "fail":
                any_fail = True
            diff_str = f"{float(diffp):.3f}" if diffp != "" else ""
            self.result_tree.insert(
                "", tk.END,
                values=(script_name, idx, orig, test, diff_str, "✓ PASS" if tag == "pass" else "✗ FAIL"),
                tags=(tag,)
            )
        # Overall line per script
        self.result_tree.insert(
            "", tk.END,
            values=(script_name, "", "", "", "", "✓ OVERALL PASS" if not any_fail else "✗ OVERALL FAIL"),
            tags=("pass",) if not any_fail else ("fail",)
        )

    def _deliver_defect_note(self, script_rel: str, md_path: Path, note_text: str) -> None:
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(note_text)
            self.root.update()
            logging.info(f"Defect note copied to clipboard for {script_rel}: {md_path}")
        except Exception as e:
            logging.warning(f"Failed to copy defect note for {script_rel}: {e}")

    # ---------------- select & preview ----------------
    def _get_selected_scripts(self) -> List[str]:
        selected: List[str] = []
        for tree in self.trees.values():
            for node_id in tree.selection():
                script = self.test_map.get(node_id)
                if script:
                    selected.append(script)
        return sorted(set(selected))

    def _find_first_leaf(self, tree, node_id):
        if node_id in self.test_map:
            return node_id
        for child in tree.get_children(node_id):
            leaf = self._find_first_leaf(tree, child)
            if leaf:
                return leaf
        return None

    def _on_tree_select_change(self, event: Optional[tk.Event] = None) -> None:
        widget = getattr(event, "widget", None)
        if widget is not None:
            invalid = [item for item in widget.selection() if item not in self.test_map]
            if invalid:
                try:
                    for node in invalid:
                        widget.selection_remove(node)
                except Exception:
                    pass
        if self._tree_select_job is not None:
            try: self.root.after_cancel(self._tree_select_job)
            except Exception: pass
        try:
            self._tree_select_job = self.root.after(80, self._update_selected_label)
        except Exception:
            self._update_selected_label()

    def _update_selected_label(self) -> None:
        self._tree_select_job = None
        scripts = self._get_selected_scripts()
        count = len(scripts)
        if count == 0:
            text = "Selected: 0 tests"
        else:
            shown = ", ".join(scripts[:3])
            if count > 3:
                shown += f", +{count - 3} more"
            suffix = "test" if count == 1 else "tests"
            text = f"Selected: {count} {suffix}: {shown}"
        self.selected_tests_var.set(text)

    def _on_tree_right_click(self, event: tk.Event) -> None:
        widget = event.widget
        try:
            item = widget.identify_row(event.y)
            if item:
                leaf = self._find_first_leaf(widget, item)
                if leaf:
                    widget.selection_set(leaf)
                else:
                    widget.selection_remove(item)
                self._update_selected_label()
            self.menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.menu.grab_release()

    def open_json(self) -> None:
        for tree in self.trees.values():
            items = tree.selection()
            for it in items:
                rel = self.test_map.get(it)
                if not rel: continue
                path = self.paths.scripts_dir / f"{rel}.json"
                if path.exists():
                    try: os.startfile(str(path))
                    except Exception: messagebox.showinfo("Open JSON", str(path), parent=self.root)
                    return

    def delete_test(self) -> None:
        for tree in self.trees.values():
            items = tree.selection()
            for it in items:
                rel = self.test_map.get(it)
                if not rel: continue
                json_path = self.paths.scripts_dir / f"{rel}.json"
                img_dir   = self.paths.images_dir  / rel
                if not messagebox.askyesno("Delete", f"Delete\n{json_path}\nand\n{img_dir} ?", parent=self.root):
                    return
                try:
                    if json_path.exists(): json_path.unlink()
                    if img_dir.exists():
                        for p in img_dir.glob("*"):
                            try: p.unlink()
                            except Exception: pass
                        try: img_dir.rmdir()
                        except Exception: pass
                    logging.info(f"Deleted test: {rel}")
                except Exception as e:
                    logging.exception(f"Delete failed: {e}")
                self._load_tests()
                self._build_notebook()
                return

    def _on_result_select(self, _evt=None) -> None:
        if self._select_job is not None:
            try: self.root.after_cancel(self._select_job)
            except Exception: pass
        self._select_job = self.root.after(120, self._update_preview_from_selection)

    def _update_preview_from_selection(self) -> None:
        sel = self.result_tree.selection()
        if not sel: return
        vals = self.result_tree.item(sel[0], "values")
        # (script, index, original, test, diff, status)
        if len(vals) < 6: return
        orig_path = Path(vals[2]) if vals[2] else None
        test_path = Path(vals[3]) if vals[3] else None
        if orig_path and test_path:
            self._show_preview_images(orig_path, test_path)

    def _thumb_size(self) -> tuple[int, int]:
        try:
            parent = self.preview_O.master.master  # frame_O -> grid -> card_preview
            total_w = parent.winfo_width() or 1200
            total_h = parent.winfo_height() or 700
            pad_w = 24; pad_h = 36
            cell_w = max(160, (total_w - pad_w * 3) // 2)
            cell_h = max(120, (total_h - pad_h * 3) // 2)
            return (cell_w, cell_h)
        except Exception:
            return (520, 290)

    def _load_thumb(self, path: Path, maxw: int, maxh: int) -> Optional[ImageTk.PhotoImage]:
        try:
            mtime = path.stat().st_mtime  # IMPORTANT: bust stale cache when file updated
        except Exception:
            return None
        key = (str(path), mtime, maxw, maxh)
        if key in self._thumb_cache:
            return self._thumb_cache[key]
        try:
            with Image.open(path) as im:
                im = im.copy()  # detach file handle
            im.thumbnail((maxw, maxh), Image.LANCZOS)
            ph = ImageTk.PhotoImage(im)
            self._thumb_cache[key] = ph
            return ph
        except Exception:
            return None

    def _show_preview_images(self, orig_path: Path, test_path: Path) -> None:
        maxw, maxh = self._thumb_size()

        o = self._load_thumb(orig_path, maxw, maxh)
        t = self._load_thumb(test_path, maxw, maxh)

        stem = test_path.stem
        d_name = (stem[:-1] + "D") if stem and stem[-1] in ("T", "O") else (stem + "_D")
        h_name = (stem[:-1] + "H") if stem and stem[-1] in ("T", "O") else (stem + "_H")
        d_path = test_path.with_name(d_name + test_path.suffix)
        h_path = test_path.with_name(h_name + test_path.suffix)

        d = self._load_thumb(d_path, maxw, maxh)
        h = self._load_thumb(h_path, maxw, maxh)

        self.preview_O.config(image=o); self.preview_O.image = o
        self.preview_T.config(image=t); self.preview_T.image = t
        self.preview_D.config(image=d); self.preview_D.image = d
        self.preview_H.config(image=h); self.preview_H.image = h

        self._current_preview_paths.update({"O":orig_path, "T":test_path, "D":d_path, "H":h_path})

    def _refresh_current_preview(self) -> None:
        self._thumb_cache.clear()
        self._update_preview_from_selection()

    def _open_preview_file(self, key: str) -> None:
        p = self._current_preview_paths.get(key)
        if not p or not p.exists():
            return
        try:
            # Open Explorer selecting the file
            subprocess.run(['explorer', '/select,', str(p)], check=False)
        except Exception:
            # fallback: open folder
            try: os.startfile(str(p.parent))
            except Exception: pass

    # ---------------- help ----------------
    def show_instructions(self) -> None:
        txt = (
            "UI Testing — How to Use\n\n"
            "Recording a Test\n"
            "1) Click 'Record New'. Enter Procedure (e.g., 1_EBS), Section (e.g., 6), and a descriptive Test name (e.g., 1.1.1_ATTACHMENTS TAB).\n"
            "2) While recording:\n"
            "   • Mouse clicks on the ENFIRE window are saved. If an AutomationID is available, it is recorded.\n"
            "   • Keyboard typing is always recorded as text (except 'p').\n"
            "   • Press 'p' to take a checkpoint screenshot (primary monitor only; taskbar/cursor suppressed).\n"
            "   • Press 'Esc' to STOP recording from anywhere (you do not need the GUI in focus).\n"
            "   • Each step uses the Default Delay (top-right). You can also edit per-step 'delay' in the JSON.\n"
            "3) On stop, files are written next to the program folder:\n"
            "   • JSON:   scripts/<Procedure>/<Section>/<Test>.json\n"
            "   • Images: images/<...>/0_000O.png (original), 0_000T.png (test), 0_000D.png (diff), 0_000H.png (highlight)\n\n"
            "Running Tests\n"
            "1) Select tests from the tabs (Procedure → Section → Test).\n"
            "2) Click 'Run Selected' or 'Run All'. Playback waits per-step using recorded 'delay' or the GUI Default Delay.\n"
            "3) PASS ⇔ percent difference ≤ Tolerance (%). Tolerance 0.0 == exact match required.\n"
            "4) Use 'Normalize ENFIRE' to run a specific JSON that puts the app into a known baseline state before other runs.\n\n"
            "Tips\n"
            "• The GUI ignores its own clicks while recording.\n"
            "• Keep Windows scaling consistent for strict pixel comparisons.\n"
            "• Right-click a test to open/delete its JSON.\n"
        )
        win = tk.Toplevel(self.root)
        win.title("Instructions"); win.geometry("820x560")
        try: win.iconbitmap(resource_path("assets/ui_testing.ico"))
        except Exception: pass
        st = scrolledtext.ScrolledText(win, wrap="word")
        st.pack(fill=tk.BOTH, expand=True)
        st.insert("1.0", txt); st.configure(state="disabled")
        ttk.Button(win, text="Close", command=win.destroy).pack(pady=8)

    # ---------------- theme ----------------
    def _on_theme_change(self, name: str) -> None:
        try:
            self.theme_var.set(name)
            self.root.style.theme_use(name)
        except Exception as e:
            logging.getLogger(__name__).warning(f"Theme switch failed: {e}")

    # ---------------- run loop ----------------
    def run(self) -> None:
        self.root.mainloop()

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    TestRunnerGUI().run()






