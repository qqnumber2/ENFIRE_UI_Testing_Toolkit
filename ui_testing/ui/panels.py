# ui_testing/ui/panels.py
from __future__ import annotations

import logging
import os
import subprocess
from collections import OrderedDict
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence

import tkinter as tk
from tkinter import scrolledtext

import ttkbootstrap as ttk
from ttkbootstrap.constants import *
from PIL import Image, ImageTk

from ui_testing.ui.notes import NoteEntry



def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    if len(value) == 3:
        value = "".join(ch * 2 for ch in value)
    if len(value) != 6:
        raise ValueError(f"Invalid hex color: {value}")
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


def _rgb_to_hex(rgb: tuple[int, int, int]) -> str:
    return "#{:02x}{:02x}{:02x}".format(*(max(0, min(255, c)) for c in rgb))


def _blend_colors(base: str, target: str, amount: float) -> str:
    br, bg, bb = _hex_to_rgb(base)
    tr, tg, tb = _hex_to_rgb(target)
    mixed = (
        int(round(br + (tr - br) * amount)),
        int(round(bg + (tg - bg) * amount)),
        int(round(bb + (tb - bb) * amount)),
    )
    return _rgb_to_hex(mixed)


def _color_to_hex(widget: tk.Misc, color: Optional[str], fallback: str) -> str:
    candidate = color or fallback
    try:
        r, g, b = widget.winfo_rgb(candidate)
    except tk.TclError:
        r, g, b = widget.winfo_rgb(fallback)
    return "#{:02x}{:02x}{:02x}".format(r // 256, g // 256, b // 256)


def _relative_luminance(hex_color: str) -> float:
    r, g, b = _hex_to_rgb(hex_color)

    def channel(value: int) -> float:
        c = value / 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def _is_dark_color(hex_color: str) -> bool:
    return _relative_luminance(hex_color) < 0.5


_LOGGER = logging.getLogger(__name__)
class ActionsPanel(ttk.Frame):
    """Top toolbar with record/playback controls and global options."""

    def __init__(
        self,
        master: tk.Misc,
        *,
        theme_var: tk.StringVar,
        default_delay_var: tk.DoubleVar,
        tolerance_var: tk.DoubleVar,
        use_default_delay_var: tk.BooleanVar,
        use_automation_ids_var: tk.BooleanVar,
        normalize_label_var: tk.StringVar,
        record_callback: Callable[[], None],
        stop_record_callback: Callable[[], None],
        run_selected_callback: Callable[[], None],
        run_all_callback: Callable[[], None],
        normalize_callback: Callable[[], None],
        choose_normalize_callback: Callable[[], None],
        open_logs_callback: Callable[[], None],
        instructions_callback: Callable[[], None],
        theme_change_callback: Callable[[str], None],
    ) -> None:
        super().__init__(master)
        self.theme_var = theme_var

        toolbar = ttk.Frame(self, padding=(12, 10))
        toolbar.pack(fill=tk.X)
        toolbar.grid_columnconfigure(0, weight=1)
        toolbar.grid_columnconfigure(1, weight=0)

        button_group = ttk.Frame(toolbar)
        button_group.grid(row=0, column=0, sticky="w")

        primary_buttons = [
            ("Record New", record_callback, "primary"),
            ("Stop Recording", stop_record_callback, "warning"),
            ("Run Selected", run_selected_callback, "success"),
            ("Run All", run_all_callback, "success-outline"),
            ("Instructions", instructions_callback, "info-outline"),
            ("Open Logs", open_logs_callback, "secondary-outline"),
        ]
        for idx, (label, command, style) in enumerate(primary_buttons):
            ttk.Button(
                button_group,
                text=label,
                command=command,
                bootstyle=style,
            ).pack(side=tk.LEFT, padx=(0 if idx == 0 else 6), pady=2)

        ttk.Button(
            button_group,
            text="Normalize ENFIRE",
            command=normalize_callback,
            bootstyle="secondary",
        ).pack(side=tk.LEFT, padx=6, pady=2)
        ttk.Button(
            button_group,
            text="Set",
            command=choose_normalize_callback,
            bootstyle="secondary-link",
        ).pack(side=tk.LEFT, padx=(0, 6), pady=2)
        ttk.Label(button_group, textvariable=normalize_label_var, bootstyle="secondary").pack(
            side=tk.LEFT, padx=(0, 6), pady=2
        )

        options_group = ttk.Frame(toolbar)
        options_group.grid(row=0, column=1, sticky="e")

        theme_frame = ttk.Frame(options_group)
        theme_frame.pack(side=tk.LEFT, padx=(0, 12))
        ttk.Label(theme_frame, text="Theme").pack(side=tk.LEFT, padx=(0, 6))
        theme_combo = ttk.Combobox(
            theme_frame,
            state="readonly",
            width=12,
            values=[
                "cosmo",
                "flatly",
                "minty",
                "litera",
                "sandstone",
                "pulse",
                "darkly",
                "cyborg",
                "superhero",
            ],
        )
        theme_combo.set(theme_var.get())
        theme_combo.pack(side=tk.LEFT)
        theme_combo.bind("<<ComboboxSelected>>", lambda _evt: theme_change_callback(theme_combo.get()))

        delay_frame = ttk.Frame(options_group)
        delay_frame.pack(side=tk.LEFT, padx=(0, 12))
        ttk.Label(delay_frame, text="Default Delay (s)").pack(side=tk.LEFT, padx=(0, 6))
        ttk.Spinbox(
            delay_frame,
            from_=0.0,
            to=5.0,
            increment=0.1,
            textvariable=default_delay_var,
            width=6,
        ).pack(side=tk.LEFT)

        tol_frame = ttk.Frame(options_group)
        tol_frame.pack(side=tk.LEFT, padx=(0, 12))
        ttk.Label(tol_frame, text="Tolerance (% max diff)").pack(side=tk.LEFT, padx=(0, 6))
        ttk.Spinbox(
            tol_frame,
            from_=0.0,
            to=1.0,
            increment=0.01,
            textvariable=tolerance_var,
            width=6,
        ).pack(side=tk.LEFT)

        ttk.Checkbutton(
            options_group,
            text="Ignore recorded delays",
            variable=use_default_delay_var,
            bootstyle="round-toggle",
        ).pack(side=tk.LEFT, padx=(0, 12))
        ttk.Checkbutton(
            options_group,
            text="Use Automation IDs",
            variable=use_automation_ids_var,
            bootstyle="round-toggle",
        ).pack(side=tk.LEFT)


class TestsPanel(ttk.Frame):
    """Procedure/section/test tree with toggle selection support."""

    _styles_initialized = False

    def __init__(
        self,
        master: tk.Misc,
        *,
        on_selection_change: Callable[[], None],
        on_open_json: Callable[[str], None],
        on_delete_test: Callable[[str], None],
    ) -> None:
        super().__init__(master)
        self._selection_change = on_selection_change
        self._open_json_cb = on_open_json
        self._delete_test_cb = on_delete_test

        self._trees: Dict[str, ttk.Treeview] = {}
        self._test_map: Dict[tuple[ttk.Treeview, str], str] = {}
        self._script_to_item: Dict[str, tuple[ttk.Treeview, str]] = {}
        self._display_map: Dict[str, str] = {}
        self._selected_scripts: OrderedDict[str, None] = OrderedDict()
        self._context_leaf: Optional[str] = None
        self._updating_selection = False
        self._press_info: Optional[tuple[ttk.Treeview, str, str, bool]] = None

        self.card = ttk.Labelframe(self, text="Available Tests", padding=8, bootstyle="info")
        self.card.pack(fill=tk.BOTH, expand=True)

        self.nb = ttk.Notebook(self.card, bootstyle="pills")
        self.nb.pack(fill=tk.BOTH, expand=True)

        self._info_row = ttk.Frame(self.card)
        self._info_row.pack(fill=tk.X, pady=(10, 0), padx=12)
        self._count_var = tk.StringVar(value="0")
        self.selected_tests_var = tk.StringVar(value="No tests selected")
        self._count_badge = ttk.Label(
            self._info_row,
            textvariable=self._count_var,
            width=3,
            anchor="center",
            padding=(8, 2),
            bootstyle="secondary-inverse",
        )
        self._count_badge.pack(side=tk.LEFT)
        self._summary_label = ttk.Label(self._info_row, textvariable=self.selected_tests_var)
        self._summary_label.pack(side=tk.LEFT, padx=(10, 0))
        ttk.Button(
            self._info_row,
            text="Deselect All",
            command=self.clear_selection,
            bootstyle="secondary-outline",
        ).pack(side=tk.RIGHT)

        self._menu = tk.Menu(self, tearoff=False)
        self._menu.add_command(label="Open JSON", command=self._open_selected_json)
        self._menu.add_command(label="Delete Test", command=self._delete_selected_test)

        self._ensure_tree_styles()
        self._apply_info_styles()

    def populate(self, grouped_tests: Dict[str, Sequence[object]]) -> None:
        previous_selection = list(self._selected_scripts.keys())
        self._test_map.clear()
        self._script_to_item.clear()
        self._display_map.clear()
        self._context_leaf = None
        self._updating_selection = False
        self._press_info = None

        for tab in self.nb.tabs():
            self.nb.forget(tab)
        self._trees.clear()

        for proc in sorted(grouped_tests.keys(), key=str):
            frame = ttk.Frame(self.nb, padding=(6, 6))
            self.nb.add(frame, text=str(proc))
            tree = ttk.Treeview(
                frame,
                show="tree",
                height=18,
                bootstyle="info",
                selectmode="extended",
                style="TestsPanel.Treeview",
            )
            tree.pack(fill=tk.BOTH, expand=True)
            tree.bind("<ButtonPress-1>", lambda evt, t=tree: self._on_tree_press(evt, t), add=True)
            tree.bind("<ButtonRelease-1>", lambda evt, t=tree: self._on_tree_release(evt, t), add=True)
            tree.bind("<<TreeviewSelect>>", lambda _evt: self._on_tree_select(), add=True)
            tree.bind("<Button-3>", self._show_context_menu, add=True)
            self._trees[str(proc)] = tree
            self._populate_tree(tree, grouped_tests[proc])

        self._selected_scripts = OrderedDict(
            (script, None)
            for script in previous_selection
            if script in self._script_to_item
        )
        self._apply_selection()
        self._update_selected_label()
        self._apply_info_styles()

    def _populate_tree(self, tree: ttk.Treeview, script_list: Sequence[object]) -> None:
        nodes: Dict[tuple[str, ...], str] = {}
        for entry in sorted(script_list, key=lambda value: str(value)):
            rel_path = entry if isinstance(entry, Path) else Path(str(entry))
            parts = rel_path.parts
            rel_str = rel_path.as_posix()
            path_tuple: tuple[str, ...] = tuple()
            for i, part in enumerate(parts):
                path_tuple = (*path_tuple, part)
                if path_tuple not in nodes:
                    parent = nodes[path_tuple[:-1]] if path_tuple[:-1] in nodes else ""
                    node = tree.insert(parent, tk.END, text=part, open=(i < len(parts) - 1))
                    nodes[path_tuple] = node
                if i == len(parts) - 1:
                    item_id = nodes[path_tuple]
                    self._test_map[(tree, item_id)] = rel_str
                    self._script_to_item[rel_str] = (tree, item_id)
                    self._display_map[rel_str] = self._format_script_label(rel_str)

    def selected_scripts(self) -> List[str]:
        return list(self._selected_scripts.keys())

    def refresh_selection(self) -> None:
        self._apply_selection()
        self._update_selected_label()

    def clear_selection(self) -> None:
        self._selected_scripts.clear()
        self._press_info = None
        self._apply_selection()
        self._update_selected_label()

    def _apply_info_styles(self) -> None:
        style = ttk.Style()
        candidates = [
            style.lookup("TLabelframe", "background"),
            style.lookup("TFrame", "background"),
            style.lookup("", "background"),
        ]
        base_bg = next((value for value in candidates if value), "#f2f2f2")
        base_hex = _color_to_hex(self, base_bg, "#f2f2f2")
        if _is_dark_color(base_hex):
            frame_bg = _blend_colors(base_hex, "#ffffff", 0.12)
            badge_bg = _blend_colors(base_hex, "#ffffff", 0.28)
            badge_fg = "#10131a"
            summary_fg = _blend_colors(frame_bg, "#ffffff", 0.65)
        else:
            frame_bg = _blend_colors(base_hex, "#000000", 0.05)
            badge_bg = _blend_colors(base_bg, "#000000", 0.18)
            badge_fg = "#ffffff"
            summary_fg = _blend_colors(frame_bg, "#000000", 0.65)
        info_style = "TestsPanel.Info.TFrame"
        badge_style = "TestsPanel.Badge.TLabel"
        summary_style = "TestsPanel.Summary.TLabel"
        style.configure(info_style, background=frame_bg)
        style.configure(badge_style, background=badge_bg, foreground=badge_fg, font=("", 10, "bold"))
        style.configure(summary_style, background=frame_bg, foreground=summary_fg, font=("", 10))
        self._info_row.configure(style=info_style)
        self._count_badge.configure(style=badge_style)
        self._summary_label.configure(style=summary_style)

    def _on_tree_press(self, event: tk.Event, tree: ttk.Treeview):
        if event.state & (0x0001 | 0x0004 | 0x0008):
            self._press_info = None
            return None
        item = tree.identify_row(event.y)
        if not item:
            self._press_info = None
            return None
        script = self._test_map.get((tree, item))
        if not script:
            self._press_info = None
            return None
        self._press_info = (tree, item, script, script in self._selected_scripts)
        return None

    def _on_tree_release(self, event: tk.Event, tree: ttk.Treeview):
        if event.state & (0x0001 | 0x0004 | 0x0008):
            self._press_info = None
            return None
        info = self._press_info
        self._press_info = None
        if not info or info[0] is not tree:
            return None
        _, item, script, was_selected = info
        release_item = tree.identify_row(event.y)
        if release_item != item:
            return None
        if was_selected:
            self._selected_scripts.pop(script, None)
            tree.focus("")
        else:
            self._selected_scripts[script] = None
            tree.focus(item)
        self._apply_selection()
        self._update_selected_label()
        return "break"

    def _apply_selection(self) -> None:
        self._updating_selection = True
        try:
            for tree in self._trees.values():
                current = tree.selection()
                if current:
                    tree.selection_remove(current)
            last_focus: Optional[tuple[ttk.Treeview, str]] = None
            for script in self._selected_scripts.keys():
                mapping = self._script_to_item.get(script)
                if not mapping:
                    continue
                tree, item_id = mapping
                tree.selection_add(item_id)
                last_focus = (tree, item_id)
            if last_focus:
                tree, item_id = last_focus
                tree.focus(item_id)
                tree.see(item_id)
        finally:
            self._updating_selection = False

    def _update_selected_label(self) -> None:
        scripts = list(self._selected_scripts.keys())
        count = len(scripts)
        self._count_var.set(str(count))
        if count == 0:
            summary = "No tests selected"
        else:
            display = [self._display_map.get(script, script) for script in scripts]
            summary = ", ".join(display[:3])
            if count > 3:
                summary += f"  (+{count - 3} more)"
        self.selected_tests_var.set(summary)
        self._selection_change()

    def _on_tree_select(self) -> None:
        if self._updating_selection:
            return
        scripts: List[str] = []
        for tree in self._trees.values():
            for item in tree.selection():
                script = self._test_map.get((tree, item))
                if script:
                    scripts.append(script)
        unique_scripts: List[str] = []
        seen: set[str] = set()
        for script in scripts:
            if script not in seen:
                unique_scripts.append(script)
                seen.add(script)
        self._selected_scripts = OrderedDict((script, None) for script in unique_scripts)
        self._update_selected_label()

    def _show_context_menu(self, event: tk.Event) -> None:
        widget: ttk.Treeview = event.widget  # type: ignore[assignment]
        item = widget.identify_row(event.y)
        script = self._test_map.get((widget, item)) if item else None
        if script:
            widget.selection_set(item)
            widget.focus(item)
            self._context_leaf = script
            self._on_tree_select()
        else:
            self._context_leaf = None
        self._menu.tk_popup(event.x_root, event.y_root)

    def _format_script_label(self, script: str) -> str:
        parts = [part.strip() for part in Path(script).parts if part.strip()]
        return "/".join(parts)

    def _open_selected_json(self) -> None:
        scripts = self.selected_scripts()
        target = scripts[0] if scripts else self._context_leaf
        if target:
            self._open_json_cb(target)
        self._context_leaf = None

    def _delete_selected_test(self) -> None:
        scripts = self.selected_scripts()
        target = scripts[0] if scripts else self._context_leaf
        if target:
            self._delete_test_cb(target)
        self._context_leaf = None



    def on_theme_changed(self) -> None:
        self._apply_info_styles()
        self._apply_selection()


    @classmethod
    def _ensure_tree_styles(cls) -> None:
        if cls._styles_initialized:
            return
        style = ttk.Style()
        base_row = style.lookup("Treeview", "rowheight")
        try:
            row_height = int(base_row) if base_row else 26
        except ValueError:
            row_height = 26
        style.configure("TestsPanel.Treeview", rowheight=row_height, font=("", 10))
        cls._styles_initialized = True


class ResultsPanel(ttk.Frame):
    """Container for results tree and AI notes view."""

    def __init__(
        self,
        master: tk.Misc,
        *,
        on_result_select: Callable[[Dict[str, str]], None],
        on_note_open: Callable[[Path], None],
    ) -> None:
        super().__init__(master)
        self._on_result_select = on_result_select
        self._on_note_open = on_note_open

        card = ttk.Labelframe(self, text="Test Results", padding=8)
        card.pack(fill=tk.BOTH, expand=True)

        notebook = ttk.Notebook(card, bootstyle="pills")
        notebook.pack(fill=tk.BOTH, expand=True)

        # Results tree
        results_frame = ttk.Frame(notebook, padding=4)
        notebook.add(results_frame, text="Results")

        cols = ("script", "index", "original", "test", "diff", "status")
        self.result_tree = ttk.Treeview(results_frame, columns=cols, show="headings", height=12, bootstyle="info")
        headings = {
            "script": "Script",
            "index": "Idx",
            "original": "Original",
            "test": "Test",
            "diff": "Diff (%)",
            "status": "Status",
        }
        for cid, width, anchor in (
            ("script", 280, "w"),
            ("index", 60, "center"),
            ("original", 220, "w"),
            ("test", 220, "w"),
            ("diff", 90, "e"),
            ("status", 120, "center"),
        ):
            self.result_tree.heading(cid, text=headings[cid])
            self.result_tree.column(cid, width=width, anchor=anchor)
        self.result_tree.pack(fill=tk.BOTH, expand=True)
        self.result_tree.tag_configure("pass", foreground="#0b6e2e", font="-weight bold")
        self.result_tree.tag_configure("fail", foreground="#b00020", font="-weight bold")
        self.result_tree.bind("<<TreeviewSelect>>", self._on_result_change)

        # AI notes
        notes_frame = ttk.Frame(notebook, padding=4)
        notebook.add(notes_frame, text="AI Notes")

        note_cols = ("script", "summary", "file", "timestamp")
        self.notes_tree = ttk.Treeview(notes_frame, columns=note_cols, show="headings", height=8, bootstyle="info")
        headings_notes = {
            "script": "Script",
            "summary": "Summary",
            "file": "File",
            "timestamp": "Created",
        }
        for cid, width, anchor in (
            ("script", 260, "w"),
            ("summary", 320, "w"),
            ("file", 160, "w"),
            ("timestamp", 160, "center"),
        ):
            self.notes_tree.heading(cid, text=headings_notes[cid])
            self.notes_tree.column(cid, width=width, anchor=anchor)
        self.notes_tree.pack(fill=tk.BOTH, expand=True)
        self.notes_tree.bind("<Double-Button-1>", self._open_selected_note)

        self._notes: List[NoteEntry] = []

    def clear(self) -> None:
        for tree in (self.result_tree, self.notes_tree):
            for item in tree.get_children(""):
                tree.delete(item)
        self._notes.clear()

    def append_results(self, script_name: str, results: Sequence[Dict[str, str]]) -> None:
        any_fail = False
        for r in results:
            idx = r.get("index", 0)
            orig = r.get("original", "")
            test = r.get("test", "")
            diffp = r.get("diff_percent", "")
            status = r.get("status", "fail")
            tag = "pass" if status == "pass" else "fail"
            if tag == "fail":
                any_fail = True
            diff_str = f"{float(diffp):.3f}" if diffp not in (None, "") else ""
            self.result_tree.insert(
                "",
                tk.END,
                values=(
                    script_name,
                    idx,
                    orig,
                    test,
                    diff_str,
                    "? PASS" if tag == "pass" else "? FAIL",
                ),
                tags=(tag,),
            )
        self.result_tree.insert(
            "",
            tk.END,
            values=(
                script_name,
                "",
                "",
                "",
                "",
                "? OVERALL PASS" if not any_fail else "? OVERALL FAIL",
            ),
            tags=("pass",) if not any_fail else ("fail",),
        )

    def add_note(self, script: str, note: NoteEntry) -> None:
        timestamp = note.created_at.strftime("%Y-%m-%d %H:%M:%S")
        self.notes_tree.insert(
            "",
            tk.END,
            values=(script, note.summary, note.path.name, timestamp),
        )
        self._notes.append(note)

    def _on_result_change(self, _evt: tk.Event) -> None:
        selection = self.result_tree.selection()
        if not selection:
            return
        item_id = selection[0]
        row = self.result_tree.item(item_id, "values")
        payload = {
            "script": row[0] if len(row) > 0 else "",
            "index": row[1] if len(row) > 1 else "",
            "original": row[2] if len(row) > 2 else "",
            "test": row[3] if len(row) > 3 else "",
            "diff": row[4] if len(row) > 4 else "",
            "status": row[5] if len(row) > 5 else "",
        }
        self._on_result_select(payload)

    def _open_selected_note(self, _evt: tk.Event) -> None:
        selection = self.notes_tree.selection()
        if not selection:
            return
        row = self.notes_tree.item(selection[0], "values")
        if len(row) < 3:
            return
        file_name = row[2]
        for entry in self._notes:
            if entry.path.name == file_name:
                self._on_note_open(entry.path)
                break


class PreviewPanel(ttk.Frame):
    """Screenshot preview grid (Original/Test/Diff/Highlight)."""

    def __init__(self, master: tk.Misc) -> None:
        super().__init__(master)

        card = ttk.Labelframe(self, text="Screenshot Preview", padding=8)
        card.pack(fill=tk.BOTH, expand=True)

        grid = ttk.Frame(card)
        grid.pack(fill=tk.BOTH, expand=True)
        for i in range(2):
            grid.grid_columnconfigure(i, weight=1, uniform="preview")
            grid.grid_rowconfigure(i, weight=1, uniform="preview")

        self.preview_labels: Dict[str, ttk.Label] = {}
        for row, col, label_text, key in (
            (0, 0, "Original (O)", "O"),
            (0, 1, "Playback (T)", "T"),
            (1, 0, "Black/White Diff (D)", "D"),
            (1, 1, "Highlighted Diff (H)", "H"),
        ):
            frame = ttk.Frame(grid)
            frame.grid(row=row, column=col, sticky="nsew", padx=4, pady=4)
            ttk.Label(frame, text=label_text, bootstyle="secondary").pack(anchor="w")
            lbl = ttk.Label(frame, anchor="center", relief=tk.SUNKEN, cursor="hand2")
            lbl.pack(fill=tk.BOTH, expand=True)
            self.preview_labels[key] = lbl

        self._thumb_cache: Dict[tuple[str, float, int, int], ImageTk.PhotoImage] = {}
        self._current_preview_paths: Dict[str, Optional[Path]] = {"O": None, "T": None, "D": None, "H": None}

    def reset(self) -> None:
        self._thumb_cache.clear()
        for lbl in self.preview_labels.values():
            lbl.configure(image="")
            lbl.image = None

    def bind_open_handlers(self, open_handler: Callable[[str], None]) -> None:
        for key, label in self.preview_labels.items():
            label.bind("<Button-1>", lambda _evt, k=key: open_handler(k))

    def update_images(self, orig_path: Path, test_path: Path) -> None:
        maxw, maxh = self._thumb_size()
        thumbs = {
            "O": self._load_thumb(orig_path, maxw, maxh),
            "T": self._load_thumb(test_path, maxw, maxh),
        }
        stem = test_path.stem
        diff_name = (stem[:-1] + "D") if stem and stem[-1] in ("T", "O") else (stem + "_D")
        hi_name = (stem[:-1] + "H") if stem and stem[-1] in ("T", "O") else (stem + "_H")
        thumbs["D"] = self._load_thumb(test_path.with_name(diff_name + test_path.suffix), maxw, maxh)
        thumbs["H"] = self._load_thumb(test_path.with_name(hi_name + test_path.suffix), maxw, maxh)

        for key, image in thumbs.items():
            label = self.preview_labels[key]
            label.configure(image=image)
            label.image = image

        self._current_preview_paths = {
            "O": orig_path,
            "T": test_path,
            "D": test_path.with_name(diff_name + test_path.suffix),
            "H": test_path.with_name(hi_name + test_path.suffix),
        }

    def current_paths(self) -> Dict[str, Optional[Path]]:
        return dict(self._current_preview_paths)

    def _thumb_size(self) -> tuple[int, int]:
        try:
            label = self.preview_labels.get("O")
            if label is None:
                raise RuntimeError
            frame = label.master
            frame.update_idletasks()
            total_w = frame.winfo_width() or frame.winfo_reqwidth() or 600
            total_h = frame.winfo_height() or frame.winfo_reqheight() or 340
            pad_w = 8
            pad_h = 16
            cell_w = max(220, total_w - pad_w)
            cell_h = max(180, total_h - pad_h)
            return (cell_w, cell_h)
        except Exception:
            return (640, 360)

    def _load_thumb(self, path: Path, maxw: int, maxh: int) -> Optional[ImageTk.PhotoImage]:
        try:
            mtime = path.stat().st_mtime
        except Exception:
            return None
        key = (str(path), mtime, maxw, maxh)
        cached = self._thumb_cache.get(key)
        if cached is not None:
            return cached
        try:
            with Image.open(path) as im:
                im = im.copy()
            im.thumbnail((maxw, maxh), Image.LANCZOS)
            ph = ImageTk.PhotoImage(im)
            self._thumb_cache[key] = ph
            return ph
        except Exception:
            return None


class LogPanel(ttk.Frame):
    """Scrollable log output widget."""

    def __init__(self, master: tk.Misc) -> None:
        super().__init__(master)
        card = ttk.Labelframe(self, text="Log", padding=8)
        card.pack(fill=tk.BOTH, expand=True, pady=(12, 0))

        self.text = scrolledtext.ScrolledText(card, height=6, wrap="word")
        self.text.pack(fill=tk.BOTH, expand=True)
        self.text.configure(state="disabled")

    def attach_logger(self) -> None:
        class TkHandler(logging.Handler):
            def __init__(self, widget: tk.Text):
                super().__init__()
                self.widget = widget
                self.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))

            def emit(self, record: logging.LogRecord) -> None:
                msg = self.format(record)

                def append() -> None:
                    try:
                        self.widget.configure(state="normal")
                        self.widget.insert("end", msg + "\n")
                        self.widget.see("end")
                        if int(self.widget.index('end-1c').split('.')[0]) > 2000:
                            self.widget.delete("1.0", "1000.0")
                        self.widget.configure(state="disabled")
                    except Exception:
                        pass

                try:
                    self.widget.after(0, append)
                except Exception:
                    pass

        handler = TkHandler(self.text)
        logging.getLogger().addHandler(handler)


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------

def open_path_in_explorer(path: Path) -> None:
    try:
        if path.is_dir():
            subprocess.run(["explorer", str(path)], check=False)
        else:
            subprocess.run(["explorer", "/select,", str(path)], check=False)
    except Exception:
        try:
            os.startfile(str(path))  # type: ignore[attr-defined]
        except Exception:
            _LOGGER.warning("Failed to open path %s", path)






































