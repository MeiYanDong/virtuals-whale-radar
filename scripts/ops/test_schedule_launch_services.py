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
    classify_launch_profile,
    format_local_timestamp,
    planned_files,
    selected_service_units,
    services_for_launch_profile,
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


def test_open_sniper_schedule_adds_fdv_limit_gate_override() -> None:
    args = Namespace(
        project="orion",
        start_at="2026-05-26 00:00:54",
        prewarm_minutes=30,
        duration_minutes=99,
        archive_delay_minutes=10,
        services="open-sniper,fdv-limit",
        no_archive_timer=False,
        start_now=False,
    )
    schedule = build_schedule(args)
    files = planned_files(schedule, Path("/tmp/systemd"), Path("/opt/virtuals-whale-radar"), install_templates=True)
    override_path = "/tmp/systemd/vwr-launch-fdv-limit@ORION.service.d/10-require-open-sniper.conf"
    assert override_path in files
    assert "--require-open-sniper-before-fdv-limit" in files[override_path]
    assert "--project ORION" in files[override_path]


def test_launch_profile_classifier_and_services() -> None:
    assert_eq(
        classify_launch_profile({"known": True, "status": "bonding_v5_anti_sniper_off"}),
        "no_tax_open_sniper",
        "no-tax bonding v5 profile",
    )
    assert_eq(
        services_for_launch_profile("no_tax_open_sniper"),
        ("open-sniper", "fdv-limit", "autosell"),
        "no-tax services",
    )
    assert_eq(classify_launch_profile({"known": True, "status": "bonding_v5_60s"}), "taxed_60s", "60s profile")
    assert_eq(classify_launch_profile({"known": True, "status": "bonding_v5_98m"}), "taxed_98m", "98m profile")
    assert_eq(services_for_launch_profile("taxed_98m"), ("dryrun", "prewarm", "autobuy", "autosell"), "taxed services")
    assert_eq(classify_launch_profile({"known": False, "status": "official_config_missing"}), "unknown_blocked", "unknown profile")
    try:
        services_for_launch_profile("unknown_blocked")
    except ValueError:
        pass
    else:
        raise AssertionError("unknown profile should not schedule services")
    assert format_local_timestamp(1779724854)


def main() -> None:
    test_schedule_units()
    test_start_now_without_start_at()
    test_open_sniper_schedule_adds_fdv_limit_gate_override()
    test_launch_profile_classifier_and_services()
    print("schedule_launch_services tests ok")


if __name__ == "__main__":
    main()
