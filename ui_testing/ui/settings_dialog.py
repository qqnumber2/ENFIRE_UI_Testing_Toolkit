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
        theme_change_callback,
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
        self._prefer_semantic_var = prefer_semantic_var
        self._theme_change_callback = theme_change_callback

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

        button_row = ttk.Frame(body)
        button_row.pack(fill=tk.X, expand=False, pady=(16, 0))
        ttk.Button(button_row, text="Close", command=self._on_close, bootstyle="primary").pack(side=tk.RIGHT)

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._theme_combo.focus_set()

    def _on_theme_selected(self, _event: tk.Event) -> None:
        if callable(self._theme_change_callback):
            self._theme_change_callback(self._theme_var.get())

    def _on_close(self) -> None:
        if callable(self._theme_change_callback):
            self._theme_change_callback(self._theme_var.get())
        self.grab_release()
        self.destroy()
