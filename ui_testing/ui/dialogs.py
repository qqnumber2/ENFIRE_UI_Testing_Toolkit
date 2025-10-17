# ui_testing/ui/dialogs.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

import ttkbootstrap as ttk
import tkinter as tk
from tkinter import messagebox, simpledialog


@dataclass
class RecordingRequest:
    procedure: str
    section: str
    test_name: str

    @property
    def qualified_name(self) -> str:
        return f"{self.procedure}/{self.section}/{self.test_name}"


class NewRecordingDialog(simpledialog.Dialog):
    """Prompt the operator for procedure/section/test metadata."""

    def body(self, master: tk.Misc) -> None:  # type: ignore[override]
        ttk.Label(master, text="Procedure (e.g. 1_EBS)").grid(row=0, column=0, sticky="w", padx=4, pady=4)
        ttk.Label(master, text="Section (e.g. 6)").grid(row=1, column=0, sticky="w", padx=4, pady=4)
        ttk.Label(master, text="Test name (e.g. 1.1.1_ATTACHMENTS TAB)").grid(row=2, column=0, sticky="w", padx=4, pady=4)

        self.proc_var = tk.StringVar(master=master)
        self.sec_var = tk.StringVar(master=master)
        self.test_var = tk.StringVar(master=master)

        ttk.Entry(master, textvariable=self.proc_var, width=40).grid(row=0, column=1, sticky="ew", padx=4, pady=4)
        ttk.Entry(master, textvariable=self.sec_var, width=40).grid(row=1, column=1, sticky="ew", padx=4, pady=4)
        ttk.Entry(master, textvariable=self.test_var, width=40).grid(row=2, column=1, sticky="ew", padx=4, pady=4)
        master.grid_columnconfigure(1, weight=1)

    def validate(self) -> bool:  # type: ignore[override]
        for label, var in (
            ("Procedure", self.proc_var),
            ("Section", self.sec_var),
            ("Test name", self.test_var),
        ):
            if not var.get().strip():
                messagebox.showerror("Missing", f"{label} is required.", parent=self)
                return False
        return True

    def apply(self) -> None:  # type: ignore[override]
        self.result = RecordingRequest(
            procedure=self.proc_var.get().strip(),
            section=self.sec_var.get().strip(),
            test_name=self.test_var.get().strip(),
        )
