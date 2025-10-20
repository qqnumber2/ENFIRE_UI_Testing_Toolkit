# Tooling Setup

## Appium / WinAppDriver

1. Install [Appium Server](https://appium.io/) (or `npm install -g appium`).
2. Install WinAppDriver = 1.2 and ensure the service is running (`WinAppDriver.exe 127.0.0.1 4723`).
3. Configure ENFIRE launch capabilities (see `docs/tools/appium_capabilities.py`).

## Visual Diff

- `opencv-python-headless` + `scikit-image` are installed via `requirements.txt`.
- SSIM helper lives in `ui_testing/automation/vision/ssim.py`.

## Reporting

- Install Allure CLI from [GitHub](https://github.com/allure-framework/allure2/releases) and add it to `PATH`.
- Test runs will emit `allure-results/` for aggregation.

## API & Data Tools

- `pytest`, `hypothesis`, and `great_expectations` are available for API/property/state validation.
- Run automated checks: `pytest` (unit/API/data suites).
