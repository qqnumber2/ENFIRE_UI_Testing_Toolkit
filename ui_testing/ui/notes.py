# ui_testing/ui/notes.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from ui_testing.services.ai_summarizer import BugNote


@dataclass
class NoteEntry:
    script: str
    created_at: datetime
    bug_note: BugNote

    @property
    def summary(self) -> str:
        return self.bug_note.summary or "(no summary)"

    @property
    def path(self) -> Path:
        return self.bug_note.note_path

    def as_tuple(self) -> tuple[str, str, str]:
        return (
            self.script,
            self.summary,
            self.path.name,
        )

    def matches(self, script: str, note_path: Path) -> bool:
        return self.script == script and self.path == note_path
