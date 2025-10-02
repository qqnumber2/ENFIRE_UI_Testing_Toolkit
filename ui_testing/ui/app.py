# ui_testing/ui/app.py
from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Sequence

import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext

import ttkbootstrap as ttk
from ttkbootstrap.toast import ToastNotification

from ui_testing.environment import Paths, build_default_paths, resource_path
from ui_testing.dialogs import NewRecordingDialog, RecordingRequest
from ui_testing.player import Player, PlayerConfig
from ui_testing.recorder import Recorder, RecorderConfig
from ui_testing.ai_summarizer import write_run_bug_report, BugNote
from ui_testing.settings import AppSettings
from ui_testing.testplan import TestPlanReporter
from ui_testing.ui.notes import NoteEntry
from ui_testing.ui.panels import (
    ActionsPanel,
    TestsPanel,
    ResultsPanel,
    PreviewPanel,
    LogPanel,
    open_path_in_explorer,
)

_LOGGER = logging.getLogger(__name__)


class TestRunnerApp:
    """High-level GUI controller for recording and replaying UI tests."""

    def __init__(self) -> None:
        # --- root window & Tk variables ---
        self.root = ttk.Window(themename="cosmo")
        self.root.title("UI Testing")
        self.root.geometry("1480x940")
        try:
            self.root.iconbitmap(resource_path("assets/ui_testing.ico"))
        except Exception:
            pass

        self.theme_var = tk.StringVar(master=self.root, value="cosmo")
        self.default_delay_var = tk.DoubleVar(master=self.root, value=0.5)
        self.tolerance_var = tk.DoubleVar(master=self.root, value=0.01)
        self.use_default_delay_var = tk.BooleanVar(master=self.root, value=False)
        self.use_automation_ids_var = tk.BooleanVar(master=self.root, value=True)
        self.normalize_label_var = tk.StringVar(master=self.root, value="Normalize: Not set")

        # --- filesystem paths & persisted settings ---
        self.paths: Paths = build_default_paths()
        self.settings_path = self.paths.root / "ui_settings.json"
        self.settings = AppSettings.load(self.settings_path)
        self.normalize_script: Optional[str] = self.settings.normalize_script
        self._apply_settings_to_variables()
        self.paths.tolerance = float(self.tolerance_var.get())

        if self.paths.test_plan:
            _LOGGER.info("Detected test plan: %s", self.paths.test_plan)
        self.testplan_reporter: Optional[TestPlanReporter] = (
            TestPlanReporter(self.paths.test_plan) if self.paths.test_plan else None
        )

        try:
            os.chdir(self.paths.root)
        except Exception:
            pass

        # --- logging ---
        self._setup_logging()

        # --- core engine objects ---
        self.recorder: Optional[Recorder] = None
        self._recorder_watch_thread: Optional[threading.Thread] = None
        self._player_running = False

        self.player = Player(
            PlayerConfig(
                scripts_dir=self.paths.scripts_dir,
                images_dir=self.paths.images_dir,
                results_dir=self.paths.results_dir,
                taskbar_crop_px=60,
                wait_between_actions=float(self.default_delay_var.get()),
                diff_tolerance=float(self.tolerance_var.get()),
                diff_tolerance_percent=float(self.tolerance_var.get()),
                use_default_delay_always=bool(self.use_default_delay_var.get()),
                use_automation_ids=bool(self.use_automation_ids_var.get()),
            )
        )

        # --- GUI assembly ---
        self.actions_panel: ActionsPanel
        self.tests_panel: TestsPanel
        self.results_panel: ResultsPanel
        self.preview_panel: PreviewPanel
        self.log_panel: LogPanel
        self._build_layout()
        self._apply_theme(self.theme_var.get())
        self._bind_setting_traces()

        self._current_result_row: Optional[Dict[str, str]] = None
        self._resize_job: Optional[str] = None

        self._load_tests()
        self.root.bind("<Escape>", self._global_escape)
        self.root.bind("<Configure>", self._on_window_resize)

    # ------------------------------------------------------------------
    # Layout & logging
    # ------------------------------------------------------------------
    def _build_layout(self) -> None:
        self.actions_panel = ActionsPanel(
            self.root,
            theme_var=self.theme_var,
            default_delay_var=self.default_delay_var,
            tolerance_var=self.tolerance_var,
            use_default_delay_var=self.use_default_delay_var,
            use_automation_ids_var=self.use_automation_ids_var,
            normalize_label_var=self.normalize_label_var,
            record_callback=self.start_recording,
            stop_record_callback=self.stop_recording,
            run_selected_callback=self.run_selected,
            run_all_callback=self.run_all,
            normalize_callback=self.run_normalize_script,
            choose_normalize_callback=self.select_normalize_script,
            open_logs_callback=self.open_logs,
            instructions_callback=self.show_instructions,
            theme_change_callback=self._on_theme_change,
        )
        self.actions_panel.pack(side=tk.TOP, fill=tk.X)

        body = ttk.Panedwindow(self.root, orient=tk.HORIZONTAL)
        body.pack(fill=tk.BOTH, expand=True, padx=12, pady=(0, 12))

        left = ttk.Frame(body)
        body.add(left, weight=1)

        right_panes = ttk.Panedwindow(body, orient=tk.VERTICAL)
        body.add(right_panes, weight=3)

        right_results = ttk.Frame(right_panes)
        right_preview = ttk.Frame(right_panes)
        right_log = ttk.Frame(right_panes)
        right_panes.add(right_results, weight=2)
        right_panes.add(right_preview, weight=3)
        right_panes.add(right_log, weight=1)

        self.tests_panel = TestsPanel(
            left,
            on_selection_change=self._on_tests_selection_changed,
            on_open_json=self.open_json,
            on_delete_test=self.delete_test,
        )
        self.tests_panel.pack(fill=tk.BOTH, expand=True)

        self.results_panel = ResultsPanel(
            right_results,
            on_result_select=self._on_result_row_selected,
            on_note_open=self._open_note_file,
        )
        self.results_panel.pack(fill=tk.BOTH, expand=True)

        self.preview_panel = PreviewPanel(right_preview)
        self.preview_panel.pack(fill=tk.BOTH, expand=True)
        self.preview_panel.bind_open_handlers(self._open_preview_file)

        self.log_panel = LogPanel(right_log)
        self.log_panel.pack(fill=tk.BOTH, expand=True)
        self.log_panel.attach_logger()

        self._update_normalize_label()

    def _setup_logging(self) -> None:
        root_logger = logging.getLogger()
        if not root_logger.handlers:
            logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
        else:
            root_logger.setLevel(logging.INFO)

    # ------------------------------------------------------------------
    # Tests discovery & selection
    # ------------------------------------------------------------------
    def _load_tests(self) -> None:
        grouped: Dict[str, List[str]] = {}
        scripts_dir = self.paths.scripts_dir
        if scripts_dir.exists():
            for json_file in sorted(scripts_dir.rglob("*.json")):
                rel = json_file.relative_to(scripts_dir).with_suffix("")
                if not rel.parts:
                    continue
                proc = rel.parts[0]
                grouped.setdefault(proc, []).append(rel)
        self.tests_panel.populate(grouped)
        self.tests_panel.refresh_selection()

    # ------------------------------------------------------------------
    # Recording flows
    # ------------------------------------------------------------------
    def start_recording(self) -> None:
        dlg = NewRecordingDialog(self.root, title="New Recording")
        request: Optional[RecordingRequest] = dlg.result
        if request is None:
            return

        script_rel = self._sanitize_recording_request(request)
        json_path = self.paths.scripts_dir / f"{script_rel}.json"
        img_dir = self.paths.images_dir / script_rel

        if json_path.exists() or img_dir.exists():
            if not messagebox.askyesno(
                "Overwrite?",
                f"{script_rel}\nexists. Overwrite JSON and screenshots?",
                parent=self.root,
            ):
                _LOGGER.info("Recording cancelled by user (overwrite declined).")
                return
            self._clear_previous_artifacts(json_path, img_dir)

        (self.paths.scripts_dir / Path(script_rel)).parent.mkdir(parents=True, exist_ok=True)

        gui_hwnd = self.root.winfo_id()
        self.recorder = Recorder(
            RecorderConfig(
                scripts_dir=self.paths.scripts_dir,
                images_dir=self.paths.images_dir,
                results_dir=self.paths.results_dir,
                script_name=script_rel,
                taskbar_crop_px=60,
                gui_hwnd=gui_hwnd,
                always_record_text=True,
                default_delay=float(self.default_delay_var.get()),
            )
        )
        self.recorder.start()
        _LOGGER.info("Recording started for: %s", script_rel)
        _LOGGER.info("Hotkeys: 'p' = screenshot (primary monitor), 'Esc' = STOP (also refreshes Available Tests).")

        if self._recorder_watch_thread is None or not self._recorder_watch_thread.is_alive():
            self._recorder_watch_thread = threading.Thread(target=self._watch_recorder_stopped, daemon=True)
            self._recorder_watch_thread.start()

    def _sanitize_recording_request(self, request: RecordingRequest) -> str:
        def clean(value: str) -> str:
            bad = '<>:"/\\|?*'
            out = "".join(c for c in value if c not in bad)
            return out.strip().replace(" ", "_")

        return str(Path(clean(request.procedure)) / clean(request.section) / clean(request.test_name))

    def _clear_previous_artifacts(self, json_path: Path, img_dir: Path) -> None:
        try:
            if json_path.exists():
                json_path.unlink()
            if img_dir.exists():
                for p in img_dir.glob("*"):
                    try:
                        p.unlink()
                    except Exception:
                        pass
                try:
                    img_dir.rmdir()
                except Exception:
                    pass
            _LOGGER.info("Cleared previous artifacts for %s", json_path.stem)
        except Exception as exc:
            logging.exception("Failed to clear previous artifacts: %s", exc)

    def _watch_recorder_stopped(self) -> None:
        while True:
            rec = self.recorder
            if rec is None:
                return
            if not getattr(rec, "running", False):
                try:
                    self.root.after(0, self._on_recorder_stopped)
                except Exception:
                    pass
                return
            time.sleep(0.05)

    def _on_recorder_stopped(self) -> None:
        self.recorder = None
        _LOGGER.info("Recorder stopped.")
        self._load_tests()

    def stop_recording(self) -> None:
        if not self.recorder:
            return
        try:
            self.recorder.stop()
        except Exception as exc:
            logging.exception("Error stopping recorder: %s", exc)
        finally:
            self._on_recorder_stopped()

    # ------------------------------------------------------------------
    # Playback flows
    # ------------------------------------------------------------------
    def run_selected(self) -> None:
        scripts = self.tests_panel.selected_scripts()
        if not scripts:
            messagebox.showinfo("No selection", "Select one or more tests to run.", parent=self.root)
            return
        self._run_scripts_async(scripts)

    def run_all(self) -> None:
        scripts = sorted({str(p.relative_to(self.paths.scripts_dir).with_suffix("")) for p in self.paths.scripts_dir.rglob("*.json")})
        scripts = [s.replace("\\", "/") for s in scripts]
        if not scripts:
            messagebox.showinfo("No tests", "No recorded tests were found.", parent=self.root)
            return
        self._run_scripts_async(scripts)

    def select_normalize_script(self) -> None:
        initial = str(self.paths.scripts_dir)
        path = filedialog.askopenfilename(
            title="Select Normalize ENFIRE Script",
            initialdir=initial,
            filetypes=[("JSON Scripts", "*.json")],
            parent=self.root,
        )
        if not path:
            return
        resolved = Path(path).resolve()
        try:
            rel = resolved.relative_to(self.paths.scripts_dir.resolve())
        except ValueError:
            messagebox.showerror(
                "Invalid Selection",
                "Choose a JSON inside the scripts folder.",
                parent=self.root,
            )
            return
        script_rel = str(rel.with_suffix(""))
        self.normalize_script = script_rel.replace("\\", "/")
        self.settings.normalize_script = self.normalize_script
        self._update_normalize_label()
        self._save_settings()

    def run_normalize_script(self) -> None:
        if not self.normalize_script:
            if messagebox.askyesno(
                "Normalize ENFIRE",
                "No normalize script selected. Would you like to choose one?",
                parent=self.root,
            ):
                previous = self.normalize_script
                self.select_normalize_script()
                if self.normalize_script and self.normalize_script != previous:
                    self._run_scripts_async([self.normalize_script])
            return
        self._run_scripts_async([self.normalize_script])

    def _run_scripts_async(self, scripts: Sequence[str]) -> None:
        self.player.config.wait_between_actions = float(self.default_delay_var.get())
        tol = float(self.tolerance_var.get())
        self.paths.tolerance = tol
        if hasattr(self.player.config, "diff_tolerance_percent"):
            self.player.config.diff_tolerance_percent = tol
        if hasattr(self.player.config, "diff_tolerance"):
            self.player.config.diff_tolerance = tol
        if hasattr(self.player.config, "use_default_delay_always"):
            self.player.config.use_default_delay_always = bool(self.use_default_delay_var.get())

        self.results_panel.clear()
        self.preview_panel.reset()
        self._player_running = True
        self.player.request_stop(clear_only=True)

        thread = threading.Thread(target=self._run_scripts_worker, args=(list(scripts),), daemon=True)
        thread.start()

    def _run_scripts_worker(self, scripts: Sequence[str]) -> None:
        for script_rel in scripts:
            if self.player.should_stop():
                _LOGGER.info("Playback interrupted by user (Esc).")
                break
            _LOGGER.info("Running: %s", script_rel)
            try:
                results = self.player.play(script_rel)
                script_failed = any(r.get("status", "fail") != "pass" for r in results)
                if script_failed:
                    self._register_note(script_rel, results)
                else:
                    self._report_test_outcome(script_rel, True)
                self._append_results(script_rel, results)
                if script_failed:
                    self._report_test_outcome(script_rel, False)
            except Exception as exc:
                logging.exception("Playback error for %s: %s", script_rel, exc)
                self._report_test_outcome(script_rel, False)
        self._player_running = False

    def stop_playback(self) -> None:
        self.player.request_stop()

    # ------------------------------------------------------------------
    # Results & AI notes
    # ------------------------------------------------------------------
    def _append_results(self, script_name: str, results: Sequence[Dict[str, str]]) -> None:
        try:
            self.root.after(0, lambda: self.results_panel.append_results(script_name, results))
        except Exception:
            pass

    def _register_note(self, script_rel: str, results: Sequence[Dict[str, str]]) -> None:
        note: Optional[BugNote] = write_run_bug_report(self.paths, script_rel, results)
        if not note:
            return

        entry = NoteEntry(script=script_rel, created_at=datetime.now(), bug_note=note)

        def update_ui() -> None:
            self.results_panel.add_note(script_rel, entry)
            if note.analysis:
                for line in note.analysis.splitlines():
                    _LOGGER.info("AI Analysis: %s", line)
            if note.summary:
                _LOGGER.info("AI Summary: %s", note.summary)
            if note.recommendations:
                for rec in note.recommendations:
                    _LOGGER.info("AI Recommendation: %s", rec)
            self._clipboard_note(note)

        try:
            self.root.after(0, update_ui)
        except Exception:
            update_ui()

    def _clipboard_note(self, note: BugNote) -> None:
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(note.note_text)
            self.root.update()
            _LOGGER.info("Defect note copied to clipboard: %s", note.note_path)
        except Exception as exc:
            _LOGGER.warning("Failed to copy defect note to clipboard: %s", exc)

    def _report_test_outcome(self, script_rel: str, passed: bool) -> None:
        if not self.testplan_reporter:
            return
        try:
            self.testplan_reporter.mark_section(script_rel, passed)
            self._show_testplan_toast(script_rel, passed)
        except Exception as exc:
            _LOGGER.warning("Failed updating test plan for %s: %s", script_rel, exc)

    def _show_testplan_toast(self, script_rel: str, passed: bool) -> None:
        if not self.testplan_reporter:
            return
        status = "PASS" if passed else "FAIL"
        boot = "success" if passed else "danger"
        workbook = self.testplan_reporter.workbook_path.name if self.testplan_reporter.workbook_path else "Test Plan"
        message = f"{workbook}: {script_rel} -> {status}"
        try:
            ToastNotification(title="Test Plan Updated", message=message, duration=4000, bootstyle=boot).show_toast()
        except Exception:
            _LOGGER.info("Test Plan Updated: %s", message)

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------
    def _on_tests_selection_changed(self) -> None:
        # Selection label handled inside TestsPanel
        pass

    def _on_result_row_selected(self, row: Dict[str, str]) -> None:
        self._current_result_row = row
        original = row.get("original") or ""
        test = row.get("test") or ""
        if not original or not test:
            return
        orig_path = Path(original)
        test_path = Path(test)
        if not orig_path.exists() or not test_path.exists():
            return
        try:
            self.preview_panel.update_images(orig_path, test_path)
        except Exception as exc:
            _LOGGER.debug("Failed to update preview: %s", exc)

    def _open_note_file(self, path: Path) -> None:
        if not path.exists():
            messagebox.showinfo("Missing", f"Note file not found:\n{path}", parent=self.root)
            return
        open_path_in_explorer(path)

    def _open_preview_file(self, key: str) -> None:
        paths = self.preview_panel.current_paths()
        target = paths.get(key)
        if not target or not target.exists():
            return
        open_path_in_explorer(target)

    def _on_window_resize(self, _evt: tk.Event) -> None:
        if self._resize_job is not None:
            try:
                self.root.after_cancel(self._resize_job)
            except Exception:
                pass
        self._resize_job = self.root.after(200, self._refresh_preview)

    def _refresh_preview(self) -> None:
        self._resize_job = None
        if not self._current_result_row:
            return
        self._on_result_row_selected(self._current_result_row)

    def _global_escape(self, _evt: Optional[tk.Event] = None) -> None:
        if self.recorder and getattr(self.recorder, "running", False):
            self.stop_recording()
        elif self._player_running:
            self.stop_playback()

    # ------------------------------------------------------------------
    # Test asset helpers
    # ------------------------------------------------------------------
    def open_logs(self) -> None:
        target = self._log_file if self._log_file.exists() else self.paths.results_dir
        try:
            open_path_in_explorer(target)
        except Exception:
            messagebox.showinfo("Open Logs", str(target), parent=self.root)

    def open_json(self, rel: str) -> None:
        path = self.paths.scripts_dir / f"{rel}.json"
        if not path.exists():
            messagebox.showinfo("Missing", f"JSON not found:\n{path}", parent=self.root)
            return
        try:
            os.startfile(str(path))  # type: ignore[attr-defined]
        except Exception:
            messagebox.showinfo("Open JSON", str(path), parent=self.root)

    def delete_test(self, rel: str) -> None:
        json_path = self.paths.scripts_dir / f"{rel}.json"
        img_dir = self.paths.images_dir / rel
        if not messagebox.askyesno(
            "Delete",
            f"Delete\n{json_path}\nand\n{img_dir}?",
            parent=self.root,
        ):
            return
        try:
            if json_path.exists():
                json_path.unlink()
            if img_dir.exists():
                for p in img_dir.glob("*"):
                    try:
                        p.unlink()
                    except Exception:
                        pass
                try:
                    img_dir.rmdir()
                except Exception:
                    pass
            _LOGGER.info("Deleted test: %s", rel)
        except Exception as exc:
            logging.exception("Delete failed: %s", exc)
        self._load_tests()

    # ------------------------------------------------------------------
    # Instructions & theme
    # ------------------------------------------------------------------
    def show_instructions(self) -> None:
        win = tk.Toplevel(self.root)
        win.title("Instructions")
        win.geometry("820x600")
        try:
            win.iconbitmap(resource_path("assets/ui_testing.ico"))
        except Exception:
            pass

        notebook = ttk.Notebook(win, bootstyle="pills")
        notebook.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        sections = [
            ("Overview", "UI Testing Overview\n\n- Available Tests displays scripts as procedure/section/test (e.g. 4/1/1).\n- The counter badge reflects how many tests are currently selected.\n- Use the toolbar to adjust tolerance, delay, theme, and the ENFIRE normalization script.\n"),
            ("Recording", "Recording a Test\n\n1) Click 'Record New'. Enter procedure (e.g. 4), section (e.g. 1), and a descriptive test name.\n2) While recording:\n   - Mouse clicks capture Automation IDs when available.\n   - Keyboard typing is recorded (press 'p' to capture a checkpoint).\n   - Press 'Esc' from anywhere to stop recording and refresh the Available Tests tree.\n3) Output lives beside the program: JSON in scripts/<proc>/<sec>/<test>.json and screenshots under images/.\n"),
            ("Playback", "Playback & Toggles\n\n- Select tests from the tree then run them with 'Run Selected' or 'Run All'.\n- 'Ignore recorded delays' forces the default delay between steps.\n- 'Use Automation IDs' toggles UIA lookups; disable it for pure coordinate playback.\n- Default delay and tolerance spinners tune pacing and diff thresholds on the fly.\n"),
            ("Results", "Results, Notes, and Test Plan\n\n- The Results panel lists checkpoints with pass/fail status and diff percent.\n- Passing or failing a run updates the ENFIRE XLSM (procedure.section sheets) and shows a confirmation toast.\n- Failing runs automatically create a bug draft in results/<proc>/<sec>/<test>/.\n"),
            ("Tips", "Tips & Shortcuts\n\n- Right-click a test to open or delete its JSON.\n- Hotkeys: 'p' captures a screenshot, 'Esc' stops playback/recording, 'Ctrl+L' opens the logs folder.\n- Keep Windows scaling consistent to minimize screenshot drift.\n"),
        ]
        for title, body in sections:
            frame = ttk.Frame(notebook, padding=12)
            notebook.add(frame, text=title)
            text_widget = scrolledtext.ScrolledText(frame, wrap="word", height=18)
            text_widget.pack(fill=tk.BOTH, expand=True)
            text_widget.insert("1.0", body)
            text_widget.configure(state="disabled")

        ttk.Button(win, text="Close", command=win.destroy, bootstyle="secondary").pack(pady=8)

    def _on_theme_change(self, name: str) -> None:
        self.theme_var.set(name)
        self._apply_theme(name)
        self._save_settings()

    def run(self) -> None:
        self.root.mainloop()

    # ------------------------------------------------------------------
    # Settings helpers
    # ------------------------------------------------------------------
    def _apply_theme(self, name: str) -> None:
        try:
            self.root.style.theme_use(name)
        except Exception as exc:
            _LOGGER.warning("Theme switch failed: %s", exc)
        else:
            try:
                self.tests_panel.on_theme_changed()
            except Exception:
                pass

    def _apply_settings_to_variables(self) -> None:
        if self.settings.theme:
            self.theme_var.set(self.settings.theme)
        self.default_delay_var.set(float(self.settings.default_delay))
        self.tolerance_var.set(float(self.settings.tolerance))
        self.use_default_delay_var.set(bool(self.settings.ignore_recorded_delays))
        self.use_automation_ids_var.set(bool(getattr(self.settings, "use_automation_ids", True)))
        self.normalize_script = self.settings.normalize_script
        self._update_normalize_label()

    def _bind_setting_traces(self) -> None:
        self.default_delay_var.trace_add("write", lambda *_: self._on_default_delay_changed())
        self.tolerance_var.trace_add("write", lambda *_: self._on_tolerance_changed())
        self.use_default_delay_var.trace_add("write", lambda *_: self._on_ignore_delays_changed())
        self.use_automation_ids_var.trace_add("write", lambda *_: self._on_use_automation_ids_changed())

    def _on_use_automation_ids_changed(self) -> None:
        value = bool(self.use_automation_ids_var.get())
        self.settings.use_automation_ids = value
        self.player.config.use_automation_ids = value
        self._save_settings()

    def _on_default_delay_changed(self) -> None:
        try:
            self.settings.default_delay = float(self.default_delay_var.get())
        except tk.TclError:
            return
        self._save_settings()

    def _on_tolerance_changed(self) -> None:
        try:
            value = float(self.tolerance_var.get())
        except tk.TclError:
            return
        self.paths.tolerance = value
        self.settings.tolerance = value
        self._save_settings()

    def _on_ignore_delays_changed(self) -> None:
        self.settings.ignore_recorded_delays = bool(self.use_default_delay_var.get())
        self._save_settings()

    def _update_normalize_label(self) -> None:
        if self.normalize_script:
            self.normalize_label_var.set(f"Normalize: {self.normalize_script}")
        else:
            self.normalize_label_var.set("Normalize: Not set")

    def _save_settings(self) -> None:
        self.settings.theme = self.theme_var.get()
        try:
            self.settings.default_delay = float(self.default_delay_var.get())
        except tk.TclError:
            pass
        try:
            self.settings.tolerance = float(self.tolerance_var.get())
        except tk.TclError:
            pass
        self.settings.ignore_recorded_delays = bool(self.use_default_delay_var.get())
        self.settings.use_automation_ids = bool(self.use_automation_ids_var.get())
        self.settings.normalize_script = self.normalize_script
        self.settings.save(self.settings_path)


def run_app() -> None:
    app = TestRunnerApp()
    app.run()


