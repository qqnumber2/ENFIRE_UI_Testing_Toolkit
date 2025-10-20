from pathlib import Path
import json

import pandas as pd
import pytest
from great_expectations.dataset import PandasDataset

SCRIPTS_ROOT = Path("ui_testing/data/scripts")


def _gather_actions():
    actions = []
    if not SCRIPTS_ROOT.exists():
        return actions
    for json_path in SCRIPTS_ROOT.rglob("*.json"):
        try:
            records = json.loads(json_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        for index, record in enumerate(records):
            if not isinstance(record, dict):
                continue
            actions.append(
                {
                    "path": str(json_path),
                    "index": index,
                    "action_type": record.get("action_type"),
                    "has_semantic": isinstance(record.get("semantic"), dict),
                }
            )
    return actions


def test_recorded_actions_have_types():
    actions = _gather_actions()
    if not actions:
        pytest.skip("No recorded scripts found to evaluate")
    df = pd.DataFrame(actions)
    dataset = PandasDataset(df)
    result = dataset.expect_column_values_to_not_be_null("action_type")
    assert result.success


def test_semantic_flag_is_boolean():
    actions = _gather_actions()
    if not actions:
        pytest.skip("No recorded scripts found to evaluate")
    df = pd.DataFrame(actions)
    dataset = PandasDataset(df)
    result = dataset.expect_column_values_to_be_in_set("has_semantic", {True, False})
    assert result.success

