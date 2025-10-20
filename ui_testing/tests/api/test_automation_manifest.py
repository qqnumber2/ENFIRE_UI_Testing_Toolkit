from pathlib import Path
from typing import Iterable

import pytest
from hypothesis import given, strategies as st

from ui_testing.automation.semantic.loader import load_registry

MANIFEST_PATH = Path("ui_testing/automation/manifest/automation_ids.json")
registry = load_registry(MANIFEST_PATH)
_groups = tuple(registry.groups())
group_strategy = st.sampled_from(_groups) if _groups else st.just("")

@pytest.fixture(scope="module")
def automation_entries() -> Iterable:
    if not _groups:
        pytest.skip("Automation manifest is empty")
    entries = []
    for group in _groups:
        entries.extend(registry.by_group(group).values())
    return entries

@given(group_strategy)
def test_each_group_has_entries(group: str):
    if not group:
        pytest.skip("No automation groups available")
    entries = registry.by_group(group)
    assert entries, f"Group {group} should expose AutomationIds"

@given(st.data())
def test_manifest_entries_have_ids(data):
    entries = []
    for group in _groups:
        entries_in_group = list(registry.by_group(group).values())
        if entries_in_group:
            entries.append(entries_in_group)
    if not entries:
        pytest.skip("No automation entries available")
    cohort = data.draw(st.sampled_from(entries))
    entry = data.draw(st.sampled_from(cohort))
    assert entry.automation_id
    assert entry.group

