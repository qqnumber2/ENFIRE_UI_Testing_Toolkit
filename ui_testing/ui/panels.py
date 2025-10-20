# ui_testing/ui/panels.py
from __future__ import annotations

import logging
import os
import subprocess
from collections import OrderedDict
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence
from datetime import datetime

import tkinter as tk
from tkinter import scrolledtext

import ttkbootstrap as ttk
from ttkbootstrap.constants import *
from ttkbootstrap.tooltip import ToolTip
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
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def _is_dark_color(hex_color: str) -> bool:
    try:
        return _relative_luminance(hex_color) < 0.5
    except Exception:
        return False


_LOGGER = logging.getLogger(__name__)
class ActionsPanel(ttk.Frame):
    """Top toolbar with record/playback controls and global options."""

    def __init__(
        self,
        master: tk.Misc,
        *,
        record_callback: Callable[[], None],
        stop_record_callback: Callable[[], None],
        run_selected_callback: Callable[[], None],
        run_all_callback: Callable[[], None],
        normalize_callback: Callable[[], None],
        choose_normalize_callback: Callable[[], None],
        normalize_label_var: tk.StringVar,
        clear_normalize_callback: Callable[[], None],
        open_logs_callback: Callable[[], None],
        instructions_callback: Callable[[], None],
        settings_callback: Callable[[], None],
        semantic_helper_callback: Callable[[], None],
        inspector_callback: Callable[[], None],
    ) -> None:
        super().__init__(master)
        toolbar = ttk.Frame(self, padding=(12, 10))
        toolbar.pack(fill=tk.X)
        toolbar.grid_columnconfigure(0, weight=1)
        toolbar.grid_columnconfigure(1, weight=0)

        self._button_container = ttk.Frame(toolbar)
        self._button_container.grid(row=0, column=0, sticky="ew")
        self._button_container.bind("<Configure>", self._on_button_container_resize)
        self._button_widgets: List[tk.Widget] = []

        primary_buttons = [
            {
                "label": "Record New",
                "command": record_callback,
                "style": "primary",
                "icon": "⏺",
                "tooltip": "Record New (Ctrl+R)",
            },
            {
                "label": "Stop Recording",
                "command": stop_record_callback,
                "style": "warning",
                "icon": "⏹",
                "tooltip": "Stop Recording (F)",
            },
            {
                "label": "Run Selected",
                "command": run_selected_callback,
                "style": "success",
                "icon": "▶",
                "tooltip": "Run Selected (Ctrl+Enter)",
            },
            {
                "label": "Run All",
                "command": run_all_callback,
                "style": "success-outline",
                "icon": "⏯",
                "tooltip": "Run All Tests",
            },
            {
                "label": "Instructions",
                "command": instructions_callback,
                "style": "info-outline",
                "icon": "ℹ",
                "tooltip": "Instructions",
            },
            {
                "label": "Open Logs",
                "command": open_logs_callback,
                "style": "secondary-outline",
                "icon": "🗒",
                "tooltip": "Open Logs",
            },
            {
                "label": "Normalize ENFIRE",
                "command": normalize_callback,
                "style": "secondary",
                "icon": "⟳",
                "tooltip": "Run normalize script",
            },
            {
                "label": "Set Normalize Script",
                "command": choose_normalize_callback,
                "style": "secondary-link",
            },
            {
                "label": "Clear Normalize",
                "command": clear_normalize_callback,
                "style": "danger-outline",
            },
            {
                "label": "Settings",
                "command": settings_callback,
                "style": "secondary",
                "icon": "⚙",
                "tooltip": "Settings",
            },
            {
                "label": "Semantic Helper",
                "command": semantic_helper_callback,
                "style": "info",
                "icon": "Σ",
                "tooltip": "Semantic Helper",
            },
            {
                "label": "Inspector",
                "command": inspector_callback,
                "style": "secondary",
                "icon": "🔍",
                "tooltip": "Automation Inspector",
            },
        ]
        for spec in primary_buttons:
            text = spec.get("icon") or spec["label"]
            btn = ttk.Button(
                self._button_container,
                text=text,
                command=spec["command"],
                bootstyle=spec.get("style", "secondary"),
                width=4 if spec.get("icon") else 12,
            )
            tooltip_text = spec.get("tooltip")
            if tooltip_text:
                ToolTip(btn, tooltip_text)
            self._button_widgets.append(btn)

        self._normalize_label = ttk.Label(
            self._button_container,
            textvariable=normalize_label_var,
            bootstyle="secondary",
            anchor="w",
            padding=(8, 2),
        )
        self._button_widgets.append(self._normalize_label)
        try:
            idx = next(
                i for i, spec in enumerate(primary_buttons) if spec["label"] == "Set Normalize Script"
            ) + 1
            self._button_widgets.insert(idx, self._button_widgets.pop())
        except StopIteration:
            pass

        self.after(100, self._reflow_buttons)

    def _on_button_container_resize(self, event: tk.Event) -> None:
        self._reflow_buttons(event.width)

    def _reflow_buttons(self, width: Optional[int] = None) -> None:
        if not self._button_widgets:
            return
        container = self._button_container
        if width is None or width <= 0:
            width = container.winfo_width() or 1
        columns = max(1, len(self._button_widgets))
        for child in container.winfo_children():
            child.grid_forget()
        for index, widget in enumerate(self._button_widgets):
            row = index // columns
            col = index % columns
            widget.grid(row=row, column=col, padx=4, pady=2, sticky="ew")
        for col_index in range(columns):
            container.grid_columnconfigure(col_index, weight=1)


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
            style="TestsPanel.Badge.TLabel",
        )
        self._count_badge.pack(side=tk.LEFT)
        self._summary_label = ttk.Label(
            self._info_row,
            textvariable=self.selected_tests_var,
            wraplength=260,
            style="TestsPanel.Summary.TLabel",
        )
        self._summary_label.pack(side=tk.LEFT, padx=(10, 0), fill=tk.X, expand=True)
        ttk.Button(
            self._info_row,
            text="Deselect All",
            command=self.clear_selection,
            bootstyle="secondary-outline",
        ).pack(side=tk.RIGHT)

        self._info_row.bind("<Configure>", self._on_info_row_resize)

        self._menu = tk.Menu(self, tearoff=False)
        self._menu.add_command(label="Open JSON", command=self._open_selected_json)
        self._menu.add_command(label="Delete Test", command=self._delete_selected_test)

        self._ensure_tree_styles()
        self._apply_info_styles()

    def populate(self, grouped_tests: Dict[str, Sequence[object]]) -> None:
        previous_selection = list(self._selected_scripts.keys())
        selected_tab_text = None
        if self.nb.tabs():
            try:
                current_tab = self.nb.select()
                selected_tab_text = self.nb.tab(current_tab, "text")
            except Exception:
                selected_tab_text = None
        self._test_map.clear()
        self._script_to_item.clear()
        self._display_map.clear()
        self._context_leaf = None
        self._updating_selection = False
        self._press_info = None

        for tab in self.nb.tabs():
            self.nb.forget(tab)
        self._trees.clear()

        for proc in sorted(grouped_tests.keys(), key=self._numeric_key):
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
        if selected_tab_text:
            for tab_id in self.nb.tabs():
                if self.nb.tab(tab_id, "text") == selected_tab_text:
                    try:
                        self.nb.select(tab_id)
                    except Exception:
                        pass
                    break

    def _populate_tree(self, tree: ttk.Treeview, script_list: Sequence[object]) -> None:
        nodes: Dict[tuple[str, ...], str] = {}
        for entry in sorted(script_list, key=lambda value: self._numeric_key(str(value))):
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

    def _on_info_row_resize(self, event: tk.Event) -> None:
        extra = max(event.width - 210, 140)
        self._summary_label.configure(wraplength=extra)

    def on_theme_changed(self) -> None:
        self._apply_info_styles()

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
        tree_style = "TestsPanel.Treeview"

        tree_fg = style.lookup("Treeview", "foreground") or summary_fg
        tree_bg = style.lookup("Treeview", "background") or frame_bg
        tree_field = style.lookup("Treeview", "fieldbackground") or tree_bg
        tree_sel_bg = style.lookup("Treeview", "selectbackground") or _blend_colors(tree_bg, badge_bg, 0.35)
        tree_sel_fg = style.lookup("Treeview", "selectforeground") or badge_fg

        style.configure(info_style, background=frame_bg)
        style.configure(badge_style, background=badge_bg, foreground=badge_fg, font=("", 10, "bold"))
        style.configure(summary_style, background=frame_bg, foreground=tree_fg, font=("", 10))

        style.configure(
            tree_style,
            foreground=tree_fg,
            background=tree_bg,
            fieldbackground=tree_field,
            rowheight=style.lookup("Treeview", "rowheight") or 26,
        )
        style.map(
            tree_style,
            foreground=[("selected", tree_sel_fg)],
            background=[("selected", tree_sel_bg)],
        )

        self._info_row.configure(style=info_style)
        self._count_badge.configure(style=badge_style, foreground=badge_fg, background=badge_bg)
        self._summary_label.configure(style=summary_style, foreground=tree_fg, background=frame_bg)

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

    def _numeric_key(self, value: str):
        try:
            parts = Path(value).parts
        except Exception:
            parts = (value,)
        key_parts = []
        for part in parts:
            if part.isdigit():
                key_parts.append(("num", int(part)))
            else:
                try:
                    key_parts.append(("num", int(part)))
                except ValueError:
                    key_parts.append(("str", part))
        return tuple(key_parts)
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

        progress_frame = ttk.Frame(results_frame)
        progress_frame.pack(fill=tk.X, pady=(0, 6))
        self._progress_label_var = tk.StringVar(value="Idle")
        self._progress_value = tk.DoubleVar(value=0.0)
        self._progress_label = ttk.Label(progress_frame, textvariable=self._progress_label_var)
        self._progress_label.pack(side=tk.LEFT, padx=(0, 8))
        self._progress_bar = ttk.Progressbar(
            progress_frame,
            mode="determinate",
            maximum=1.0,
            variable=self._progress_value,
            bootstyle="info-striped",
        )
        self._progress_bar.pack(side=tk.LEFT, fill=tk.X, expand=True)

        cols = ("script", "index", "timestamp", "original", "test", "diff", "status")
        display_cols = ("script", "index", "timestamp", "diff", "status")
        self.result_tree = ttk.Treeview(
            results_frame,
            columns=cols,
            displaycolumns=display_cols,
            show="headings",
            height=12,
            bootstyle="info",
        )
        headings = {
            "script": "Script",
            "index": "Idx",
            "timestamp": "Time",
            "original": "Original",
            "test": "Test",
            "diff": "Diff (%)",
            "status": "Status",
        }
        self._heading_labels = headings
        self._sortable_columns = display_cols
        self._column_indices = {name: idx for idx, name in enumerate(cols)}
        self._active_sort: Optional[tuple[str, bool]] = None
        for cid, width, anchor in (
            ("script", 320, "w"),
            ("index", 80, "center"),
            ("timestamp", 180, "center"),
            ("diff", 260, "w"),
            ("status", 140, "center"),
        ):
            self.result_tree.heading(
                cid,
                text=headings[cid],
                command=lambda col=cid: self._sort_results(col),
            )
            self.result_tree.column(cid, width=width, anchor=anchor)
        for hidden in ("original", "test"):
            self.result_tree.column(hidden, width=1, stretch=False, minwidth=1)

        self.result_tree.pack(fill=tk.BOTH, expand=True)
        self._refresh_heading_text()
        self.result_tree.tag_configure("pass", foreground="#0b6e2e", font="-weight bold")
        self.result_tree.tag_configure("warn", foreground="#a35f00", font="-weight bold")
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
        self._active_sort = None
        self._refresh_heading_text()
        self._progress_label_var.set("Idle")
        self._progress_value.set(0.0)

    def begin_run(self, total_scripts: int) -> None:
        if total_scripts <= 0:
            self._progress_bar.configure(mode="determinate", maximum=1.0)
            self._progress_value.set(0.0)
            self._progress_label_var.set("Idle")
            return
        self._progress_bar.configure(mode="determinate", maximum=float(total_scripts))
        self._progress_value.set(0.0)
        self._progress_label_var.set(f"0 / {total_scripts} scripts")

    def update_progress(
        self,
        script: str,
        script_index: int,
        total_scripts: int,
        checkpoint: Optional[str] = None,
        checkpoint_timestamp: Optional[str] = None,
    ) -> None:
        total = max(1, total_scripts)
        self._progress_bar.configure(maximum=float(total))
        self._progress_value.set(float(min(script_index, total)))
        details: List[str] = []
        if checkpoint:
            details.append(f"checkpoint {checkpoint}")
        if checkpoint_timestamp:
            details.append(checkpoint_timestamp)
        label = f"{script_index}/{total} - {script}"
        if details:
            label = f"{label} ({' | '.join(details)})"
        self._progress_label_var.set(label)

    def append_results(self, script_name: str, results: Sequence[Dict[str, str]]) -> None:
        summary_level = "pass"
        summary_data: Optional[Dict[str, str]] = None
        latest_item = None
        for r in results:
            idx = r.get("index", 0)
            if isinstance(idx, str) and str(idx).lower() == "summary":
                summary_data = r
                continue
            orig = r.get("original", "")
            test = r.get("test", "")
            diffp = r.get("diff_percent", "")
            status = r.get("status", "fail")
            timestamp = r.get("timestamp", "")
            note = r.get("note", "")
            if status == "pass":
                tag = "pass"
            elif status == "warn":
                tag = "warn"
            else:
                tag = "fail"
            if tag == "fail":
                summary_level = "fail"
            elif tag == "warn" and summary_level != "fail":
                summary_level = "warn"
            metrics = r.get("metrics")
            diff_str = ""
            if metrics:
                diff_str = str(metrics)
            else:
                try:
                    diff_val = float(diffp)
                    diff_str = f"{diff_val:.3f}"
                except Exception:
                    diff_str = ""
            if note:
                diff_str = f"{diff_str} | {note}" if diff_str else note
            diff_str = diff_str.strip(" |")
            try:
                idx_display = int(idx) + 1
            except Exception:
                idx_display = idx
            if status == "warn":
                status_display = "WARN"
            else:
                status_display = "PASS" if tag == "pass" else "FAIL"
            latest_item = self.result_tree.insert(
                "",
                tk.END,
                values=(
                    script_name,
                    idx_display,
                    timestamp,
                    orig,
                    test,
                    diff_str,
                    status_display,
                ),
                tags=("detail", tag),
            )
        summary_note = ""
        if summary_data:
            summary_level = summary_data.get("status", summary_level)
            summary_note = summary_data.get("note", "")
        if summary_level == "fail":
            summary_status = "OVERALL FAIL"
            summary_tags = ("summary", "fail")
        elif summary_level == "warn":
            summary_status = "OVERALL WARN"
            summary_tags = ("summary", "warn")
            if not summary_note:
                summary_note = "Run completed without validations."
        else:
            summary_status = "OVERALL PASS"
            summary_tags = ("summary", "pass")
        summary_item = self.result_tree.insert(
            "",
            tk.END,
            values=(
                script_name,
                "",
                "",
                "",
                "",
                summary_note,
                summary_status,
            ),
            tags=summary_tags,
        )
        if summary_item:
            self.result_tree.see(summary_item)
        elif latest_item:
            self.result_tree.see(latest_item)
        if self._active_sort:
            self._reapply_active_sort()

    def on_theme_changed(self) -> None:
        try:
            self.result_tree.tag_configure("pass", foreground="#0b6e2e", font="-weight bold")
            self.result_tree.tag_configure("warn", foreground="#a35f00", font="-weight bold")
            self.result_tree.tag_configure("fail", foreground="#b00020", font="-weight bold")
        except Exception:
            pass

    def _sort_results(self, column: str) -> None:
        current_column, current_direction = self._active_sort if self._active_sort else (None, True)
        if current_column == column:
            ascending = not current_direction
        else:
            ascending = True
        self._apply_sort(column, ascending, remember=True)

    def _apply_sort(self, column: str, ascending: bool, *, remember: bool) -> None:
        idx = self._column_indices.get(column)
        if idx is None:
            return
        detail_items: List[tuple[object, str]] = []
        summary_items: List[str] = []
        for item in self.result_tree.get_children(""):
            tags = tuple(self.result_tree.item(item, "tags") or ())
            if "summary" in tags:
                summary_items.append(item)
                continue
            values = self.result_tree.item(item, "values")
            value = values[idx] if idx < len(values) else ""
            sort_key = self._coerce_sort_key(column, value)
            detail_items.append((sort_key, item))
        detail_items.sort(key=lambda rec: (rec[0] is None, rec[0]))
        if not ascending:
            detail_items.reverse()
        for _, item_id in detail_items:
            self.result_tree.move(item_id, "", tk.END)
        for item_id in summary_items:
            self.result_tree.move(item_id, "", tk.END)
        if remember:
            self._active_sort = (column, ascending)
        self._refresh_heading_text()

    def _reapply_active_sort(self) -> None:
        if not self._active_sort:
            return
        column, ascending = self._active_sort
        self._apply_sort(column, ascending, remember=False)

    def _coerce_sort_key(self, column: str, value: object) -> Optional[object]:
        if value is None:
            return None
        text = str(value).strip()
        if not text:
            return None
        if column == "index":
            try:
                return int(float(text))
            except Exception:
                return None
        if column == "timestamp":
            try:
                return datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
            except Exception:
                return text
        if column == "diff":
            try:
                return float(text)
            except Exception:
                return None
        if column == "status":
            mapping = {"PASS": 0, "FAIL": 1}
            return mapping.get(text.upper(), 2)
        return text.lower()

    def _refresh_heading_text(self) -> None:
        active_column = None
        ascending = True
        if self._active_sort:
            active_column, ascending = self._active_sort
        for cid in self._sortable_columns:
            label = self._heading_labels.get(cid, cid.title())
            if cid == active_column:
                suffix = "ASC" if ascending else "DESC"
                label = f"{label} ({suffix})"
            self.result_tree.heading(
                cid,
                text=label,
                command=lambda col=cid: self._sort_results(col),
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
            "timestamp": row[2] if len(row) > 2 else "",
            "original": row[3] if len(row) > 3 else "",
            "test": row[4] if len(row) > 4 else "",
            "diff": row[5] if len(row) > 5 else "",
            "status": row[6] if len(row) > 6 else "",
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

    def on_theme_changed(self) -> None:
        pass


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





































