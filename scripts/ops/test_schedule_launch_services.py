#!/usr/bin/env python3
"""Smoke tests for schedule_launch_services.py."""

from __future__ import annotations

import sys
from argparse import Namespace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OPS_DIR = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(OPS_DIR) not in sys.path:
    sys.path.insert(0, str(OPS_DIR))

from schedule_launch_services import (  # noqa: E402
    archive_timer_name,
    build_schedule,
    planned_files,
    selected_service_units,
    start_timer_name,
)


def assert_eq(actual, expected, label: str) -> None:
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def test_schedule_units() -> None:
    args = Namespace(
        project="roo",
        start_at="2026-05-12 23:00:00",
        prewarm_minutes=35,
        duration_minutes=99,
        archive_delay_minutes=10,
        services="dryrun,prewarm,autobuy,autosell",
        no_archive_timer=False,
        start_now=False,
    )
    schedule = build_schedule(args)
    assert_eq(schedule.project, "ROO", "project normalized")
    assert_eq(str(schedule.service_at), "2026-05-12 22:25:00", "service at")
    assert_eq(str(schedule.archive_at), "2026-05-13 00:49:00", "archive at")
    assert_eq(start_timer_name(schedule.unit_prefix), "vwr-launch-roo-start.timer", "start timer")
    assert_eq(archive_timer_name(schedule.unit_prefix), "vwr-launch-roo-archive.timer", "archive timer")
    assert_eq(
        selected_service_units(schedule),
        [
            "vwr-launch-dryrun@ROO.service",
            "vwr-launch-prewarm@ROO.service",
            "vwr-launch-autobuy@ROO.service",
            "vwr-launch-autosell@ROO.service",
        ],
        "selected units",
    )
    files = planned_files(schedule, Path("/tmp/systemd"), Path("/opt/virtuals-whale-radar"), install_templates=True)
    joined = "\n".join(files.values())
    assert "launch-samples-%i.jsonl" in joined
    assert "archive_launch_project.py" in joined
    assert "/bin/systemctl start vwr-launch-dryrun@ROO.service" in joined


def test_start_now_without_start_at() -> None:
    args = Namespace(
        project="abc",
        start_at=None,
        prewarm_minutes=35,
        duration_minutes=99,
        archive_delay_minutes=10,
        services="dryrun",
        no_archive_timer=True,
        start_now=True,
    )
    schedule = build_schedule(args)
    assert_eq(schedule.project, "ABC", "start-now project")
    assert_eq(schedule.archive_at, None, "no archive")
    assert_eq(selected_service_units(schedule), ["vwr-launch-dryrun@ABC.service"], "start-now units")


def main() -> None:
    test_schedule_units()
    test_start_now_without_start_at()
    print("schedule_launch_services tests ok")


if __name__ == "__main__":
    main()
