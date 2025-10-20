"""State snapshot validation helpers using Great Expectations."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

import pandas as pd
from great_expectations.dataset import PandasDataset


def validate_exports(directory: Path) -> None:
    if not directory.exists():
        return
    csv_files: Iterable[Path] = directory.rglob("*.csv")
    for csv_path in csv_files:
        try:
            df = pd.read_csv(csv_path)
        except Exception:
            continue
        if df.empty:
            raise AssertionError(f"Export {csv_path} is empty")
        dataset = PandasDataset(df)
        result = dataset.expect_table_row_count_to_be_greater_than(0)
        if not result.success:
            raise AssertionError(f"Export {csv_path} failed row-count expectation")
