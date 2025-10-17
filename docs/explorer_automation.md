# Explorer Automation Design

## Overview

Playback covers ENFIRE itself, but many test flows open Windows Explorer to validate log drops, export directories, or attachment transfers. We need a predictable way to describe those file–explorer steps so recorder output can drive Explorer deterministically and without recording arbitrary screen coordinates.

## Goals

- Express common Explorer interactions (navigate path, select file/folder, copy/move/delete, create folders, drag-drop into ENFIRE) as strongly-typed actions.
- Keep JSON scripts mostly backward compatible so existing runs still succeed.
- Make playback resilient to Explorer layout differences (view mode, window size).
- Provide a roadmap for eventually auto-recording these steps instead of asking users to hand-edit JSON.

## Typical Use Cases

1. Navigate to a known export directory and verify output files were created.
2. Copy a template file from a repository share into an ENFIRE staging folder.
3. Drag a file from Explorer into the ENFIRE window (requires Explorer automation to supply the drag source).
4. Delete leftover screenshots or logs between runs.

## Action Model Additions

Introduce a new `explorer` action group with explicit subtypes instead of overloading the existing pointer actions:

| `action_type`        | Required fields                                                | Purpose                                   |
|----------------------|----------------------------------------------------------------|-------------------------------------------|
| `explorer.open`      | `path` (string)                                                | Launch Explorer window rooted at `path`.  |
| `explorer.navigate`  | `path` (string)                                                | Navigate the focused Explorer instance.   |
| `explorer.select`    | `items` (list of names), optional `view`                       | Select one or more entries.               |
| `explorer.copy`      | optional `items`, optional `destination`                       | Copy selection or named items.            |
| `explorer.move`      | optional `items`, required `destination`                       | Move selection or named items.            |
| `explorer.delete`    | optional `items`, optional `recycle` (bool)                    | Delete current selection or named items.  |
| `explorer.ensure`    | `path` (string), optional `kind` (`file`/`dir`), optional `template` | Create folders or seed files if missing. |
| `explorer.drag_to_enfire` | `source` (file/folder), optional `target` (ENFIRE locator) | Stage forthcoming cross-window drags.    |

All Explorer actions reuse the existing `delay` field so they participate in pacing controls. Additional metadata lives under a new optional `explorer` payload when we need more structured parameters.

### JSON Shape

```json
{
  "action_type": "explorer.navigate",
  "delay": 0.0,
  "explorer": {
    "path": "C:/Users/Public/Documents/ENFIRE/Exports"
  }
}
```

`explorer` payload keys are explicit to avoid mixing concerns with the legacy top level.

## Recorder Strategy

Phase 1 (manual authoring) keeps recorder unchanged. Users can insert Explorer actions via the upcoming JSON editor or through a lightweight "Explorer Macro" dialog in the GUI.

Phase 2 adds optional recorder helpers:

- A dedicated "Record Explorer Step" hotkey opens a prompt to capture a typed command (navigate/copy/etc.) instead of raw mouse data.
- Recorder stores the Explorer command in the new action format, skipping screenshots and coordinate diffs for those steps.

## Playback Strategy

Add an `ExplorerController` class to orchestrate Explorer actions. The player delegates actions whose `action_type` starts with `explorer.` to the controller.

Responsibilities:

- Launch and cache an Explorer window handle (via `subprocess` or `pywinauto` Desktop enumeration).
- Use `pywinauto`'s `Application(backend="uia")` to drive address bar navigation and item selection.
- Fall back to `os`/`shutil` for filesystem operations when a visible Explorer window is unnecessary (e.g., `ensure`, `copy`, `delete`). This keeps runs reliable even if Explorer renders differently.
- For `drag_to_enfire`, prepare a data object describing the drag source so the main player can synthesize a drag from Explorer coordinates into ENFIRE using existing pointer primitives.

Errors bubble up through the existing player logging, but we add clearer messages (e.g., "Explorer navigate failed: path not found").

## Integration Points

1. **Schema**: extend `Action` dataclass with an optional `explorer` dictionary and list of strings (`items`). The player keeps ignoring them for non-Explorer actions.
2. **Player routing**: new method `Player._play_explorer_action(action: Action)` that calls `ExplorerController`.
3. **Settings/UI**: expose a toggle allowing labs to disable Explorer automation if env policies forbid it.
4. **Tests**: create unit tests mocking `pywinauto` to ensure navigation/select/copy flows map to the proper backend calls.

## Open Questions

- How to identify ENFIRE drop targets for `drag_to_enfire`? Likely reuse AutomationId data already captured during ENFIRE recordings.
- Should we allow relative paths resolved against the current script directory? (Recommended: yes, default base `paths.root`.)
- How do we handle multiple Explorer windows? We can store a mapping of handles keyed by requested root path.

## Next Steps

1. Implement `ExplorerController` skeleton with method stubs and dependency injection hooks.
2. Extend the `Action` dataclass and JSON serializer/deserializer to accept the new payload (while keeping backwards compatibility).
3. Update the GUI to preview and edit Explorer steps (table view with human-readable summary).
4. Prototype `explorer.navigate` and `explorer.select` playback, test against Windows 10/11 stable builds.
