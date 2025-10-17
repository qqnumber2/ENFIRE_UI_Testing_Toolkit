# ENFIRE Automation ID Contract

The ENFIRE WPF client must expose stable automation identifiers so the `ui_testing` harness (and any future
Appium/Ranorex suites) can interact with controls reliably. This contract outlines the conventions and highlights
which areas were instrumented in this change.

## Guiding Principles

- **Declare identifiers in code** – add constants to `Enfire.EsriRuntime.Wpf.Utility.AutomationIds` so they can be
  shared between product code and tests.
- **Bind once, reuse everywhere** – XAML should reference identifiers with
  `AutomationProperties.AutomationId="{x:Static automation:SomeIds.SomeValue}"`. Avoid string literals.
- **Name dynamic content** – for data-driven controls (list items, menus) keep `AutomationProperties.Name`
  or expose a view-model property so individual instances remain discoverable.
- **Avoid breaking renames** – if an identifier must change, provide an `[Obsolete]` alias until test artifacts
  have migrated.

## Coverage Expectations

| Surface                  | Requirement                                                                    |
|--------------------------|--------------------------------------------------------------------------------|
| Main shell chrome        | Title-bar buttons, device toggles, recording indicators                        |
| Map toolbar/toolbelt     | Radial menu, scale display, combo box, coordinate label, go-to & basemap tools |
| Explorer panes           | Back/close buttons and root navigation list                                   |
| Recon editors/dialogs    | Tabs, primary actions, confirmation buttons                                   |
| Export/settings wizards  | Navigation buttons and options (checkboxes, radio buttons, list items)        |
| Toasts/transient UI      | At minimum provide `AutomationProperties.Name` for visibility assertions       |

## Enforcement Workflow

1. **Authoring** – land identifier constants and XAML updates together.
2. **Manifest generation** (future) – emit an `automation_ids.json` artifact during the build so automated tests
   can validate their selectors.
3. **Build validation** – add a CI guard that fails when modified XAML introduces a button/toggle without an
   automation identifier.
4. **Playback** – `ui_testing` should prefer automation IDs and fall back to screenshots only for intentionally
   visual checkpoints.

## Additions in This Change

- Added `MapControlIds`, `ShellIds`, and `ExplorerIds` to `Source/Enfire.EsriRuntime.Wpf/Utility/AutomationIds`.
- Instrumented the map toolbelt (`MainWindow/Views/MainWindow.xaml`) with IDs for radial menu, custom zoom, scale
  combo, coordinate display, go-to toggle/execute, manual set location, and basemap selector.
- Tagged shell chrome buttons in `MainWindow/Views/ShellView.xaml` (close, maximize/restore, minimize, device refresh,
  device status toggle, recording indicator).
- Tagged explorer navigation controls in `Explorer/Views/ExplorerView.xaml` and `Explorer/Views/ExplorerPaneView.xaml`.

## Next Steps

- Extend the contract through recon editors and export/report wizards (checkboxes, list selectors, finish buttons).
- Generate the automation manifest automatically and ship it alongside the ENFIRE installer.
- Mirror these conventions in the Android “Dismounted” client before introducing cross-platform playback.
