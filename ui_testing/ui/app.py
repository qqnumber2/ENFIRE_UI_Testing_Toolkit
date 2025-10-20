# ui_testing/ui/app.py
from __future__ import annotations

import json
import sys
import logging
import os
import threading
import time
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext

import ttkbootstrap as ttk
from ttkbootstrap.toast import ToastNotification

try:
    from pynput import keyboard as pynput_keyboard
except Exception:
    pynput_keyboard = None  # type: ignore[attr-defined]

package_root = Path(__file__).resolve().parents[2]
if str(package_root) not in sys.path:
    sys.path.insert(0, str(package_root))

from ui_testing.app.environment import Paths, build_default_paths, resource_path
from ui_testing.ui.dialogs import NewRecordingDialog, RecordingRequest
from ui_testing.ui.background import VideoBackground
from ui_testing.automation.player import Player, PlayerConfig
from ui_testing.automation.semantic import reset_semantic_context
from ui_testing.automation.recorder import Recorder, RecorderConfig
from ui_testing.services.ai_summarizer import write_run_bug_report, BugNote
from ui_testing.app.settings import AppSettings
from ui_testing.services.testplan import TestPlanReporter
from ui_testing.ui.notes import NoteEntry
from ui_testing.ui.panels import (
    ActionsPanel,
    TestsPanel,
    ResultsPanel,
    PreviewPanel,
    LogPanel,
    open_path_in_explorer,
)
from ui_testing.ui.settings_dialog import SettingsDialog

_LOGGER = logging.getLogger(__name__)


class _NullBackground:
    """Fallback background controller when no video is available."""

    def start(self) -> None:  # pragma: no cover - trivial no-op
        return

    def stop(self) -> None:  # pragma: no cover - trivial no-op
        return


class TestRunnerApp:
    """High-level GUI controller for recording and replaying UI tests."""

    def __init__(self) -> None:
        # --- root window & Tk variables ---
        self.root = ttk.Window(themename="cosmo")
        self.root.withdraw()
        self.root.title("UI Testing")
        self._default_geometry = "1480x940"
        self.root.geometry(self._default_geometry)
        try:
            self.root.minsize(1180, 720)
        except Exception:
            pass
        try:
            self.root.iconbitmap(resource_path("assets/ui_testing.ico"))
        except Exception:
            pass

        self.theme_var = tk.StringVar(master=self.root, value="cosmo")
        self.default_delay_var = tk.DoubleVar(master=self.root, value=0.5)
        self.tolerance_var = tk.DoubleVar(master=self.root, value=0.01)
        self.use_default_delay_var = tk.BooleanVar(master=self.root, value=False)
        self.use_automation_ids_var = tk.BooleanVar(master=self.root, value=True)
        self.use_screenshots_var = tk.BooleanVar(master=self.root, value=True)
        self.prefer_semantic_var = tk.BooleanVar(master=self.root, value=True)
        self.use_ssim_var = tk.BooleanVar(master=self.root, value=False)
        self.ssim_threshold_var = tk.DoubleVar(master=self.root, value=0.99)
        self.automation_backend_var = tk.StringVar(master=self.root, value="uia")
        self.normalize_label_var = tk.StringVar(master=self.root, value="Normalize: Not set")
        self._theme_choices = sorted(set(self.root.style.theme_names()))

        # --- filesystem paths & persisted settings ---
        self.paths: Paths = build_default_paths()
        self.settings_path = self.paths.data_root / "ui_settings.json"
        self._log_file = self.paths.logs_dir / "ui_testing.log"
        self.settings = AppSettings.load(self.settings_path)
        self.normalize_script: Optional[str] = self.settings.normalize_script
        self._apply_settings_to_variables()
        self.paths.tolerance = float(self.tolerance_var.get())
        self.automation_manifest: Dict[str, Dict[str, str]] = self._load_automation_manifest()

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

        self._background = self._init_background()
        self._body_paned = None
        self._left_panes = None

        self._restore_window_state()

        # --- core engine objects ---
        self.recorder: Optional[Recorder] = None
        self._recorder_watch_thread: Optional[threading.Thread] = None
        self._player_running = False
        self._hotkey_listener = None

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
                use_screenshots=bool(self.use_screenshots_var.get()),
                prefer_semantic_scripts=bool(self.prefer_semantic_var.get()),
                use_ssim=bool(self.use_ssim_var.get()),
                ssim_threshold=float(self.ssim_threshold_var.get()),
                automation_backend=str(self.automation_backend_var.get()).lower(),
                appium_server_url=getattr(self.settings, "appium_server_url", None),
                appium_capabilities=getattr(self.settings, "appium_capabilities", None) or None,
                enable_allure=True,
                flake_stats_path=self.paths.data_root / "flake_stats.json",
                state_snapshot_dir=self.paths.data_root / "snapshots",
                automation_manifest=self.automation_manifest or None,
            )
        )
        self.player.update_automation_manifest(self.automation_manifest)

        # --- GUI assembly ---
        self.actions_panel: ActionsPanel
        self.tests_panel: TestsPanel
        self.results_panel: ResultsPanel
        self.preview_panel: PreviewPanel
        self.log_panel: LogPanel
        self._build_layout()
        self._apply_theme(self.theme_var.get())
        self._bind_setting_traces()

        if not getattr(self.settings, "window_geometry", None):
            self.root.after(150, self._set_initial_sash_positions)

        self._current_result_row: Optional[Dict[str, str]] = None
        self._resize_job: Optional[str] = None

        self.root.protocol("WM_DELETE_WINDOW", self._on_window_close)

        self.root.deiconify()
        try:
            self._background.start()
        except Exception:
            pass
        self._load_tests()
        self.root.bind("<KeyPress-f>", self._global_escape)
        self.root.bind("<KeyPress-F>", self._global_escape)
        self.root.bind("<Configure>", self._on_window_resize)
        self._bind_shortcuts()
        self._start_global_hotkeys()

    # ------------------------------------------------------------------
    # Layout & logging
    # ------------------------------------------------------------------
    def _build_layout(self) -> None:
        self.actions_panel = ActionsPanel(
            self.root,
            record_callback=self.start_recording,
            stop_record_callback=self.stop_recording,
            run_selected_callback=self.run_selected,
            run_all_callback=self.run_all,
            normalize_callback=self.run_normalize_script,
            choose_normalize_callback=self.select_normalize_script,
            normalize_label_var=self.normalize_label_var,
            clear_normalize_callback=self.clear_normalize_script,
            open_logs_callback=self.open_logs,
            instructions_callback=self.show_instructions,
            settings_callback=self.open_settings_dialog,
            semantic_helper_callback=self.semantic_upgrade_selected_scripts,
        )
        self.actions_panel.pack(side=tk.TOP, fill=tk.X)

        body = ttk.Panedwindow(self.root, orient=tk.HORIZONTAL)
        body.pack(fill=tk.BOTH, expand=True, padx=12, pady=(0, 12))
        self._body_paned = body

        left_panes = ttk.Panedwindow(body, orient=tk.VERTICAL)
        body.add(left_panes, weight=1)
        self._left_panes = left_panes

        tests_frame = ttk.Frame(left_panes)
        logs_frame = ttk.Frame(left_panes)
        left_panes.add(tests_frame, weight=3)
        left_panes.add(logs_frame, weight=2)

        right_panes = ttk.Panedwindow(body, orient=tk.VERTICAL)
        body.add(right_panes, weight=4)

        right_results = ttk.Frame(right_panes)
        right_preview = ttk.Frame(right_panes)
        right_panes.add(right_results, weight=1)
        right_panes.add(right_preview, weight=5)

        self.tests_panel = TestsPanel(
            tests_frame,
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

        self.log_panel = LogPanel(logs_frame)
        self.log_panel.pack(fill=tk.BOTH, expand=True)
        self.log_panel.attach_logger()

        self._update_normalize_label()

    def _init_background(self) -> VideoBackground | _NullBackground:
        """Create the ambient video background if a source can be found."""
        try:
            video_path = self._resolve_background_video()
        except Exception:
            _LOGGER.exception("Failed to resolve video background path.")
            return _NullBackground()
        if video_path is None:
            _LOGGER.info("Video background not available; continuing without it.")
            return _NullBackground()
        try:
            return VideoBackground(self.root, video_path, alpha=0.42)
        except Exception:
            _LOGGER.exception("Failed to initialize video background.")
            return _NullBackground()

    def _resolve_background_video(self) -> Optional[str]:
        """Locate the background video, honoring overrides and fallbacks."""
        candidates: List[Path] = []

        env_override = os.environ.get("UI_TESTING_BACKGROUND")
        if env_override:
            candidates.append(Path(env_override).expanduser())

        settings_override = getattr(self.settings, "background_video", None)
        if settings_override:
            candidates.append(Path(settings_override).expanduser())

        module_path = Path(__file__).resolve()
        repo_assets = module_path.parents[2] / "assets" / "background.mp4"
        candidates.append(repo_assets)

        parent_assets = module_path.parents[3] / "assets" / "background.mp4"
        if parent_assets != repo_assets:
            candidates.append(parent_assets)

        for candidate in candidates:
            if candidate.is_file():
                resolved = str(candidate)
                _LOGGER.info("Using video background: %s", resolved)
                return resolved
        return None

    def _setup_logging(self) -> None:
        root_logger = logging.getLogger()
        formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
        file_handler_attached = False
        try:
            self._log_file.parent.mkdir(parents=True, exist_ok=True)
            for handler in root_logger.handlers:
                if isinstance(handler, logging.FileHandler) and getattr(handler, "baseFilename", None) == str(self._log_file):
                    file_handler_attached = True
                    break
            if not file_handler_attached:
                file_handler = RotatingFileHandler(self._log_file, maxBytes=1_048_576, backupCount=3, encoding="utf-8")
                file_handler.setFormatter(formatter)
                root_logger.addHandler(file_handler)
        except Exception:
            logging.exception("Failed to initialize file logging")

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
        _LOGGER.info("Hotkeys: 'p' = screenshot (primary monitor), 'F' = STOP (also refreshes Available Tests).")

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

    def clear_normalize_script(self) -> None:
        if not self.normalize_script:
            messagebox.showinfo("Normalize ENFIRE", "No normalization script is currently set.", parent=self.root)
            return
        self.normalize_script = None
        self.settings.normalize_script = None
        self._update_normalize_label()
        self._save_settings()
        _LOGGER.info("Normalize script cleared.")

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
        self.results_panel.begin_run(len(scripts))
        self._player_running = True
        self.player.request_stop(clear_only=True)

        thread = threading.Thread(target=self._run_scripts_worker, args=(list(scripts),), daemon=True)
        thread.start()

    def _run_scripts_worker(self, scripts: Sequence[str]) -> None:
        last_procedure: Optional[str] = None
        total_scripts = max(1, len(scripts))
        for idx, script_rel in enumerate(scripts, start=1):
            if self.player.should_stop():
                _LOGGER.info("Playback interrupted by user (F).")
                break
            procedure = self._extract_procedure(script_rel)
            if procedure and procedure != last_procedure:
                self._normalize_if_required(procedure, script_rel)
                last_procedure = procedure
            self._focus_target_app()
            _LOGGER.info("Running: %s", script_rel)
            try:
                results = self.player.play(script_rel)
                summary_entry = next((r for r in results if str(r.get("index")).lower() == "summary"), None)
                has_result_fail = any(
                    r.get("status") == "fail" for r in results if str(r.get("index")).lower() != "summary"
                )
                script_failed = any(r.get("status", "fail") != "pass" for r in results)
                warn_only = False
                if summary_entry and summary_entry.get("status") == "warn" and not has_result_fail:
                    warn_only = True
                if script_failed:
                    if warn_only:
                        note = summary_entry.get("note", "Semantic playback executed without any validations.") if summary_entry else "Semantic playback executed without any validations."
                        self._notify_semantic_warning(script_rel, note)
                    else:
                        self._register_note(script_rel, results)
                else:
                    self._report_test_outcome(script_rel, True)
                self._append_results(script_rel, results)
                last_checkpoint: Optional[str] = None
                checkpoint_ts: Optional[str] = None
                if results:
                    detail_entries = [r for r in results if str(r.get("index")).lower() != "summary"]
                    last_entry = detail_entries[-1] if detail_entries else None
                    if last_entry:
                        raw_idx = last_entry.get("index")
                        try:
                            last_checkpoint = str(int(raw_idx) + 1)
                        except Exception:
                            if raw_idx not in (None, ""):
                                last_checkpoint = str(raw_idx)
                        timestamp_val = last_entry.get("timestamp")
                        if timestamp_val:
                            checkpoint_ts = str(timestamp_val)
                self._queue_progress_update(script_rel, idx, total_scripts, last_checkpoint, checkpoint_ts)
                if script_failed:
                    self._report_test_outcome(script_rel, False)
            except Exception as exc:
                logging.exception("Playback error for %s: %s", script_rel, exc)
                self._report_test_outcome(script_rel, False)
                self._queue_progress_update(script_rel, idx, total_scripts, None, None)
        self._player_running = False

    def _extract_procedure(self, script_rel: str) -> Optional[str]:
        try:
            parts = Path(script_rel).parts
            return parts[0] if parts else None
        except Exception:
            return None

    def _normalize_if_required(self, procedure: str, current_script: str) -> None:
        if not self.normalize_script:
            return
        norm = self.normalize_script
        if not norm or norm == current_script:
            return
        script_path = (self.paths.scripts_dir / f"{norm}.json").resolve()
        if not script_path.exists():
            _LOGGER.debug("Normalize script missing (%s); skipping.", script_path)
            return
        try:
            _LOGGER.info("Normalizing procedure %s using %s", procedure, norm)
            self._focus_target_app()
            self.player.play(norm)
        except Exception as exc:
            logging.exception("Normalization failed for %s (%s): %s", procedure, norm, exc)

    def _focus_target_app(self) -> None:
        regex = getattr(self, "target_app_regex", None)
        if not regex:
            return
        try:
            from pywinauto import Desktop as PwDesktop  # type: ignore
            desktop = PwDesktop(backend="uia")
            window = desktop.window(title_re=regex)
            try:
                window.set_focus()
            except Exception:
                try:
                    window.set_keyboard_focus()
                except Exception:
                    pass
        except Exception as exc:
            _LOGGER.debug("Unable to focus target app (%s): %s", regex, exc)

    def _queue_progress_update(
        self,
        script: str,
        index: int,
        total: int,
        checkpoint: Optional[str],
        checkpoint_ts: Optional[str],
    ) -> None:
        try:
            self.root.after(
                0,
                lambda s=script, i=index, t=total, c=checkpoint, ts=checkpoint_ts: self.results_panel.update_progress(
                    s, i, t, c, ts
                ),
            )
        except Exception:
            pass

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

    def _notify_semantic_warning(self, script_rel: str, note: str) -> None:
        message = f"{script_rel}\n{note}"

        def _show() -> None:
            try:
                ToastNotification(title="Semantic Warning", message=message, duration=6000, bootstyle="warning").show_toast()
            except Exception:
                messagebox.showwarning("Semantic Warning", message, parent=self.root)

        try:
            self.root.after(0, _show)
        except Exception:
            _show()

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
        previous: Optional[str] = None
        try:
            previous = self.root.clipboard_get()
        except Exception:
            previous = None
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(note.note_text)
            self.root.update()
            _LOGGER.info("Defect note copied to clipboard (restoring previous contents): %s", note.note_path)
        except Exception as exc:
            _LOGGER.warning("Failed to copy defect note to clipboard: %s", exc)
        finally:
            if previous is not None:
                try:
                    self.root.clipboard_clear()
                    self.root.clipboard_append(previous)
                    self.root.update()
                except Exception:
                    pass
            else:
                try:
                    self.root.clipboard_clear()
                except Exception:
                    pass

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
        try:
            os.startfile(str(target))  # type: ignore[attr-defined]
        except Exception:
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

    def _start_global_hotkeys(self) -> None:
        if pynput_keyboard is None:
            _LOGGER.debug("pynput not available; global F hotkey disabled.")
            return
        if self._hotkey_listener:
            return
        try:
            listener = pynput_keyboard.Listener(on_press=self._on_global_key_press)
            listener.daemon = True
            listener.start()
            self._hotkey_listener = listener
        except Exception as exc:
            _LOGGER.warning("Failed to start global hotkeys: %s", exc)
            self._hotkey_listener = None

    def _stop_global_hotkeys(self) -> None:
        listener = self._hotkey_listener
        if listener:
            try:
                listener.stop()
            except Exception:
                pass
        self._hotkey_listener = None

    def _bind_shortcuts(self) -> None:
        """Register accelerator keys advertised in tooltips."""
        bindings: Dict[str, Callable[[tk.Event], str]] = {
            "<Control-r>": self._shortcut_start_recording,
            "<Control-R>": self._shortcut_start_recording,
            "<Control-Return>": self._shortcut_run_selected,
            "<Control-KP_Enter>": self._shortcut_run_selected,
        }
        for sequence, handler in bindings.items():
            try:
                self.root.bind_all(sequence, handler, add=True)
            except Exception:
                _LOGGER.debug("Unable to bind shortcut %s", sequence)

    def _shortcut_start_recording(self, _event: tk.Event) -> str:
        if self.recorder and getattr(self.recorder, "running", False):
            return "break"
        self.start_recording()
        return "break"

    def _shortcut_run_selected(self, _event: tk.Event) -> str:
        self.run_selected()
        return "break"

    def _on_global_key_press(self, key) -> None:
        if pynput_keyboard is None:
            return
        try:
            if isinstance(key, pynput_keyboard.KeyCode) and key.char and key.char.lower() == 'f':
                self.root.after(0, self._global_escape)
        except Exception:
            pass

    def _on_window_close(self) -> None:
        try:
            state = self.root.state()
        except Exception:
            state = None
        if state == 'zoomed':
            self.settings.window_state = 'zoomed'
            self.settings.window_geometry = None
        else:
            self.settings.window_state = state or 'normal'
            try:
                self.settings.window_geometry = self.root.geometry()
            except Exception:
                self.settings.window_geometry = None
        self._save_settings()
        self._stop_global_hotkeys()
        try:
            self._background.stop()
        except Exception:
            pass
        try:
            self.root.destroy()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Test asset helpers
    # ------------------------------------------------------------------
    def open_logs(self) -> None:
        target = self._log_file if self._log_file.exists() else self.paths.results_dir
        try:
            open_path_in_explorer(target)
        except Exception:
            messagebox.showinfo("Open Logs", str(target), parent=self.root)

    def open_settings_dialog(self, _event: Optional[tk.Event] = None) -> None:
        dialog = SettingsDialog(
            self.root,
            theme_var=self.theme_var,
            theme_choices=self._theme_choices,
            default_delay_var=self.default_delay_var,
            tolerance_var=self.tolerance_var,
            use_default_delay_var=self.use_default_delay_var,
            use_automation_ids_var=self.use_automation_ids_var,
            use_screenshots_var=self.use_screenshots_var,
            prefer_semantic_var=self.prefer_semantic_var,
            use_ssim_var=self.use_ssim_var,
            ssim_threshold_var=self.ssim_threshold_var,
            backend_var=self.automation_backend_var,
            backend_choices=["uia", "appium"],
            theme_change_callback=self._on_theme_change,
        )
        self._popup_over_root(dialog)

    def semantic_upgrade_selected_scripts(self) -> None:
        scripts = self.tests_panel.selected_scripts()
        if not scripts:
            messagebox.showinfo("Semantic Helper", "Select at least one test in the Available Tests panel.", parent=self.root)
            return
        stats_updated: List[str] = []
        stats_skipped: List[str] = []
        total_asserts_added = 0
        for rel in scripts:
            base_path = self.paths.scripts_dir / f"{rel}.json"
            if not base_path.exists():
                continue
            try:
                actions = json.loads(base_path.read_text(encoding="utf-8"))
            except Exception as exc:
                _LOGGER.warning("Failed to load %s: %s", base_path, exc)
                continue
            upgrade = self._upgrade_script_actions(actions)
            if upgrade is None:
                stats_skipped.append(rel)
                continue
            semantic_actions, removed, inserted = upgrade
            semantic_path = base_path.with_suffix(".semantic.json")
            if not semantic_path.exists() or semantic_actions != actions or removed:
                semantic_path.write_text(json.dumps(semantic_actions, indent=2), encoding="utf-8")
                stats_updated.append(rel)
                total_asserts_added += inserted
        summary: List[str] = []
        if stats_updated:
            summary.append(f"Wrote semantic variants (*.semantic.json) for {len(stats_updated)} test(s).")
            summary.append("Use Settings -> Prefer semantic assertions to play them back.")
            summary.append(f"Inserted {total_asserts_added} semantic assertion(s).")
        if stats_skipped:
            summary.append(f"Skipped {len(stats_skipped)} script(s) without Automation IDs to upgrade.")
        if not summary:
            summary.append("Scripts already contain semantic checks.")
        messagebox.showinfo("Semantic Helper", "\n".join(summary), parent=self.root)

    def _upgrade_script_actions(self, actions: Any) -> Optional[tuple[List[Dict[str, Any]], bool, int]]:
        if not isinstance(actions, list):
            return None
        changed: List[Dict[str, Any]] = []
        removed_screenshots = False
        assertions_added = 0
        for idx, action in enumerate(actions):
            a_type = action.get("action_type")
            if a_type == "screenshot":
                removed_screenshots = True
                continue
            changed.append(action)
            if a_type == "click":
                auto_id = action.get("auto_id")
                if not auto_id:
                    continue
                auto_id_str = str(auto_id)
                if self._has_assert_following(actions, idx, auto_id_str):
                    continue
                expected = action.get("text") or action.get("value")
                if not expected:
                    lookup = getattr(self.player, "_automation_lookup", {}).get(auto_id_str)
                    if lookup:
                        expected = lookup[1]
                if not expected:
                    expected = auto_id_str
                changed.append(
                    {
                        "action_type": "assert.property",
                        "delay": 0.0,
                        "auto_id": auto_id_str,
                        "control_type": action.get("control_type"),
                        "property": "name",
                        "expected": expected,
                        "compare": "equals",
                    }
                )
                assertions_added += 1
        if assertions_added == 0:
            return None
        return changed, removed_screenshots, assertions_added

    def _has_assert_following(self, actions: List[Dict[str, Any]], start_index: int, auto_id: str) -> bool:
        for offset in (1, 2):
            idx = start_index + offset
            if idx >= len(actions):
                break
            nxt = actions[idx]
            if nxt.get("action_type") == "assert.property" and str(nxt.get("auto_id")) == auto_id:
                return True
            if nxt.get("action_type") not in {"screenshot", "mouse_move", "click"}:
                break
        return False

    def _load_automation_manifest(self) -> Dict[str, Dict[str, str]]:
        candidates = [
            self.paths.root / "automation_ids.json",
            self.paths.root / "automation" / "automation_ids.json",
            self.paths.root / "ui_testing" / "automation" / "manifest" / "automation_ids.json",
        ]
        for path in candidates:
            try:
                if path.exists():
                    raw = json.loads(path.read_text(encoding="utf-8"))
                    groups = raw.get("groups") if isinstance(raw, dict) else None
                    manifest_input = groups if isinstance(groups, dict) else raw
                    manifest: Dict[str, Dict[str, str]] = {}
                    if isinstance(manifest_input, dict):
                        for group, mapping in manifest_input.items():
                            if not isinstance(mapping, dict):
                                continue
                            target: Dict[str, str] = {}
                            for name, payload in mapping.items():
                                if isinstance(payload, dict):
                                    automation_id = payload.get("id") or payload.get("automation_id")
                                else:
                                    automation_id = str(payload)
                                if automation_id:
                                    target[str(name)] = str(automation_id)
                            if target:
                                manifest[str(group)] = target
                    if manifest:
                        return manifest
            except Exception:
                logging.warning("Failed to load automation manifest from %s", path)
        return {}

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
    def show_instructions(self, _event: Optional[tk.Event] = None) -> None:
        win = tk.Toplevel(self.root)
        win.title("Instructions")
        win.geometry("820x600")
        try:
            win.iconbitmap(resource_path("assets/ui_testing.ico"))
        except Exception:
            pass
        self._popup_over_root(win)

        notebook = ttk.Notebook(win, bootstyle="pills")
        notebook.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        sections = [
            (
                "Overview & Layout",
                "UI Testing Overview\n\n"
                "- The window is split into four panes: Available Tests (tree), Results (grid + summary banner), Preview (image diff), and Log (live journal).\n"
                "- Toolbar buttons control high-frequency actions: Record/Stop, Run Selected/Run All, Normalize helpers, Semantic Helper, Settings, open logs, and documentation.\n"
                "- Status indicators show the active script, remaining queue, and semantic/screenshot configuration so you always know which validation modes are enabled.\n"
                "- Every run writes to results_summary.xlsx and creates per-script folders under data/results for downstream analysis."
            ),
            (
                "Recording Sessions",
                "Recording a Test\n\n"
                "1) Click 'Record New'. Enter the procedure, section, and a descriptive test name (these drive folder structure and workbook sheets).\n"
                "2) During capture the recorder stores raw cursor coordinates, AutomationIds (when available), semantic metadata (group/name), and keystrokes. Press 'p' for a screenshot checkpoint; press 'F' (or the toolbar Stop button) to finish.\n"
                "3) The recorder automatically filters out generic AutomationIds ('Window', 'Pane', etc.) and falls back to coordinates when a control is not described by the manifest, ensuring the JSON reflects actionable selectors.\n"
                "4) Output lands in data/scripts/<proc>/<sec>/<test>.json with matching images under data/images/... Screenshot names use the 0_000O/0_000T convention for quick diffing."
            ),
            (
                "Playback & Validation",
                "Running Scripts\n\n"
                "- Select one or more tests in the tree (Ctrl/Shift click supported) and use 'Run Selected' or 'Run All'.\n"
                "- The player resolves clicks in this order: semantic session (manifest-backed AutomationId), UIA window search, then raw coordinates. Summary rows include semantic/UIA/coordinate counts so you can confirm how each run navigated the UI.\n"
                "- Toggle 'Prefer semantic assertions' to load *.semantic.json variants. Toggle 'Use Automation IDs' or 'Compare screenshots' to influence which validation channels are active.\n"
                "- A normalize script (optional) is invoked automatically whenever a new procedure starts; use the Normalize buttons to set, clear, or execute that helper."
            ),
            (
                "Semantic Automation",
                "Semantic Checks & Helper\n\n"
                "- The Semantic Helper upgrades legacy scripts by inserting assert.property steps based on the automation manifest. Upgrades create side-by-side *.semantic.json files so you can switch between image- and AutomationId-driven playback without losing history.\n"
                "- During recording, controls are cross-referenced against the manifest. If an AutomationId exists, the recorder captures group/name metadata so playback can target the same widget even if window chrome shifts.\n"
                "- During playback, failed semantic lookups automatically fall back to coordinates and log warnings. Use the log search box to filter for 'Playback(Semantic)' entries when auditing runs."
            ),
            (
                "Results & Reporting",
                "Output Artefacts\n\n"
                "- The Results panel lists each checkpoint with status, including semantic assertions, screenshot comparisons, and summary lines. Icons surface failures immediately; double-click to jump in the tree.\n"
                "- Failed runs trigger AI-assisted bug drafts under data/results/<script>/bugdraft_*.md with cropped evidence, heuristics, and recommendations. Diff/crop images are stored alongside the markdown.\n"
                "- results_summary.xlsx is pruned and rewritten per script to avoid duplicate history and is also attached to Allure (when enabled) for CI review. Flake statistics are recorded per assertion when the optional tracker is configured."
            ),
            (
                "Settings & Shortcuts",
                "Customization guide\n\n"
                "- Settings (gear) exposes theme selection, default delay, tolerance, automation toggles, semantic preference, screenshot handling, SSIM threshold, automation backend, and normalize script path.\n"
                "- Hotkeys: 'p' screenshot, 'F' stop recording/playback, 'Ctrl+L' open logs, 'Ctrl+R' start recording, 'Ctrl+Enter' run selected, 'Ctrl+Shift+S' toggle screenshots, 'Ctrl+Shift+A' toggle automation IDs.\n"
                "- Right-click a tree node to open the JSON, jump to the images, or delete artifacts. Logs are timestamped under data/logs/ui_testing.log for long-term auditing."
            ),
            (
                "Packaging & Maintenance",
                "Shipping the Toolkit\n\n"
                "- Run setup_and_deploy.ps1 whenever dependencies or scripts change. The build script recreates the virtual environment as needed, installs pinned wheels, runs compileall + pytest -m semantic, builds the PyInstaller bundle, and generates package/installer zips.\n"
                "- The generated README.txt in the Package folder explains offline deployment steps. Use Install_UI_Testing.bat on target machines for a zero-config install that drops a desktop shortcut.\n"
                "- Keep automation_ids.json in sync with upstream ENFIRE builds (see automation/export tooling). When manifest entries change, re-run the Semantic Helper to refresh recordings."
            ),
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
        try:
            self.root.mainloop()
        finally:
            self._stop_global_hotkeys()

    # ------------------------------------------------------------------
    # Settings helpers
    # ------------------------------------------------------------------
    def _popup_over_root(self, window: tk.Misc) -> None:
        try:
            self.root.update_idletasks()
            window.update_idletasks()
            root_x = self.root.winfo_rootx()
            root_y = self.root.winfo_rooty()
            root_w = self.root.winfo_width() or window.winfo_screenwidth()
            root_h = self.root.winfo_height() or window.winfo_screenheight()
            win_w = window.winfo_width() or window.winfo_reqwidth()
            win_h = window.winfo_height() or window.winfo_reqheight()
        except Exception:
            return
        target_x = root_x + (root_w - win_w) // 2
        target_y = root_y + (root_h - win_h) // 2
        if root_w > win_w:
            min_x = root_x
            max_x = root_x + root_w - win_w
            target_x = max(min_x, min(target_x, max_x))
        else:
            target_x = root_x
        if root_h > win_h:
            min_y = root_y
            max_y = root_y + root_h - win_h
            target_y = max(min_y, min(target_y, max_y))
        else:
            target_y = root_y
        try:
            window.geometry(f"+{int(target_x)}+{int(target_y)}")
        except Exception:
            pass

    def _apply_theme(self, name: str) -> None:
        try:
            self.root.style.theme_use(name)
        except Exception as exc:
            _LOGGER.warning("Theme switch failed: %s", exc)
        self.settings.theme = name
        self._save_settings()
        self._refresh_input_styles()
        for panel in (self.tests_panel, self.results_panel, self.preview_panel, self.log_panel):
            if callable(getattr(panel, "on_theme_changed", None)):
                try:
                    panel.on_theme_changed()
                except Exception:
                    pass

    def _apply_settings_to_variables(self) -> None:
        if self.settings.theme:
            self.theme_var.set(self.settings.theme)
        self.default_delay_var.set(float(self.settings.default_delay))
        self.tolerance_var.set(float(self.settings.tolerance))
        self.use_default_delay_var.set(bool(self.settings.ignore_recorded_delays))
        self.use_automation_ids_var.set(bool(getattr(self.settings, "use_automation_ids", True)))
        self.use_screenshots_var.set(bool(getattr(self.settings, "use_screenshots", True)))
        self.use_ssim_var.set(bool(getattr(self.settings, "use_ssim", False)))
        self.ssim_threshold_var.set(float(getattr(self.settings, "ssim_threshold", 0.99)))
        self.automation_backend_var.set(str(getattr(self.settings, "automation_backend", "uia")))
        self.prefer_semantic_var.set(bool(getattr(self.settings, "prefer_semantic_scripts", True)))
        self.normalize_script = self.settings.normalize_script
        self.target_app_regex = getattr(self.settings, "target_app_regex", getattr(self, "target_app_regex", None))
        self._update_normalize_label()

    def _bind_setting_traces(self) -> None:
        self.default_delay_var.trace_add("write", lambda *_: self._on_default_delay_changed())
        self.tolerance_var.trace_add("write", lambda *_: self._on_tolerance_changed())
        self.use_default_delay_var.trace_add("write", lambda *_: self._on_ignore_delays_changed())
        self.use_automation_ids_var.trace_add("write", lambda *_: self._on_use_automation_ids_changed())
        self.use_screenshots_var.trace_add("write", lambda *_: self._on_use_screenshots_changed())
        self.use_ssim_var.trace_add("write", lambda *_: self._on_use_ssim_changed())
        self.ssim_threshold_var.trace_add("write", lambda *_: self._on_ssim_threshold_changed())
        self.automation_backend_var.trace_add("write", lambda *_: self._on_backend_changed())
        self.prefer_semantic_var.trace_add("write", lambda *_: self._on_prefer_semantic_changed())

    def _on_use_automation_ids_changed(self) -> None:
        value = bool(self.use_automation_ids_var.get())
        self.settings.use_automation_ids = value
        self.player.config.use_automation_ids = value
        self._save_settings()

    def _on_use_screenshots_changed(self) -> None:
        value = bool(self.use_screenshots_var.get())
        self.settings.use_screenshots = value
        self.player.config.use_screenshots = value
        self._save_settings()

    def _on_prefer_semantic_changed(self) -> None:
        value = bool(self.prefer_semantic_var.get())
        self.settings.prefer_semantic_scripts = value
        self.player.config.prefer_semantic_scripts = value
        self._save_settings()

    def _on_use_ssim_changed(self) -> None:
        value = bool(self.use_ssim_var.get())
        self.settings.use_ssim = value
        self.player.config.use_ssim = value
        self._save_settings()

    def _on_ssim_threshold_changed(self) -> None:
        try:
            threshold = float(self.ssim_threshold_var.get())
        except tk.TclError:
            return
        self.settings.ssim_threshold = threshold
        self.player.config.ssim_threshold = threshold
        self._save_settings()

    def _on_backend_changed(self) -> None:
        backend = str(self.automation_backend_var.get()).lower()
        self.settings.automation_backend = backend
        self.player.config.automation_backend = backend
        reset_semantic_context()
        self.player._semantic_context = None
        self.player._semantic_disabled = False
        self.player._semantic_registry_cache = None
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

    def _restore_window_state(self) -> None:
        state = getattr(self.settings, 'window_state', None)
        geom = getattr(self.settings, 'window_geometry', None)
        try:
            if state == 'zoomed':
                try:
                    self.root.state('zoomed')
                    return
                except Exception:
                    pass
            if geom:
                try:
                    self.root.geometry(geom)
                except Exception:
                    pass
            if state and state not in (None, 'normal', 'zoomed'):
                try:
                    self.root.state(state)
                except Exception:
                    pass
            elif not geom and state != 'zoomed':
                try:
                    self.root.state('zoomed')
                except Exception:
                    self.root.geometry(self._default_geometry)
        except Exception:
            if geom:
                try:
                    self.root.geometry(geom)
                except Exception:
                    pass

    def _set_initial_sash_positions(self) -> None:
        if getattr(self.settings, 'window_geometry', None):
            return
        try:
            self.root.update_idletasks()
            if self._body_paned is not None:
                total_w = self._body_paned.winfo_width() or 1200
                target = max(200, int(total_w * 0.18))
                self._body_paned.sashpos(0, target)
            if self._left_panes is not None:
                total_h = self._left_panes.winfo_height() or 600
                target_h = int(total_h * 0.65)
                self._left_panes.sashpos(0, target_h)
        except Exception:
            pass

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
        self.settings.use_screenshots = bool(self.use_screenshots_var.get())
        self.settings.use_ssim = bool(self.use_ssim_var.get())
        try:
            self.settings.ssim_threshold = float(self.ssim_threshold_var.get())
        except tk.TclError:
            pass
        self.settings.automation_backend = str(self.automation_backend_var.get()).lower()
        self.settings.prefer_semantic_scripts = bool(self.prefer_semantic_var.get())
        self.settings.normalize_script = self.normalize_script
        try:
            current_regex = self.target_app_regex
        except AttributeError:
            current_regex = getattr(self.settings, "target_app_regex", None)
        self.settings.target_app_regex = current_regex
        self.settings.save(self.settings_path)

    def _refresh_input_styles(self) -> None:
        try:
            style = self.root.style
        except Exception:
            return
        def _get_color(style_name: str, option: str, default: str) -> str:
            try:
                value = style.lookup(style_name, option)
            except Exception:
                value = ""
            return value or default
        label_fg = _get_color("TLabel", "foreground", "#f0f0f0")
        entry_bg = _get_color("TEntry", "fieldbackground", "#202020")
        for style_name in ("TEntry", "TCombobox", "TSpinbox"):
            try:
                style.configure(style_name, foreground=label_fg, fieldbackground=entry_bg, insertcolor=label_fg)
            except Exception:
                try:
                    style.configure(style_name, foreground=label_fg, insertcolor=label_fg)
                except Exception:
                    continue
            try:
                style.map(style_name, foreground=[("readonly", label_fg), ("disabled", _get_color(style_name, "foreground", label_fg))])
            except Exception:
                pass


def run_app() -> None:
    app = TestRunnerApp()
    app.run()



