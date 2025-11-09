from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional

from ui_testing.app.configuration import load_runtime_config
from ui_testing.app.settings import AppSettings
from ui_testing.tools.calibration import (
    CalibrationProfile,
    capture_window_anchor,
    calibration_dir,
    compute_offset,
    list_profiles,
    load_profile,
    save_profile,
)

try:
    from ui_testing.automation.driver import DEFAULT_WINDOW_SPEC, WindowSpec
except Exception:
    WindowSpec = None  # type: ignore
    DEFAULT_WINDOW_SPEC = None  # type: ignore

logger = logging.getLogger("ui_testing.cli")


def _default_data_root() -> Path:
    return Path(__file__).resolve().parents[2] / "ui_testing" / "data"


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="ui-testing", description="UI Testing Toolkit CLI")
    parser.add_argument("--data-root", type=Path, default=_default_data_root(), help="Data directory (defaults to ui_testing/data)")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose logging")

    subparsers = parser.add_subparsers(dest="command", required=True)

    calibrate_parser = subparsers.add_parser("calibrate", help="Capture the current ENFIRE window position for a calibration profile")
    calibrate_parser.add_argument("--name", required=True, help="Calibration profile name")
    calibrate_parser.add_argument("--overwrite", action="store_true", help="Overwrite existing profile without prompting")
    calibrate_parser.add_argument("--set-default", action="store_true", help="Persist this calibration profile into ui_settings.json")

    list_parser = subparsers.add_parser("calibration-list", help="List available calibration profiles")

    play_parser = subparsers.add_parser("play", help="Replay scripts from the command line")
    play_parser.add_argument("scripts", nargs="+", help="Script names or JSON paths")
    play_parser.add_argument("--calibration", help="Calibration profile to apply")
    play_parser.add_argument("--semantic/--no-semantic", dest="semantic", default=None, action=argparse.BooleanOptionalAction)
    play_parser.add_argument("--screenshots/--no-screenshots", dest="screenshots", default=None, action=argparse.BooleanOptionalAction)

    record_parser = subparsers.add_parser("record", help="Launch recorder without the GUI")
    record_parser.add_argument("script_name", help="Script name relative to scripts directory")
    record_parser.add_argument("--calibration", help="Calibration profile to update during recording")

    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(levelname)s %(name)s - %(message)s")

    runtime_cfg = load_runtime_config()
    logger.debug("Loaded runtime config overrides: %s", runtime_cfg)

    if args.command == "calibrate":
        return _handle_calibrate(args.name, args.data_root, args.overwrite, args.set_default, runtime_cfg)
    if args.command == "calibration-list":
        return _handle_calibration_list(args.data_root)
    if args.command == "play":
        return _handle_play(args, args.data_root, runtime_cfg)
    if args.command == "record":
        return _handle_record(args, args.data_root, runtime_cfg)
    parser.print_help()
    return 1


def _handle_calibrate(name: str, data_root: Path, overwrite: bool, set_default: bool, runtime_cfg) -> int:
    calibration_dir(data_root)
    existing = load_profile(data_root, name)
    if existing and not overwrite:
        logger.error("Calibration profile '%s' already exists. Use --overwrite to replace it.", name)
        return 2
    anchor = capture_window_anchor(DEFAULT_WINDOW_SPEC if WindowSpec else None)
    if anchor is None:
        logger.error("Unable to capture ENFIRE window. Ensure the window is visible and pywinauto is available.")
        return 3
    x, y, width, height = anchor
    profile = CalibrationProfile(name=name, anchor_x=x, anchor_y=y, width=width, height=height)
    save_profile(data_root, profile)
    logger.info("Saved calibration profile '%s' at (%s, %s)", name, x, y)
    if set_default:
        settings, settings_path = _load_settings(data_root, runtime_cfg)
        settings.calibration_profile = name
        settings.save(settings_path)
        logger.info("Updated default calibration profile in %s", settings_path)
    return 0


def _handle_calibration_list(data_root: Path) -> int:
    profiles = list_profiles(data_root)
    if not profiles:
        print("No calibration profiles found.", file=sys.stderr)
        return 1
    for name in profiles:
        profile = load_profile(data_root, name)
        if profile:
            print(f"{name}\tanchor=({profile.anchor_x}, {profile.anchor_y}) updated={profile.updated_at}")
    return 0


def _handle_play(args: argparse.Namespace, data_root: Path, runtime_cfg) -> int:
    from ui_testing.automation.player import Player, PlayerConfig

    scripts_dir = data_root / "scripts"
    images_dir = data_root / "images"
    results_dir = data_root / "results"
    for directory in (scripts_dir, images_dir, results_dir):
        directory.mkdir(parents=True, exist_ok=True)
    settings, settings_path = _load_settings(data_root, runtime_cfg)
    if args.semantic is not None:
        settings.use_automation_ids = bool(args.semantic)
    if args.screenshots is not None:
        settings.use_screenshots = bool(args.screenshots)
    if args.calibration:
        settings.calibration_profile = args.calibration
    manifest = _load_manifest(data_root)
    config = PlayerConfig(
        scripts_dir=scripts_dir,
        images_dir=images_dir,
        results_dir=results_dir,
        taskbar_crop_px=60,
        wait_between_actions=settings.default_delay,
        diff_tolerance=settings.tolerance,
        diff_tolerance_percent=settings.tolerance,
        use_default_delay_always=settings.ignore_recorded_delays,
        use_automation_ids=settings.use_automation_ids,
        use_screenshots=settings.use_screenshots,
        prefer_semantic_scripts=settings.prefer_semantic_scripts,
        use_ssim=settings.use_ssim,
        ssim_threshold=settings.ssim_threshold,
        automation_backend=settings.automation_backend,
        app_title_regex=settings.target_app_regex,
        automation_manifest=manifest,
        semantic_wait_timeout=settings.semantic_wait_timeout,
        semantic_poll_interval=settings.semantic_poll_interval,
        calibration_profile=settings.calibration_profile,
        calibration_dir=data_root,
        appium_server_url=settings.appium_server_url,
        appium_capabilities=settings.appium_capabilities,
        window_spec=DEFAULT_WINDOW_SPEC,
    )
    player = Player(config)
    if manifest:
        player.update_automation_manifest(manifest)
    exit_code = 0
    for script_arg in args.scripts:
        script_path = Path(script_arg)
        script_name = script_path.stem if script_path.suffix == ".json" else script_arg
        try:
            player.play(script_name)
            logger.info("Completed script '%s'", script_name)
        except Exception as exc:
            logger.exception("Playback failed for '%s': %s", script_name, exc)
            exit_code = 4
    return exit_code


def _handle_record(args: argparse.Namespace, data_root: Path, runtime_cfg) -> int:
    from ui_testing.automation.recorder import Recorder, RecorderConfig

    scripts_dir = data_root / "scripts"
    images_dir = data_root / "images"
    results_dir = data_root / "results"
    for directory in (scripts_dir, images_dir, results_dir):
        directory.mkdir(parents=True, exist_ok=True)
    settings, _ = _load_settings(data_root, runtime_cfg)
    if args.calibration:
        settings.calibration_profile = args.calibration
    manifest = _load_manifest(data_root)
    config = RecorderConfig(
        scripts_dir=scripts_dir,
        images_dir=images_dir,
        results_dir=results_dir,
        script_name=args.script_name,
        taskbar_crop_px=60,
        default_delay=settings.default_delay,
        calibration_profile=settings.calibration_profile,
        calibration_dir=data_root,
        automation_manifest=manifest,
        window_spec=DEFAULT_WINDOW_SPEC,
    )
    recorder = Recorder(config)
    recorder.start()
    logger.info("Recorder started for '%s'. Press F in ENFIRE to stop.", args.script_name)
    try:
        while recorder.running:
            time.sleep(0.1)
    except KeyboardInterrupt:
        recorder.stop()
    return 0


def _load_settings(data_root: Path, runtime_cfg) -> tuple[AppSettings, Path]:
    settings_path = data_root / "ui_settings.json"
    settings = AppSettings.load(settings_path)
    runtime_cfg.apply_to_settings(settings)
    return settings, settings_path


def _load_manifest(data_root: Path) -> Dict[str, Dict[str, Dict[str, Any]]]:
    package_root = data_root.parent
    candidates = [
        package_root / "automation_ids.json",
        package_root / "automation" / "automation_ids.json",
        package_root / "ui_testing" / "automation" / "manifest" / "automation_ids.json",
    ]
    for candidate in candidates:
        if candidate.exists():
            try:
                manifest = json.loads(candidate.read_text(encoding="utf-8"))
                if isinstance(manifest, dict) and "groups" in manifest:
                    manifest = manifest["groups"]
                if isinstance(manifest, dict):
                    return manifest
            except Exception:
                continue
    return {}


if __name__ == "__main__":
    sys.exit(main())
