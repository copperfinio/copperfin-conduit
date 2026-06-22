"""Conduit command-line interface."""

from __future__ import annotations

import os
import platform
import shutil
import socket
import stat
import subprocess
import sys
import tarfile
import threading
import time
import urllib.request
from pathlib import Path

import click
import requests

from . import __version__, anthropic_auth
from .auth import (
    ConduitAuthError,
    auth_status,
    import_codex_auth,
    login_browser,
    login_device,
)
from .auth import logout as auth_logout
from .auth import (
    refresh_auth,
)
from .envfile import apply_env, ensure_env_file, load_env, service_key
from .paths import (
    anthropic_auth_path,
    auth_path,
    conduit_home,
    ensure_conduit_home,
    logs_dir,
    run_dir,
    tools_dir,
)
from .service import install_service, service_status, uninstall_service
from .smoke import run_smoke

AUTH_PROVIDER_CHOICE = click.Choice(["codex", "anthropic", "claude"])


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(__version__, prog_name="conduit")
def cli() -> None:
    """Use your AI subscriptions like an API."""


@cli.command()
@click.option("--force", is_flag=True, help="Overwrite ~/.conduit/.env.")
def init(force: bool) -> None:
    """Create Conduit's user config directory."""
    home = ensure_conduit_home()
    env_file = ensure_env_file(force=force, home=home)
    click.echo(f"Conduit home: {home}")
    click.echo(f"Config:       {env_file}")
    click.echo(f"Codex auth:   {auth_path(home)}")
    click.echo(f"Claude auth:  {anthropic_auth_path(home)}")
    click.echo(f"API key:      {service_key(home=home)}")


@cli.group()
def auth() -> None:
    """Manage subscription auth."""


@auth.command("login")
@click.option(
    "--provider",
    type=AUTH_PROVIDER_CHOICE,
    default="codex",
    show_default=True,
    help="Subscription provider to authenticate.",
)
@click.option(
    "--method",
    type=click.Choice(["browser", "device"]),
    default="browser",
    show_default=True,
    help="OAuth login method.",
)
@click.option("--no-browser", is_flag=True, help="Do not open a browser automatically.")
def auth_login(provider: str, method: str, no_browser: bool) -> None:
    """Authenticate Conduit to a subscription provider."""
    ensure_env_file()
    normalized = normalize_auth_provider(provider)
    try:
        if normalized == "anthropic":
            if method == "device":
                raise ConduitAuthError(
                    "Anthropic OAuth does not provide a device-code flow here. "
                    "Use --method browser."
                )
            token = anthropic_auth.login_browser(open_browser=not no_browser)
            click.echo("Authenticated.")
            click.echo(f"Expires: {format_epoch_ms(token.expires)}")
            click.echo(f"Saved:   {anthropic_auth_path()}")
            return
        if method == "device":
            credentials = login_device(open_browser=not no_browser)
        else:
            credentials = login_browser(open_browser=not no_browser)
    except ConduitAuthError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo("Authenticated.")
    click.echo(f"Account: {credentials.account_id}")
    click.echo(f"Saved:   {auth_path()}")


@auth.command("status")
@click.option(
    "--provider",
    type=AUTH_PROVIDER_CHOICE,
    default="codex",
    show_default=True,
    help="Subscription provider to inspect.",
)
def auth_status_command(provider: str) -> None:
    """Show current auth status."""
    normalized = normalize_auth_provider(provider)
    status = (
        anthropic_auth.auth_status() if normalized == "anthropic" else auth_status()
    )
    click.echo(f"Auth path: {status['path']}")
    if not status["authenticated"]:
        click.echo("Status:    not authenticated")
        if status.get("error"):
            click.echo(f"Error:     {status['error']}")
        return
    click.echo("Status:    authenticated")
    if status.get("account_id"):
        click.echo(f"Account:   {status.get('account_id')}")
    if status.get("expires"):
        click.echo(f"Expires:   {format_epoch_ms(int(status['expires']))}")
    click.echo(f"Expired:   {status.get('expired')}")


@auth.command("refresh")
@click.option(
    "--provider",
    type=AUTH_PROVIDER_CHOICE,
    default="codex",
    show_default=True,
    help="Subscription provider to refresh.",
)
def auth_refresh_command(provider: str) -> None:
    """Refresh a stored access token."""
    normalized = normalize_auth_provider(provider)
    try:
        if normalized == "anthropic":
            token = anthropic_auth.refresh_auth()
            click.echo("Refreshed.")
            click.echo(f"Expires: {format_epoch_ms(token.expires)}")
            return
        credentials = refresh_auth()
    except ConduitAuthError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo("Refreshed.")
    click.echo(f"Account: {credentials.account_id}")


@auth.command("logout")
@click.option(
    "--provider",
    type=AUTH_PROVIDER_CHOICE,
    default="codex",
    show_default=True,
    help="Subscription provider to log out.",
)
def auth_logout_command(provider: str) -> None:
    """Delete Conduit's stored auth state."""
    normalized = normalize_auth_provider(provider)
    removed = anthropic_auth.logout() if normalized == "anthropic" else auth_logout()
    click.echo("Logged out." if removed else "No auth state found.")


@auth.command("import-codex")
@click.option(
    "--source",
    type=click.Path(path_type=Path),
    default=Path.home() / ".codex" / "auth.json",
    show_default=True,
    help="Existing Codex CLI auth file.",
)
def auth_import_codex(source: Path) -> None:
    """Import an existing Codex CLI login into ~/.conduit."""
    try:
        import_codex_auth(source=source)
    except ConduitAuthError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"Imported {source} -> {auth_path()}")


@cli.command()
@click.option("--host", default="127.0.0.1", show_default=True)
@click.option("--port", default=20129, show_default=True, type=int)
@click.option("--foreground", is_flag=True, help="Run in the foreground.")
@click.option("--background", is_flag=True, help="Run in the background.")
@click.option("--wait/--no-wait", default=True, show_default=True)
@click.option(
    "--dashboard/--no-dashboard",
    default=True,
    show_default=True,
    help="Run the unauthenticated local-only telemetry dashboard alongside the proxy.",
)
@click.option(
    "--dashboard-port",
    default=None,
    type=int,
    help="Localhost port for the telemetry dashboard; defaults to DASHBOARD_PORT or 20130.",
)
def start(
    host: str,
    port: int,
    foreground: bool,
    background: bool,
    wait: bool,
    dashboard: bool,
    dashboard_port: int | None,
) -> None:
    """Start the local Conduit proxy."""
    if foreground and background:
        raise click.ClickException("Use either --foreground or --background, not both.")
    if background:
        start_background(
            host=host,
            port=port,
            wait=wait,
            dashboard=dashboard,
            dashboard_port=dashboard_port,
        )
        return
    run_foreground(
        host=host,
        port=port,
        dashboard=dashboard,
        dashboard_port=dashboard_port,
    )


@cli.command()
@click.option("--port", default=20129, show_default=True, type=int)
def stop(port: int) -> None:
    """Stop a Conduit process started with --background."""
    pid_file = run_dir() / f"conduit_{port}.pid"
    if not pid_file.exists():
        click.echo("No background pid file found.")
        return
    pid = int(pid_file.read_text(encoding="utf-8").strip())
    try:
        terminate_pid(pid)
    except OSError as exc:
        raise click.ClickException(f"Could not stop process {pid}: {exc}") from exc
    pid_file.unlink(missing_ok=True)
    click.echo(f"Stopped pid {pid}.")


@cli.command()
@click.option("--root-url", default="http://127.0.0.1:20129", show_default=True)
@click.option("--model", default="gpt-5.4-mini", show_default=True)
@click.option("--api-key", default="", help="Override SERVICE_API_KEY.")
@click.option("--cache-probe", is_flag=True, help="Verify prompt-cache hit reporting.")
def smoke(root_url: str, model: str, api_key: str, cache_probe: bool) -> None:
    """Run proxy health, streaming, tool, and optional cache probes."""
    try:
        for line in run_smoke(
            root_url=root_url,
            model=model,
            api_key=api_key or None,
            cache_probe=cache_probe,
        ):
            click.echo(line)
    except Exception as exc:  # noqa: B902
        raise click.ClickException(str(exc)) from exc


@cli.command()
@click.option("--root-url", default="http://127.0.0.1:20129/codex", show_default=True)
@click.option("--api-key", default="", help="Override SERVICE_API_KEY.")
def models(root_url: str, api_key: str) -> None:
    """List models exposed by Conduit."""
    key = api_key or service_key()
    if not key:
        raise click.ClickException("SERVICE_API_KEY is not configured.")
    url = root_url.rstrip("/") + "/v1/models"
    response = requests.get(url, headers={"Authorization": f"Bearer {key}"}, timeout=10)
    if response.status_code != 200:
        raise click.ClickException(f"HTTP {response.status_code}: {response.text}")
    for item in response.json().get("data", []):
        model_id = item.get("id")
        if model_id:
            click.echo(model_id)


@cli.command()
@click.option("--host", default="127.0.0.1", show_default=True)
@click.option("--port", default=20129, show_default=True, type=int)
@click.option(
    "--install-cloudflared", is_flag=True, help="Install cloudflared if missing."
)
def tunnel(host: str, port: int, install_cloudflared: bool) -> None:
    """Start a Cloudflare Quick Tunnel to the local proxy."""
    cloudflared = find_cloudflared()
    if cloudflared is None and install_cloudflared:
        cloudflared = install_cloudflared_binary()
    if cloudflared is None:
        raise click.ClickException(
            "cloudflared was not found. Install it or rerun with --install-cloudflared."
        )
    click.echo("Starting Cloudflare Quick Tunnel.")
    click.echo("Use /codex for OpenAI-compatible Codex or /anthropic for Claude.")
    raise SystemExit(
        subprocess.call([str(cloudflared), "tunnel", "--url", f"http://{host}:{port}"])
    )


@cli.command()
@click.option("--host", default="127.0.0.1", show_default=True)
@click.option("--port", default=20129, show_default=True, type=int)
def doctor(host: str, port: int) -> None:
    """Check local Conduit configuration."""
    ensure_env_file()
    click.echo(f"Conduit:      {__version__}")
    click.echo(f"Python:       {sys.version.split()[0]} ({sys.executable})")
    click.echo(f"OS:           {platform.platform()}")
    click.echo(f"Home:         {conduit_home()}")
    click.echo(f"Config:       {conduit_home() / '.env'}")
    click.echo(f"Codex auth:   {auth_path()}")
    click.echo(f"Codex status: {'ok' if auth_status()['authenticated'] else 'missing'}")
    click.echo(f"Claude auth:  {anthropic_auth_path()}")
    claude_status = anthropic_auth.auth_status()
    click.echo(
        f"Claude status:{' ok' if claude_status['authenticated'] else ' missing'}"
    )
    click.echo(f"Service key:  {'set' if service_key() else 'missing'}")
    click.echo(f"cloudflared:  {find_cloudflared() or 'missing'}")
    click.echo(f"Listening:    {is_listening(host, port)} ({host}:{port})")
    if is_listening(host, port):
        try:
            response = requests.get(f"http://{host}:{port}/health", timeout=3)
            click.echo(f"Health:       HTTP {response.status_code} {response.text}")
        except requests.RequestException as exc:
            click.echo(f"Health:       failed: {exc}")


@cli.group()
def service() -> None:
    """Install or manage Conduit's local service integration."""


@service.command("install")
@click.option("--host", default="127.0.0.1", show_default=True)
@click.option("--port", default=20129, show_default=True, type=int)
@click.option("--dry-run", is_flag=True, help="Print actions without applying them.")
@click.option("--start/--no-start", default=True, show_default=True)
@click.option(
    "--dashboard/--no-dashboard",
    default=True,
    show_default=True,
    help="Launch the unauthenticated local-only dashboard with the service.",
)
@click.option("--dashboard-port", default=20130, show_default=True, type=int)
def service_install_command(
    host: str,
    port: int,
    dry_run: bool,
    start: bool,
    dashboard: bool,
    dashboard_port: int,
) -> None:
    """Install Conduit for startup."""
    ensure_env_file()
    try:
        commands = install_service(
            host=host,
            port=port,
            dry_run=dry_run,
            start=start,
            dashboard=dashboard,
            dashboard_port=dashboard_port,
        )
    except Exception as exc:  # noqa: B902
        raise click.ClickException(str(exc)) from exc
    for command in commands:
        click.echo(command)


@service.command("uninstall")
@click.option("--dry-run", is_flag=True, help="Print actions without applying them.")
def service_uninstall_command(dry_run: bool) -> None:
    """Uninstall Conduit's service integration."""
    try:
        commands = uninstall_service(dry_run=dry_run)
    except Exception as exc:  # noqa: B902
        raise click.ClickException(str(exc)) from exc
    for command in commands:
        click.echo(command)


@service.command("status")
def service_status_command() -> None:
    """Show service status."""
    raise SystemExit(service_status())


def run_foreground(
    *,
    host: str,
    port: int,
    dashboard: bool = True,
    dashboard_port: int | None = None,
) -> None:
    """Run Flask in the current process."""
    ensure_env_file()
    values = load_env()
    apply_env(values)
    resolved_dashboard_port = resolve_dashboard_port(dashboard_port)
    from app import create_app

    app = create_app()
    if dashboard:
        start_dashboard_thread(port=resolved_dashboard_port)
        click.echo(
            f"Dashboard listening on http://127.0.0.1:{resolved_dashboard_port}/dashboard/"
        )
    click.echo(f"Conduit listening on http://{host}:{port}")
    app.run(host=host, port=port, debug=False, use_reloader=False, threaded=True)


def start_dashboard_thread(*, port: int) -> None:
    """Start the unauthenticated local-only dashboard server in a daemon thread."""
    if is_listening("127.0.0.1", port):
        click.echo(f"Dashboard port {port} already in use; skipping dashboard.")
        return
    from app.dashboard.app import create_dashboard_app

    dashboard_app = create_dashboard_app()

    def serve() -> None:
        dashboard_app.run(
            host="127.0.0.1",
            port=port,
            debug=False,
            use_reloader=False,
            threaded=True,
        )

    thread = threading.Thread(target=serve, name="conduit-dashboard", daemon=True)
    thread.start()


def start_background(
    *,
    host: str,
    port: int,
    wait: bool,
    dashboard: bool = True,
    dashboard_port: int | None = None,
) -> None:
    """Start Conduit in a background process."""
    ensure_env_file()
    values = load_env()
    apply_env(values)
    resolved_dashboard_port = resolve_dashboard_port(dashboard_port)
    if is_listening(host, port):
        click.echo(f"Conduit is already listening on {host}:{port}.")
        return
    home = ensure_conduit_home()
    out_log = logs_dir(home) / f"conduit_{port}.out.log"
    err_log = logs_dir(home) / f"conduit_{port}.err.log"
    command = [
        sys.executable,
        "-u",
        "-m",
        "conduit.cli",
        "start",
        "--foreground",
        "--host",
        host,
        "--port",
        str(port),
        "--dashboard-port",
        str(resolved_dashboard_port),
    ]
    command.append("--dashboard" if dashboard else "--no-dashboard")
    env = os.environ.copy()
    env["CONDUIT_HOME"] = str(home)
    env["PYTHONUNBUFFERED"] = "1"
    process = subprocess.Popen(
        command,
        stdout=out_log.open("ab"),
        stderr=err_log.open("ab"),
        env=env,
        creationflags=windows_no_window_flags(),
    )
    (run_dir(home) / f"conduit_{port}.pid").write_text(
        str(process.pid), encoding="utf-8"
    )
    click.echo(f"Started Conduit pid {process.pid}.")
    click.echo(f"Logs: {out_log}")
    click.echo(f"Logs: {err_log}")
    if wait:
        wait_for_health(host, port)
        click.echo(f"Health: http://{host}:{port}/health")


def resolve_dashboard_port(dashboard_port: int | None) -> int:
    """Resolve dashboard port from CLI, env, or the built-in default."""
    if dashboard_port is not None:
        return validate_port(dashboard_port, source="--dashboard-port")
    raw = os.environ.get("DASHBOARD_PORT", "").strip()
    if not raw:
        return 20130
    try:
        return validate_port(int(raw), source="DASHBOARD_PORT")
    except ValueError as exc:
        raise click.ClickException("DASHBOARD_PORT must be an integer.") from exc


def validate_port(port: int, *, source: str) -> int:
    """Validate a TCP port number from CLI or environment."""
    if port < 1 or port > 65535:
        raise click.ClickException(f"{source} must be between 1 and 65535.")
    return port


def is_listening(host: str, port: int) -> bool:
    """Return whether host:port accepts TCP connections."""
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


def wait_for_health(host: str, port: int) -> None:
    """Wait for the Flask health endpoint."""
    url = f"http://{host}:{port}/health"
    for _ in range(60):
        try:
            response = requests.get(url, timeout=2)
            response.raise_for_status()
            return
        except requests.RequestException:
            time.sleep(0.5)
    raise click.ClickException(f"Conduit did not become healthy at {url}")


def normalize_auth_provider(provider: str) -> str:
    """Normalize provider aliases used by the auth CLI."""
    return "anthropic" if provider in {"anthropic", "claude"} else "codex"


def format_epoch_ms(value: int) -> str:
    """Format a millisecond epoch without exposing token material."""
    if value <= 0:
        return "unknown"
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(value / 1000))


def terminate_pid(pid: int) -> None:
    """Terminate a process by PID."""
    if os.name == "nt":
        subprocess.run(["taskkill.exe", "/PID", str(pid), "/T", "/F"], check=True)
        return
    os.kill(pid, 15)


def windows_no_window_flags() -> int:
    """Return subprocess flags that hide Windows helper windows."""
    return getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0


def find_cloudflared() -> Path | None:
    """Find cloudflared on PATH or in Conduit's tools directory."""
    local_name = "cloudflared.exe" if os.name == "nt" else "cloudflared"
    local = tools_dir() / local_name
    if local.exists():
        return local
    found = shutil.which("cloudflared")
    return Path(found) if found else None


def install_cloudflared_binary() -> Path:
    """Install cloudflared into ~/.conduit/tools."""
    tools = tools_dir()
    tools.mkdir(parents=True, exist_ok=True)
    url, target = cloudflared_download()
    click.echo(f"Downloading cloudflared from {url}")
    download = target.with_suffix(target.suffix + ".download")
    urllib.request.urlretrieve(url, download)
    if url.endswith(".tgz"):
        with tarfile.open(download, "r:gz") as archive:
            member = next(
                item
                for item in archive.getmembers()
                if Path(item.name).name == "cloudflared"
            )
            member.name = "cloudflared"
            archive.extract(member, tools)
        download.unlink()
    else:
        download.replace(target)
    target.chmod(target.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return target


def cloudflared_download() -> tuple[str, Path]:
    """Return cloudflared download URL and local target path."""
    machine = platform.machine().lower()
    system = platform.system().lower()
    arch = "arm64" if machine in {"arm64", "aarch64"} else "amd64"
    base = "https://github.com/cloudflare/cloudflared/releases/latest/download"
    tools = tools_dir()
    if system == "windows":
        if arch != "amd64":
            raise click.ClickException(
                "Automatic cloudflared install only supports Windows amd64."
            )
        return f"{base}/cloudflared-windows-amd64.exe", tools / "cloudflared.exe"
    if system == "linux":
        return f"{base}/cloudflared-linux-{arch}", tools / "cloudflared"
    if system == "darwin":
        return f"{base}/cloudflared-darwin-{arch}.tgz", tools / "cloudflared"
    raise click.ClickException(
        f"Unsupported OS for automatic cloudflared install: {system}"
    )


def main() -> None:
    """Entrypoint for python -m conduit.cli."""
    cli()


if __name__ == "__main__":
    main()
