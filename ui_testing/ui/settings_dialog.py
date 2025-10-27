# ui_testing/ui/settings_dialog.py
from __future__ import annotations

import tkinter as tk
import ttkbootstrap as ttk


class SettingsDialog(ttk.Toplevel):
    def __init__(
        self,
        master: tk.Misc,
        *,
        theme_var: tk.StringVar,
        theme_choices: list[str],
        default_delay_var: tk.DoubleVar,
        tolerance_var: tk.DoubleVar,
        use_default_delay_var: tk.BooleanVar,
        use_automation_ids_var: tk.BooleanVar,
        use_screenshots_var: tk.BooleanVar,
        prefer_semantic_var: tk.BooleanVar,
        use_ssim_var: tk.BooleanVar,
        ssim_threshold_var: tk.DoubleVar,
        ssim_available: bool = True,
        backend_var: tk.StringVar,
        backend_choices: list[str],
        theme_change_callback,
        app_regex_var: tk.StringVar,
    ) -> None:
        super().__init__(master=master)
        self.title("Settings")
        self.transient(master)
        self.grab_set()
        self.resizable(False, False)
        self.configure(padx=4, pady=4)

        self._theme_var = theme_var
        self._default_delay_var = default_delay_var
        self._tolerance_var = tolerance_var
        self._use_default_delay_var = use_default_delay_var
        self._use_automation_ids_var = use_automation_ids_var
        self._use_screenshots_var = use_screenshots_var
        self._use_ssim_var = use_ssim_var
        self._ssim_threshold_var = ssim_threshold_var
        self._ssim_available = bool(ssim_available)
        self._backend_var = backend_var
        self._backend_choices = backend_choices
        self._prefer_semantic_var = prefer_semantic_var
        self._theme_change_callback = theme_change_callback
        self._app_regex_var = app_regex_var

        body = ttk.Frame(self, padding=16)
        body.pack(fill=tk.BOTH, expand=True)

        # Theme selection
        theme_frame = ttk.Labelframe(body, text="Theme", padding=12)
        theme_frame.pack(fill=tk.X, expand=False)
        self._theme_combo = ttk.Combobox(
            theme_frame,
            state="readonly",
            values=theme_choices,
            textvariable=self._theme_var,
            width=18,
        )
        self._theme_combo.pack(fill=tk.X)
        self._theme_combo.bind("<<ComboboxSelected>>", self._on_theme_selected, add=True)

        # Timing
        timing_frame = ttk.Labelframe(body, text="Timing", padding=12)
        timing_frame.pack(fill=tk.X, expand=False, pady=(12, 0))
        ttk.Label(timing_frame, text="Default delay (s)").grid(row=0, column=0, sticky="w")
        ttk.Spinbox(
            timing_frame,
            from_=0.0,
            to=5.0,
            increment=0.1,
            textvariable=self._default_delay_var,
            width=8,
        ).grid(row=0, column=1, sticky="w", padx=(12, 0))

        ttk.Label(timing_frame, text="Tolerance (% max diff)").grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Spinbox(
            timing_frame,
            from_=0.0,
            to=1.0,
            increment=0.01,
            textvariable=self._tolerance_var,
            width=8,
        ).grid(row=1, column=1, sticky="w", padx=(12, 0), pady=(8, 0))

        # Toggles
        toggle_frame = ttk.Labelframe(body, text="Playback Options", padding=12)
        toggle_frame.pack(fill=tk.X, expand=False, pady=(12, 0))
        ttk.Checkbutton(
            toggle_frame,
            text="Ignore recorded delays",
            variable=self._use_default_delay_var,
            bootstyle="round-toggle",
        ).pack(anchor="w", pady=4)
        ttk.Checkbutton(
            toggle_frame,
            text="Use Automation IDs",
            variable=self._use_automation_ids_var,
            bootstyle="round-toggle",
        ).pack(anchor="w", pady=4)
        ttk.Checkbutton(
            toggle_frame,
            text="Prefer semantic assertions",
            variable=self._prefer_semantic_var,
            bootstyle="round-toggle",
        ).pack(anchor="w", pady=4)
        ttk.Checkbutton(
            toggle_frame,
            text="Compare screenshots",
            variable=self._use_screenshots_var,
            bootstyle="round-toggle",
        ).pack(anchor="w", pady=4)
        ssim_label = "Use SSIM image compare"
        if not self._ssim_available:
            ssim_label += " (requires scikit-image)"
        self._ssim_check = ttk.Checkbutton(
            toggle_frame,
            text=ssim_label,
            variable=self._use_ssim_var,
            bootstyle="round-toggle",
        )
        if not self._ssim_available:
            self._ssim_check.configure(state="disabled")
        self._ssim_check.pack(anchor="w", pady=4)
        ssim_frame = ttk.Frame(toggle_frame)
        ssim_frame.pack(fill=tk.X, expand=False, pady=(0, 4))
        ttk.Label(ssim_frame, text="SSIM threshold").pack(side=tk.LEFT)
        self._ssim_spin = ttk.Spinbox(
            ssim_frame,
            from_=0.90,
            to=1.0,
            increment=0.01,
            textvariable=self._ssim_threshold_var,
            width=6,
        )
        self._ssim_spin.pack(side=tk.LEFT, padx=(12, 0))
        self._use_ssim_var.trace_add("write", lambda *_: self._update_ssim_state())
        self._update_ssim_state()

        backend_frame = ttk.Labelframe(body, text="Automation Backend", padding=12)
        backend_frame.pack(fill=tk.X, expand=False, pady=(12, 0))
        self._backend_combo = ttk.Combobox(
            backend_frame,
            state="readonly",
            values=self._backend_choices,
            textvariable=self._backend_var,
            width=18,
        )
        self._backend_combo.pack(fill=tk.X)

        target_frame = ttk.Labelframe(body, text="Target Application", padding=12)
        target_frame.pack(fill=tk.X, expand=False, pady=(12, 0))
        ttk.Label(target_frame, text="Title regex (UIA scope)").pack(anchor="w")
        ttk.Entry(target_frame, textvariable=self._app_regex_var, width=36).pack(fill=tk.X, expand=True, pady=(4, 0))
        ttk.Label(
            target_frame,
            text="Example: .*ENFIRE.*  (must match the ENFIRE window title when playback runs)",
            bootstyle="secondary",
        ).pack(anchor="w", pady=(4, 0))

        button_row = ttk.Frame(body)
        button_row.pack(fill=tk.X, expand=False, pady=(16, 0))
        ttk.Button(button_row, text="Close", command=self._on_close, bootstyle="primary").pack(side=tk.RIGHT)

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._theme_combo.focus_set()

    def _update_ssim_state(self) -> None:
        if not self._ssim_available:
            state = "disabled"
        else:
            state = "normal" if bool(self._use_ssim_var.get()) else "disabled"
        try:
            self._ssim_spin.configure(state=state)
        except Exception:
            pass

    def _on_theme_selected(self, _event: tk.Event) -> None:
        if callable(self._theme_change_callback):
            self._theme_change_callback(self._theme_var.get())

    def _on_close(self) -> None:
        if callable(self._theme_change_callback):
            self._theme_change_callback(self._theme_var.get())
        self.grab_release()
        self.destroy()
