#!/usr/bin/env python3
"""Schedule or start launch execution services for one Virtuals project.

This script only manages systemd units. It does not sign, broadcast, or mutate
strategy configuration. Use --apply explicitly for systemd writes.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_UNIT_DIR = Path("/etc/systemd/system")
DEFAULT_REMOTE_DIR = Path("/opt/virtuals-whale-radar")
DEFAULT_SERVICES = ("dryrun", "prewarm", "autobuy", "autosell")
NO_TAX_PROFILE_SERVICES = ("open-sniper", "fdv-limit", "autosell")
NO_TAX_SCHEDULE_STATUSES = {"bonding_v5_anti_sniper_off", "legacy_no_anti_sniper"}
TAXED_60S_SCHEDULE_STATUSES = {"bonding_v5_60s", "x_launch_98s"}
TAXED_98M_SCHEDULE_STATUSES = {"bonding_v5_98m", "default_98m"}
SERVICE_UNIT_MAP = {
    "dryrun": "vwr-launch-dryrun@{project}.service",
    "prewarm": "vwr-launch-prewarm@{project}.service",
    "autobuy": "vwr-launch-autobuy@{project}.service",
    "autosell": "vwr-launch-autosell@{project}.service",
    "open-sniper": "vwr-launch-open-sniper@{project}.service",
    "fdv-limit": "vwr-launch-fdv-limit@{project}.service",
}
TEMPLATE_FILES = (
    "vwr-launch-dryrun@.service",
    "vwr-launch-prewarm@.service",
    "vwr-launch-autobuy@.service",
    "vwr-launch-autosell@.service",
    "vwr-launch-open-sniper@.service",
    "vwr-launch-fdv-limit@.service",
)


@dataclass(frozen=True)
class LaunchSchedule:
    project: str
    start_at: datetime
    service_at: datetime
    archive_at: datetime | None
    services: tuple[str, ...]
    unit_prefix: str
    launch_profile: dict[str, object] | None = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Schedule or start launch execution services for one project.")
    parser.add_argument("--config", default="config.json")
    parser.add_argument("--project", required=True, help="Project symbol/name, for example ROO.")
    parser.add_argument("--start-at", help="Launch start time in server local time, e.g. '2026-05-12 23:00:00'.")
    parser.add_argument("--prewarm-minutes", type=int, default=35)
    parser.add_argument("--duration-minutes", type=int, default=99)
    parser.add_argument("--archive-delay-minutes", type=int, default=10)
    parser.add_argument("--services", default="")
    parser.add_argument(
        "--auto-profile",
        action="store_true",
        help="Read the managed project and official Virtuals launchInfo, then choose the launch service profile automatically.",
    )
    parser.add_argument("--unit-dir", default=str(DEFAULT_UNIT_DIR))
    parser.add_argument("--remote-dir", default=str(DEFAULT_REMOTE_DIR))
    parser.add_argument("--apply", action="store_true", help="Write units and call systemctl. Default is dry-run.")
    parser.add_argument("--start-now", action="store_true", help="Start selected services immediately.")
    parser.add_argument("--no-archive-timer", action="store_true")
    parser.add_argument("--no-install-templates", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def sanitize_project(raw: str) -> str:
    project = str(raw or "").strip().upper()
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9_.-]{0,63}", project):
        raise ValueError("project must be 1-64 chars and contain only letters, numbers, dot, underscore, or dash")
    return project


def parse_local_datetime(raw: str) -> datetime:
    value = str(raw or "").strip()
    formats = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M")
    for fmt in formats:
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            pass
    raise ValueError("start-at must look like 'YYYY-MM-DD HH:MM[:SS]' in server local time")


def parse_services(raw: str) -> tuple[str, ...]:
    value = str(raw or "").strip() or ",".join(DEFAULT_SERVICES)
    services = tuple(item.strip().lower() for item in value.split(",") if item.strip())
    unknown = [item for item in services if item not in SERVICE_UNIT_MAP]
    if unknown:
        raise ValueError(f"unknown services: {', '.join(unknown)}")
    if not services:
        raise ValueError("at least one service is required")
    return services


def classify_launch_profile(schedule: dict[str, object]) -> str:
    if not bool(schedule.get("known")):
        return "unknown_blocked"
    status = str(schedule.get("status") or "").strip()
    if status in NO_TAX_SCHEDULE_STATUSES:
        return "no_tax_open_sniper"
    if status in TAXED_60S_SCHEDULE_STATUSES:
        return "taxed_60s"
    if status in TAXED_98M_SCHEDULE_STATUSES:
        return "taxed_98m"
    return "taxed_default"


def services_for_launch_profile(profile: str) -> tuple[str, ...]:
    if profile == "no_tax_open_sniper":
        return NO_TAX_PROFILE_SERVICES
    if profile in {"taxed_60s", "taxed_98m", "taxed_default"}:
        return DEFAULT_SERVICES
    raise ValueError(f"cannot schedule launch services for profile={profile}")


def format_local_timestamp(ts: object) -> str:
    value = int(ts or 0)
    if value <= 0:
        return ""
    return datetime.fromtimestamp(value).strftime("%Y-%m-%d %H:%M:%S")


def systemd_time(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def start_unit_name(prefix: str) -> str:
    return f"{prefix}-start.service"


def start_timer_name(prefix: str) -> str:
    return f"{prefix}-start.timer"


def archive_unit_name(prefix: str) -> str:
    return f"{prefix}-archive.service"


def archive_timer_name(prefix: str) -> str:
    return f"{prefix}-archive.timer"


def build_schedule(args: argparse.Namespace) -> LaunchSchedule:
    project = sanitize_project(args.project)
    if args.start_now:
        now = datetime.now().replace(microsecond=0)
        start_at = parse_local_datetime(args.start_at) if args.start_at else now
    else:
        if not args.start_at:
            raise ValueError("--start-at is required unless --start-now is used")
        start_at = parse_local_datetime(args.start_at)
    service_at = start_at - timedelta(minutes=max(0, int(args.prewarm_minutes)))
    archive_at = None
    if not args.no_archive_timer:
        archive_at = start_at + timedelta(minutes=max(1, int(args.duration_minutes)) + max(0, int(args.archive_delay_minutes)))
    return LaunchSchedule(
        project=project,
        start_at=start_at,
        service_at=service_at,
        archive_at=archive_at,
        services=parse_services(args.services),
        unit_prefix=f"vwr-launch-{project.lower()}",
        launch_profile=getattr(args, "launch_profile", None),
    )


def selected_service_units(schedule: LaunchSchedule) -> list[str]:
    return [SERVICE_UNIT_MAP[name].format(project=schedule.project) for name in schedule.services]


def render_start_service(schedule: LaunchSchedule) -> str:
    units = " ".join(selected_service_units(schedule))
    return f"""[Unit]
Description=Start Virtuals Whale Radar {schedule.project} launch execution services
After=network-online.target vwr@writer.service vwr@realtime.service vwr@backfill.service
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=/bin/systemctl start {units}
"""


def render_start_timer(schedule: LaunchSchedule) -> str:
    return f"""[Unit]
Description=Start {schedule.project} launch execution services {int((schedule.start_at - schedule.service_at).total_seconds() // 60)} minutes before launch

[Timer]
OnCalendar={systemd_time(schedule.service_at)}
AccuracySec=1s
Persistent=true
Unit={start_unit_name(schedule.unit_prefix)}

[Install]
WantedBy=timers.target
"""


def render_archive_service(schedule: LaunchSchedule, remote_dir: Path) -> str:
    archive_name = f"{schedule.start_at.strftime('%Y-%m-%d')}-{schedule.project}-auto"
    cmd = (
        f"{remote_dir}/.venv/bin/python {remote_dir}/scripts/ops/archive_launch_project.py "
        f"--config {remote_dir}/config.json --project {schedule.project} "
        f"--output-dir {remote_dir}/data/launch-archives --archive-name {archive_name} --overwrite"
    )
    return f"""[Unit]
Description=Archive Virtuals Whale Radar {schedule.project} launch data
After=vwr@writer.service

[Service]
Type=oneshot
User=vwr
Group=vwr
WorkingDirectory={remote_dir}
ExecStart={cmd}
"""


def render_archive_timer(schedule: LaunchSchedule) -> str:
    if schedule.archive_at is None:
        raise ValueError("archive timer requested without archive_at")
    return f"""[Unit]
Description=Archive {schedule.project} launch data after launch window

[Timer]
OnCalendar={systemd_time(schedule.archive_at)}
AccuracySec=1s
Persistent=true
Unit={archive_unit_name(schedule.unit_prefix)}

[Install]
WantedBy=timers.target
"""


def render_fdv_limit_open_sniper_gate_override(project: str, remote_dir: Path) -> str:
    template_path = ROOT / "deploy" / "systemd" / "vwr-launch-fdv-limit@.service"
    template = template_path.read_text(encoding="utf-8")
    exec_start = next((line for line in template.splitlines() if line.startswith("ExecStart=")), "")
    if not exec_start:
        raise ValueError(f"missing ExecStart in {template_path}")
    command = exec_start.removeprefix("ExecStart=").replace("--project %i", f"--project {project}")
    command = command.replace(str(DEFAULT_REMOTE_DIR), str(remote_dir))
    if "--require-open-sniper-before-fdv-limit" not in command:
        marker = " --output-jsonl "
        command = command.replace(marker, " --require-open-sniper-before-fdv-limit --output-jsonl ", 1)
    return f"""[Service]
ExecStart=
ExecStart={command}
"""


def planned_files(schedule: LaunchSchedule, unit_dir: Path, remote_dir: Path, install_templates: bool) -> dict[str, str]:
    files: dict[str, str] = {
        str(unit_dir / start_unit_name(schedule.unit_prefix)): render_start_service(schedule),
        str(unit_dir / start_timer_name(schedule.unit_prefix)): render_start_timer(schedule),
    }
    if schedule.archive_at is not None:
        files[str(unit_dir / archive_unit_name(schedule.unit_prefix))] = render_archive_service(schedule, remote_dir)
        files[str(unit_dir / archive_timer_name(schedule.unit_prefix))] = render_archive_timer(schedule)
    if install_templates:
        template_dir = ROOT / "deploy" / "systemd"
        for name in TEMPLATE_FILES:
            files[str(unit_dir / name)] = (template_dir / name).read_text(encoding="utf-8")
    if "open-sniper" in schedule.services and "fdv-limit" in schedule.services:
        files[
            str(
                unit_dir
                / f"vwr-launch-fdv-limit@{schedule.project}.service.d"
                / "10-require-open-sniper.conf"
            )
        ] = render_fdv_limit_open_sniper_gate_override(schedule.project, remote_dir)
    return files


def run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True)


def write_files(files: dict[str, str]) -> None:
    for raw_path, body in files.items():
        path = Path(raw_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")


def systemctl_enable_start(schedule: LaunchSchedule, start_now: bool) -> list[list[str]]:
    commands: list[list[str]] = [["systemctl", "daemon-reload"]]
    timers = [start_timer_name(schedule.unit_prefix)]
    if schedule.archive_at is not None:
        timers.append(archive_timer_name(schedule.unit_prefix))
    for timer in timers:
        commands.append(["systemctl", "enable", "--now", timer])
    if start_now:
        commands.append(["systemctl", "start", *selected_service_units(schedule)])
    return commands


def emit_plan(args: argparse.Namespace, schedule: LaunchSchedule, files: dict[str, str], commands: Iterable[list[str]]) -> None:
    payload = {
        "apply": bool(args.apply),
        "project": schedule.project,
        "startAt": systemd_time(schedule.start_at),
        "serviceAt": systemd_time(schedule.service_at),
        "archiveAt": systemd_time(schedule.archive_at) if schedule.archive_at else None,
        "services": list(schedule.services),
        "launchProfile": schedule.launch_profile,
        "serviceUnits": selected_service_units(schedule),
        "unitFiles": list(files.keys()),
        "commands": [" ".join(cmd) for cmd in commands],
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(payload, ensure_ascii=False))


async def resolve_auto_profile(args: argparse.Namespace) -> dict[str, object]:
    if str(args.services or "").strip():
        raise ValueError("--auto-profile cannot be combined with --services")
    from live_strategy_dry_run import find_project  # noqa: PLC0415
    from virtuals_bot import VirtualsBot, load_config  # noqa: PLC0415

    cfg = load_config(args.config)
    cfg.bootstrap_admin_email = None
    cfg.bootstrap_admin_password = None
    cfg.email_enabled = False
    async with VirtualsBot(cfg, role="backfill") as bot:
        project_row = find_project(bot, str(args.project))
        project_name = sanitize_project(str(project_row.get("name") or args.project))
        signalhub_project_id = str(project_row.get("signalhub_project_id") or "").strip()
        if not signalhub_project_id:
            raise ValueError(f"managed project {project_name} missing signalhub_project_id")
        virtuals_data = await bot.fetch_virtuals_launch_info(signalhub_project_id)
        launch_info = virtuals_data.get("launchInfo") if isinstance(virtuals_data.get("launchInfo"), dict) else {}
        schedule = bot.resolve_buy_tax_schedule(
            factory=virtuals_data.get("factory"),
            category=virtuals_data.get("category"),
            anti_sniper_tax_type=launch_info.get("antiSniperTaxType"),
            is_project_60days=launch_info.get("isProject60days"),
        )
        profile = classify_launch_profile(schedule)
        services = services_for_launch_profile(profile)
        start_at_source = "cli_start_at" if args.start_at else "managed_project_start_at"
        if not args.start_at and not args.start_now:
            start_at = format_local_timestamp(project_row.get("start_at"))
            if not start_at:
                raise ValueError(f"managed project {project_name} missing start_at; pass --start-at explicitly")
            args.start_at = start_at
        args.project = project_name
        args.services = ",".join(services)
        return {
            "profile": profile,
            "services": list(services),
            "project": project_name,
            "managedProjectId": int(project_row.get("id") or 0),
            "signalhubProjectId": signalhub_project_id,
            "official": {
                "factory": virtuals_data.get("factory"),
                "category": virtuals_data.get("category"),
                "antiSniperTaxType": launch_info.get("antiSniperTaxType"),
                "isProject60days": launch_info.get("isProject60days"),
                "launchedAt": virtuals_data.get("launchedAt"),
            },
            "taxSchedule": schedule,
            "startAtSource": start_at_source,
        }


async def async_main() -> int:
    args = parse_args()
    try:
        if args.auto_profile:
            args.launch_profile = await resolve_auto_profile(args)
        else:
            args.launch_profile = None
        schedule = build_schedule(args)
        unit_dir = Path(args.unit_dir)
        remote_dir = Path(args.remote_dir)
        files = planned_files(
            schedule=schedule,
            unit_dir=unit_dir,
            remote_dir=remote_dir,
            install_templates=not args.no_install_templates,
        )
        commands = systemctl_enable_start(schedule, start_now=bool(args.start_now))
        emit_plan(args, schedule, files, commands)
        if args.apply:
            write_files(files)
            for cmd in commands:
                run(cmd)
        return 0
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


def main() -> None:
    raise SystemExit(asyncio.run(async_main()))


if __name__ == "__main__":
    main()
