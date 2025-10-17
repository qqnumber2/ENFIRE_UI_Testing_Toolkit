"""Background services such as AI summarisation and test plan updates."""

from .ai_summarizer import BugNote, write_run_bug_report
from .testplan import TestPlanReporter
