# Semantic Testing

This document will outline semantic automation workflows.

## Quick Start (Semantic Driver)

```python
from ui_testing.automation.driver import get_session
from ui_testing.automation.semantic.loader import load_registry
from ui_testing.automation.semantic.screens import MapToolbarScreen

session = get_session()
registry = load_registry()
map_toolbar = MapToolbarScreen(session, registry)

map_toolbar.open_radial_menu()
map_toolbar.select_map_scale("1:12,500")
print("Current coords:", map_toolbar.read_coordinates())
```

Available screens: `MapToolbarScreen`, `AppBarScreen`, `HazardFormScreen`, `BridgeReportScreen`, `TerrainOverlayScreen`.
Run semantic-focused tests with `pytest -m semantic --maxfail=1`.

## Running Test Suites

- `pytest -m semantic --maxfail=1` &ndash; fail fast while exercising semantic automation checks.
- `pytest -m semantic --alluredir=artifacts/semantic` &ndash; generate Allure results for the semantic suite.
- Running `setup_and_deploy.ps1` automatically issues `python -m compileall ui_testing` followed by `pytest -m semantic --maxfail=1`; the build halts if either check fails to keep installers reproducible.
