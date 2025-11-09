from __future__ import annotations

from pathlib import Path

from ui_testing.tools.calibration import (
    CalibrationProfile,
    calibration_dir,
    compute_offset,
    list_profiles,
    load_profile,
    save_profile,
)


def test_calibration_profile_round_trip(tmp_path: Path) -> None:
    profile = CalibrationProfile(name="default", anchor_x=100, anchor_y=200, width=1280, height=720)
    path = save_profile(tmp_path, profile)
    assert path.exists()

    loaded = load_profile(tmp_path, "default")
    assert loaded is not None
    assert loaded.anchor_x == 100
    assert loaded.anchor_y == 200
    assert loaded.width == 1280
    assert loaded.height == 720

    dx, dy = compute_offset(loaded, (110, 190))
    assert dx == 10
    assert dy == -10


def test_list_profiles(tmp_path: Path) -> None:
    calibration_dir(tmp_path)
    profile_a = CalibrationProfile(name="profile_a", anchor_x=0, anchor_y=0)
    profile_b = CalibrationProfile(name="profile_b", anchor_x=10, anchor_y=10)
    save_profile(tmp_path, profile_a)
    save_profile(tmp_path, profile_b)

    profiles = list_profiles(tmp_path)
    assert profiles == ["profile_a", "profile_b"]
