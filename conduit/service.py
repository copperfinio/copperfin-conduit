"""Service install helpers for Conduit."""

from __future__ import annotations

import platform
import subprocess
import sys
from pathlib import Path

from .paths import conduit_home

SERVICE_NAME = "Conduit"
SERVICE_ID = "conduit"


def service_command(
    *,
    host: str,
    port: int,
    dashboard: bool = True,
    dashboard_port: int = 20130,
) -> list[str]:
    """Return the Python command used by service managers."""
    command = [
        sys.executable,
        "-m",
        "conduit.cli",
        "start",
        "--foreground",
        "--host",
        host,
        "--port",
        str(port),
        "--dashboard-port",
        str(dashboard_port),
    ]
    command.append("--dashboard" if dashboard else "--no-dashboard")
    return command


def install_service(
    *,
    host: str,
    port: int,
    dry_run: bool = False,
    start: bool = True,
    dashboard: bool = True,
    dashboard_port: int = 20130,
) -> list[str]:
    """Install Conduit as the best native user service for this platform."""
    system = platform.system().lower()
    if system == "linux":
        return install_systemd_user_service(
            host=host,
            port=port,
            dry_run=dry_run,
            start=start,
            dashboard=dashboard,
            dashboard_port=dashboard_port,
        )
    if system == "windows":
        return install_windows_task(
            host=host,
            port=port,
            dry_run=dry_run,
            start=start,
            dashboard=dashboard,
            dashboard_port=dashboard_port,
        )
    raise RuntimeError(f"Service install is not supported on {platform.system()}.")


def uninstall_service(*, dry_run: bool = False) -> list[str]:
    """Uninstall Conduit service integration."""
    system = platform.system().lower()
    if system == "linux":
        commands = [
            "systemctl --user disable --now conduit.service",
            "remove ~/.config/systemd/user/conduit.service",
            "systemctl --user daemon-reload",
        ]
        if dry_run:
            return commands
        subprocess.run(
            ["systemctl", "--user", "disable", "--now", "conduit.service"], check=False
        )
        service_file = Path.home() / ".config" / "systemd" / "user" / "conduit.service"
        service_file.unlink(missing_ok=True)
        subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)
        return commands
    if system == "windows":
        commands = [r"schtasks /Delete /TN Conduit /F"]
        if dry_run:
            return commands
        subprocess.run(
            ["schtasks.exe", "/Delete", "/TN", SERVICE_NAME, "/F"], check=False
        )
        return commands
    raise RuntimeError(f"Service uninstall is not supported on {platform.system()}.")


def service_status() -> int:
    """Print service status and return process exit code."""
    system = platform.system().lower()
    if system == "linux":
        return subprocess.call(["systemctl", "--user", "status", "conduit.service"])
    if system == "windows":
        return subprocess.call(
            ["schtasks.exe", "/Query", "/TN", SERVICE_NAME, "/V", "/FO", "LIST"]
        )
    raise RuntimeError(f"Service status is not supported on {platform.system()}.")


def install_systemd_user_service(
    *,
    host: str,
    port: int,
    dry_run: bool,
    start: bool,
    dashboard: bool = True,
    dashboard_port: int = 20130,
) -> list[str]:
    """Install a Linux systemd user service."""
    unit_dir = Path.home() / ".config" / "systemd" / "user"
    unit_file = unit_dir / "conduit.service"
    command = " ".join(
        shell_quote(arg)
        for arg in service_command(
            host=host,
            port=port,
            dashboard=dashboard,
            dashboard_port=dashboard_port,
        )
    )
    unit = f"""[Unit]
Description=Conduit AI subscription proxy
After=network-online.target

[Service]
Type=simple
Environment=CONDUIT_HOME={conduit_home()}
ExecStart={command}
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
"""
    commands = [
        f"write {unit_file}",
        "systemctl --user daemon-reload",
        "systemctl --user enable conduit.service",
    ]
    if start:
        commands.append("systemctl --user start conduit.service")
    if dry_run:
        return commands
    unit_dir.mkdir(parents=True, exist_ok=True)
    unit_file.write_text(unit, encoding="utf-8")
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "--user", "enable", "conduit.service"], check=True)
    if start:
        subprocess.run(["systemctl", "--user", "start", "conduit.service"], check=True)
    return commands


def install_windows_task(
    *,
    host: str,
    port: int,
    dry_run: bool,
    start: bool,
    dashboard: bool = True,
    dashboard_port: int = 20130,
) -> list[str]:
    """Install a Windows logon task that runs Conduit.

    A plain Python process is not a native Windows Service process. Task Scheduler
    is the honest no-wrapper option until Conduit ships a Windows service wrapper.
    """
    command = subprocess.list2cmdline(
        service_command(
            host=host,
            port=port,
            dashboard=dashboard,
            dashboard_port=dashboard_port,
        )
    )
    create = [
        "schtasks.exe",
        "/Create",
        "/TN",
        SERVICE_NAME,
        "/SC",
        "ONLOGON",
        "/TR",
        command,
        "/F",
    ]
    commands = [subprocess.list2cmdline(create)]
    if start:
        commands.append(
            subprocess.list2cmdline(["schtasks.exe", "/Run", "/TN", SERVICE_NAME])
        )
    if dry_run:
        return commands
    subprocess.run(create, check=True)
    if start:
        subprocess.run(["schtasks.exe", "/Run", "/TN", SERVICE_NAME], check=True)
    return commands


def shell_quote(value: str) -> str:
    """Quote a shell argument for systemd ExecStart."""
    if not value or any(ch.isspace() for ch in value):
        return "'" + value.replace("'", "'\\''") + "'"
    return value
