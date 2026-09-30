#!/usr/bin/env python3
"""vibedom CLI - Secure AI agent sandbox."""

import os
import shutil
import signal as signal_module
import sys
import subprocess
import click
from pathlib import Path
from typing import Optional
from vibedom.ssh_keys import generate_deploy_key, get_public_key
from vibedom.gitleaks import scan_workspace
from vibedom.review_ui import review_findings
from vibedom.whitelist import create_default_whitelist
from vibedom.vm import VMManager, parse_apple_inspect_status
from vibedom.project_config import ProjectConfig
from vibedom.proxy import ProxyManager
from vibedom.container_state import ContainerState, ContainerRegistry


@click.group()
@click.version_option()
def main():
    """Secure AI agent sandbox for running Claude Code and OpenCode."""
    pass

@main.command()
@click.option('--runtime', '-r', type=click.Choice(['auto', 'docker', 'apple'],
              case_sensitive=False), default='auto',
              help='Container runtime to use for building the image (default: auto-detect)')
def init(runtime: str):
    """Initialize vibedom (first-time setup)."""
    click.echo("🔧 Initializing vibedom...")

    # Create config directory
    config_dir = Path.home() / '.vibedom'
    keys_dir = config_dir / 'keys'
    keys_dir.mkdir(parents=True, exist_ok=True)

    # Generate deploy key
    key_path = keys_dir / 'id_ed25519_vibedom'
    if key_path.exists():
        click.echo(f"✓ Deploy key already exists at {key_path}")
    else:
        click.echo("Generating SSH deploy key...")
        generate_deploy_key(key_path)
        click.echo(f"✓ Deploy key created at {key_path}")

    # Show public key
    pubkey = get_public_key(key_path)
    click.echo("\n" + "="*60)
    click.echo("📋 Add this public key to your GitLab account:")
    click.echo("   Settings → SSH Keys")
    click.echo("="*60)
    click.echo(pubkey)
    click.echo("="*60 + "\n")

    # Create whitelist
    click.echo("Creating network whitelist...")
    whitelist_path = create_default_whitelist(config_dir)
    click.echo(f"✓ Whitelist created at {whitelist_path}")
    click.echo("  Edit this file to add your internal domains")

    # Build VM image
    click.echo("\nBuilding VM image (this may take a few minutes on first run)...")
    try:
        rt = None if runtime == 'auto' else runtime
        _, runtime_cmd = VMManager._detect_runtime(rt)
        if VMManager.image_exists(runtime_cmd):
            click.echo("✓ VM image already up to date")
        else:
            VMManager.build_image(rt)
            click.echo("✓ VM image built successfully")
    except RuntimeError as e:
        click.secho(f"⚠️  Could not build VM image: {e}", fg='yellow')
        click.echo("  Run 'vibedom build' manually once a container runtime is installed")

    click.echo("\n✅ Initialization complete!")

@main.command('reload-whitelist')
def reload_whitelist() -> None:
    """Reload the domain whitelist in every running container's proxy.

    Sends SIGHUP to each host proxy so mitmproxy re-reads whitelist.txt
    without restarting containers.
    """
    registry = ContainerRegistry(Path.home() / '.vibedom' / 'containers')
    running = [c for c in registry.all() if c.status == 'running']
    if not running:
        click.echo("No running containers.")
        return

    failed = 0
    for c in running:
        name = Path(c.workspace).name
        if not c.proxy_pid:
            click.secho(f"⚠️  {name}: no proxy PID recorded — run 'vibedom proxy-restart {name}'", fg='yellow')
            failed += 1
            continue
        try:
            os.kill(c.proxy_pid, signal_module.SIGHUP)
            click.echo(f"✅ {name}: whitelist reloaded (proxy PID {c.proxy_pid})")
        except ProcessLookupError:
            click.secho(f"❌ {name}: proxy PID {c.proxy_pid} not running — run 'vibedom proxy-restart {name}'", fg='red')
            failed += 1
    if failed:
        sys.exit(1)


@main.command('proxy-restart')
@click.argument('workspace', required=False)
def proxy_restart(workspace: Optional[str]) -> None:
    """Restart the host proxy for a running container.

    WORKSPACE is a workspace name, path, or container name. If omitted and
    exactly one container is running, that one is used.

    The proxy restarts on the same port so the container's HTTP_PROXY
    setting stays valid. Use this to reload the mitmproxy addon code.
    """
    config_dir = Path.home() / '.vibedom'
    registry = ContainerRegistry(config_dir / 'containers')
    container = registry.find(workspace) if workspace else None
    if container is None and not workspace:
        running = [c for c in registry.all() if c.status == 'running']
        if len(running) == 1:
            container = running[0]
        elif len(running) > 1:
            click.secho("Multiple running containers. Specify a workspace name.", fg='red')
            sys.exit(1)
    if container is None:
        click.secho(f"No container found for '{workspace or ''}'.", fg='red')
        sys.exit(1)
    _restart_container_proxy(container, config_dir)


def _live_container_status(c: ContainerState) -> str:
    """Query the container runtime for the actual current status."""
    if c.runtime == 'apple':
        result = subprocess.run(
            ['container', 'inspect', c.container_name],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            return 'gone'
        if result.stdout.strip() in ('', '[]'):
            return 'gone'
        return parse_apple_inspect_status(result.stdout) or 'unknown'
    else:
        result = subprocess.run(
            ['docker', 'inspect', '--format', '{{.State.Status}}', c.container_name],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            return 'gone'
        return result.stdout.strip() or 'unknown'


def _proxy_is_alive(pid: Optional[int]) -> bool:
    """Check whether a proxy process is still running.

    os.kill(pid, 0) raises ProcessLookupError when the process does not exist
    and PermissionError (EPERM) when it exists but is owned by another user.
    Both mean the proxy we started is not reachable; any other OSError is re-raised.
    """
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def _ensure_proxy_running(
    container_state: ContainerState,
    container_dir: Path,
    config_dir: Path,
) -> Optional[ProxyManager]:
    """Ensure the host proxy is running. Restarts it if dead. Returns the proxy manager or None."""
    if _proxy_is_alive(container_state.proxy_pid):
        return None  # Already running

    proxy = ProxyManager(session_dir=container_dir, config_dir=config_dir)
    try:
        proxy.start(port=container_state.proxy_port)
    except RuntimeError as e:
        click.secho(f"⚠️  Could not start proxy: {e}", fg='yellow')
        return None
    container_state.proxy_pid = proxy.pid
    container_state.proxy_port = proxy.port
    container_state.save(container_dir)
    click.echo(f"Proxy started on port {proxy.port} (PID {proxy.pid})")
    return proxy


def _restart_container_proxy(container: ContainerState, config_dir: Path) -> None:
    """Force-restart the host proxy for a running persistent container.

    Unlike ``_ensure_proxy_running`` (which only starts a dead proxy), this
    always stops the current proxy and starts a fresh one on the same port,
    so the mitmproxy addon code is reloaded (e.g. after a DLP-scrubber fix).
    Exits the process with a non-zero status on error.
    """
    # Trust the runtime, not the persisted status field, which can drift
    # (e.g. a reboot restarts the container without updating container.json).
    # This is the same source of truth `vibedom list` uses.
    live_status = _live_container_status(container)
    if live_status != 'running':
        click.secho(
            f"❌ Container '{Path(container.workspace).name}' is not running "
            f"(status: {live_status}) — start it with 'vibedom up' first.",
            fg='red'
        )
        sys.exit(1)

    if not container.proxy_port:
        click.secho(
            "❌ No proxy port recorded for this container "
            "(started with older vibedom?)",
            fg='red'
        )
        sys.exit(1)

    container_dir = config_dir / 'containers' / Path(container.workspace).name

    # Stop existing proxy if still running
    if container.proxy_pid:
        try:
            os.kill(container.proxy_pid, signal_module.SIGTERM)
            click.echo(f"Stopped proxy (PID {container.proxy_pid})")
        except ProcessLookupError:
            click.echo(f"Proxy (PID {container.proxy_pid}) was already stopped")

    # Start fresh proxy on the same port so the container's HTTP_PROXY stays valid
    proxy = ProxyManager(session_dir=container_dir, config_dir=config_dir)
    try:
        proxy.start(port=container.proxy_port)
    except RuntimeError as e:
        click.secho(f"❌ Failed to start proxy: {e}", fg='red')
        sys.exit(1)

    container.proxy_pid = proxy.pid
    container.proxy_port = proxy.port
    container.status = 'running'  # reconcile any drift in the persisted field
    container.save(container_dir)

    click.echo(f"✅ Proxy restarted on port {proxy.port} (PID {proxy.pid})")


def _run_setup_commands(vm, project_config) -> None:
    """Run vibedom.yml `setup:` commands inside a freshly created container.

    Called after every create (first run, recreate, or re-create of a container
    that vanished from the runtime) since anything setup installed into the
    container filesystem is gone.
    """
    if not (project_config and project_config.setup):
        return
    click.echo("Running setup commands...")
    for setup_cmd in project_config.setup:
        click.echo(f"  $ {setup_cmd}")
        result = vm.exec(['sh', '-c', setup_cmd])
        if result.returncode != 0:
            click.secho(f"  Warning: setup command failed: {result.stderr}", fg='yellow')


@main.command()
@click.argument('workspace', type=click.Path(exists=True))
@click.option('--runtime', '-r', type=click.Choice(['auto', 'docker', 'apple'],
              case_sensitive=False), default='auto',
              help='Container runtime (auto-detect, docker, or apple)')
@click.option('--recreate', is_flag=True,
              help='Remove the existing container and create it again from the current '
                   'vibedom.yml (picks up new mounts, env, image changes). Repo data and '
                   'container state are kept; setup commands re-run.')
@click.option('--yes', '-y', '--force', 'yes', is_flag=True,
              help='Skip the confirmation prompt for --recreate')
def up(workspace, runtime, recreate, yes):
    """Start a persistent project container.

    Creates the container on first use; restarts it if stopped; does nothing if already running.
    With --recreate, an existing container is removed and rebuilt from the current vibedom.yml.
    """
    workspace_path = Path(workspace).resolve()
    if not workspace_path.is_dir():
        click.secho(f"Error: {workspace_path} is not a directory", fg='red')
        sys.exit(1)

    config_dir = Path.home() / '.vibedom'
    containers_dir = config_dir / 'containers'
    container_dir = containers_dir / workspace_path.name
    container_dir.mkdir(parents=True, exist_ok=True)

    try:
        resolved_runtime, _ = VMManager._detect_runtime(
            runtime if runtime != 'auto' else None
        )
    except RuntimeError as e:
        click.secho(f"Error: {e}", fg='red')
        sys.exit(1)

    project_config = ProjectConfig.load(workspace_path)
    mounts = project_config.mounts if project_config else None
    if mounts:
        for m in mounts:
            if not m.host_path.is_dir():
                click.secho(
                    f"Error: mount path is not a directory: {m.host_path}", fg='red'
                )
                sys.exit(1)

    registry = ContainerRegistry(containers_dir)
    container_state = registry.find(workspace_path.name)

    vm = VMManager(
        workspace_path, config_dir,
        container_dir=container_dir,
        runtime=resolved_runtime,
        network=project_config.network if project_config else None,
        base_image=project_config.base_image if project_config else None,
        host_aliases=project_config.host_aliases if project_config else None,
        memory=project_config.memory if project_config else None,
        extra_env=project_config.env if project_config else None,
        mounts=mounts,
    )

    if recreate and vm.exists():
        if not (mounts or yes) and not click.confirm(
            f"Recreate container '{vm.container_name}'? The container filesystem is discarded "
            f"(the repo copy at {container_dir / 'repo'} is kept).",
            default=False,
        ):
            click.echo("Aborted")
            return
        click.echo(f"Removing container '{vm.container_name}' for recreation...")
        if container_state and container_state.proxy_pid:
            try:
                os.kill(container_state.proxy_pid, signal_module.SIGTERM)
            except ProcessLookupError:
                pass
        vm.stop()
        if not (project_config and project_config.base_image):
            # No project layer to rebuild on create, so refresh the base image here
            # so startup.sh changes are picked up. Layer caching keeps this cheap.
            click.echo("Rebuilding base image...")
            VMManager.build_image(resolved_runtime)
        if container_state is None:
            container_state = ContainerState.create(
                workspace_path, resolved_runtime, live=bool(mounts)
            )
        container_state.live = bool(mounts)

    if vm.is_running() and not recreate:
        click.echo(f"Container '{vm.container_name}' is already running.")
        if container_state:
            _ensure_proxy_running(container_state, container_dir, config_dir)
        if container_state and container_state.live:
            click.echo("Live-mount container — files are shared with your host.")
        else:
            click.echo(f"Repo: {container_dir / 'repo'}")
        return

    if vm.exists() and not recreate:
        # Container stopped — restart proxy then container
        click.echo(f"Restarting container '{vm.container_name}'...")
        if container_state is None:
            container_state = ContainerState.create(
                workspace_path, resolved_runtime, live=bool(mounts)
            )
        proxy = ProxyManager(session_dir=container_dir, config_dir=config_dir)
        try:
            proxy.start(port=container_state.proxy_port)
        except RuntimeError as e:
            click.secho(f"Error starting proxy: {e}", fg='red')
            sys.exit(1)
        try:
            vm.restart()
        except RuntimeError as e:
            proxy.stop()
            click.secho(f"Error: {e}", fg='red')
            sys.exit(1)
        container_state.mark_running(proxy.port, proxy.pid, container_dir)
    elif container_state is not None:
        # Container no longer exists in the runtime but the state file and repo are intact.
        # Repo data is safe in the bind-mount directory — just recreate the container.
        click.echo(f"Container '{vm.container_name}' not found. Recreating with existing repo...")
        try:
            vm.start()
        except RuntimeError as e:
            click.secho(f"Error: {e}", fg='red')
            sys.exit(1)
        container_state.mark_running(vm._proxy.port, vm._proxy.pid, container_dir)
        _run_setup_commands(vm, project_config)

    else:
        # First-time creation
        click.echo("Scanning for secrets...")
        if mounts:
            findings = []
            for m in mounts:
                findings.extend(scan_workspace(m.host_path))
        else:
            findings = scan_workspace(workspace_path)
        if not review_findings(findings):
            click.secho("Cancelled", fg='yellow')
            sys.exit(1)

        click.echo(f"Starting container '{vm.container_name}'...")
        try:
            vm.start()
        except RuntimeError as e:
            click.secho(f"Error: {e}", fg='red')
            sys.exit(1)

        container_state = ContainerState.create(
            workspace_path, resolved_runtime, live=bool(mounts)
        )
        if vm._proxy:
            container_state.mark_running(vm._proxy.port, vm._proxy.pid, container_dir)
        else:
            container_state.save(container_dir)

        _run_setup_commands(vm, project_config)

    if mounts:
        click.echo(f"\nContainer running (live mount)!")
        click.echo("Mounted:")
        for m in mounts:
            ro = ' (ro)' if m.read_only else ''
            click.echo(f"  {m.host_path} -> /work/{m.name}{ro}")
        click.echo(f"\nTo open a shell:")
        click.echo(f"  vibedom shell {workspace_path.name}")
        click.echo(f"\nTo stop:")
        click.echo(f"  vibedom down {workspace_path.name}")
    else:
        click.echo(f"\nContainer running!")
        click.echo(f"Workspace: {workspace_path}")
        click.echo(f"Repo: {container_dir / 'repo'}")
        click.echo(f"\nTo sync code:")
        click.echo(f"  vibedom pull {workspace_path.name}   # container -> host")
        click.echo(f"  vibedom push {workspace_path.name}   # host -> container")
        click.echo(f"\nTo open a shell:")
        click.echo(f"  vibedom shell {workspace_path.name}")
        click.echo(f"\nTo stop:")
        click.echo(f"  vibedom down {workspace_path.name}")


@main.command()
@click.argument('workspace', required=False)
def down(workspace):
    """Stop a persistent container (preserves filesystem).

    WORKSPACE is the workspace directory name or path.
    If omitted, uses the only running container or prompts.
    """
    config_dir = Path.home() / '.vibedom'
    containers_dir = config_dir / 'containers'
    registry = ContainerRegistry(containers_dir)

    identifier = workspace or ''
    container_state = registry.find(identifier) if identifier else None

    if container_state is None and not identifier:
        all_containers = [c for c in registry.all() if c.status == 'running']
        if len(all_containers) == 1:
            container_state = all_containers[0]
        elif len(all_containers) > 1:
            click.secho("Multiple running containers. Specify a workspace name.", fg='red')
            for c in all_containers:
                click.echo(f"  {Path(c.workspace).name}")
            sys.exit(1)
        else:
            click.secho("No running containers found.", fg='yellow')
            return

    if container_state is None:
        click.secho(f"No container found for '{workspace}'.", fg='red')
        sys.exit(1)

    container_dir = containers_dir / Path(container_state.workspace).name
    vm = VMManager(
        Path(container_state.workspace), config_dir,
        container_dir=container_dir,
        runtime=container_state.runtime,
    )

    click.echo(f"Stopping container '{container_state.container_name}'...")
    vm.pause()

    if container_state.proxy_pid:
        try:
            os.kill(container_state.proxy_pid, signal_module.SIGTERM)
        except ProcessLookupError:
            pass

    container_state.mark_stopped(container_dir)
    click.echo("Container stopped (filesystem preserved). Run 'vibedom up' to restart.")


@main.command()
@click.argument('workspace', required=False)
@click.option('--force', '-f', is_flag=True, help='Skip confirmation prompt')
def destroy(workspace, force):
    """Remove a persistent container and its state.

    WORKSPACE is the workspace directory name or path.
    This removes the container and its repo — use 'vibedom down' to just stop it.
    """
    config_dir = Path.home() / '.vibedom'
    containers_dir = config_dir / 'containers'
    registry = ContainerRegistry(containers_dir)

    container_state = registry.find(workspace) if workspace else None

    if container_state is None and not workspace:
        click.secho("Specify a workspace name.", fg='red')
        sys.exit(1)

    if container_state is None:
        click.secho(f"No container found for '{workspace}'.", fg='red')
        sys.exit(1)

    name = Path(container_state.workspace).name
    if not force and not click.confirm(
        f"Destroy container '{container_state.container_name}' and delete repo data for '{name}'?",
        default=False,
    ):
        click.echo("Aborted")
        return

    container_dir = containers_dir / name
    vm = VMManager(
        Path(container_state.workspace), config_dir,
        container_dir=container_dir,
        runtime=container_state.runtime,
    )

    click.echo(f"Destroying container '{container_state.container_name}'...")
    vm.stop()

    if container_state.proxy_pid:
        try:
            os.kill(container_state.proxy_pid, signal_module.SIGTERM)
        except ProcessLookupError:
            pass

    shutil.rmtree(container_dir, ignore_errors=True)
    click.echo(f"Container '{container_state.container_name}' destroyed.")


@main.command()
@click.argument('workspace', required=False)
def status(workspace):
    """Show status of persistent containers."""
    config_dir = Path.home() / '.vibedom'
    containers_dir = config_dir / 'containers'
    registry = ContainerRegistry(containers_dir)

    if workspace:
        container_state = registry.find(workspace)
        if not container_state:
            click.secho(f"No container found for '{workspace}'.", fg='red')
            sys.exit(1)
        containers = [container_state]
    else:
        containers = registry.all()

    if not containers:
        click.echo("No persistent containers found. Run 'vibedom up <workspace>' to create one.")
        return

    click.echo(f"{'WORKSPACE':<25} {'CONTAINER':<35} {'STATUS':<10} {'PROXY'}")
    click.echo('-' * 85)
    for c in containers:
        workspace_name = Path(c.workspace).name
        proxy_info = f"port {c.proxy_port}" if c.proxy_port else "none"
        if c.proxy_pid and _proxy_is_alive(c.proxy_pid):
            proxy_info += f" (PID {c.proxy_pid})"
        else:
            proxy_info += " (dead)" if c.proxy_pid else ""
        live_status = _live_container_status(c)
        click.echo(
            f"{workspace_name:<25} "
            f"{c.container_name:<35} "
            f"{live_status:<10} "
            f"{proxy_info}"
        )


@main.command('shell')
@click.argument('workspace', required=False)
def shell_cmd(workspace):
    """Open a shell in a running container's workspace (/work/repo).

    WORKSPACE is the workspace directory name or path.
    If omitted, uses the only running container or prompts.
    """
    config_dir = Path.home() / '.vibedom'
    containers_dir = config_dir / 'containers'
    registry = ContainerRegistry(containers_dir)

    container_state = registry.find(workspace) if workspace else None

    if container_state is None and not workspace:
        running = [c for c in registry.all() if c.status == 'running']
        if len(running) == 1:
            container_state = running[0]
        elif len(running) > 1:
            click.secho("Multiple running containers. Specify a workspace name.", fg='red')
            sys.exit(1)
        else:
            click.secho("No running containers found.", fg='red')
            sys.exit(1)

    if container_state is None:
        click.secho(f"No container found for '{workspace}'.", fg='red')
        sys.exit(1)

    # Ensure proxy is alive before entering
    container_dir = containers_dir / Path(container_state.workspace).name
    _ensure_proxy_running(container_state, container_dir, config_dir)

    runtime_cmd = 'container' if container_state.runtime == 'apple' else 'docker'
    workdir = '/work' if container_state.live else '/work/repo'
    cmd = [runtime_cmd, 'exec', '-it', '-w', workdir,
           container_state.container_name, 'bash', '--login']
    try:
        subprocess.run(cmd)
    except FileNotFoundError:
        click.secho(f"Error: {runtime_cmd} command not found", fg='red')
        sys.exit(1)


def _validate_sync_paths(paths: tuple, src: Path) -> list[Path]:
    """Validate and resolve path arguments for sync commands.

    Each path must be relative (no leading '/') and must resolve to a location
    inside src after resolving any '..' components.  Absolute paths and path
    traversals that escape src are rejected to prevent accidental writes
    outside the workspace or container repo.

    Args:
        paths: Raw path strings provided by the user.
        src: The source root directory that all paths must stay within.

    Returns:
        List of resolved absolute Path objects, each guaranteed to be inside src.

    Raises:
        click.ClickException: If any path is invalid or escapes src.
    """
    validated = []
    src_resolved = src.resolve()
    for raw in paths:
        if Path(raw).is_absolute():
            raise click.ClickException(
                f"Path argument must be relative, not absolute: '{raw}'"
            )
        resolved = (src_resolved / raw).resolve()
        try:
            resolved.relative_to(src_resolved)
        except ValueError:
            raise click.ClickException(
                f"Path '{raw}' escapes the source directory — path traversal not allowed"
            )
        validated.append(resolved)
    return validated


def _make_workspace_relative(raw: str, workspace_root: Path, cwd: Path | None = None) -> str:
    """Resolve a path argument relative to CWD if CWD is inside workspace_root.

    Returns a workspace-root-relative path string. Falls back to raw unchanged
    if CWD is outside workspace_root or if the resolved path escapes the root.
    """
    if cwd is None:
        cwd = Path.cwd()
    cwd = cwd.resolve()
    workspace_resolved = workspace_root.resolve()
    try:
        cwd.relative_to(workspace_resolved)
    except ValueError:
        return raw
    try:
        return str((cwd / raw).resolve().relative_to(workspace_resolved))
    except ValueError:
        return raw


def _build_rsync_cmd(
    src: Path,
    dst: Path,
    paths: tuple,
    delete: bool,
    dry_run: bool,
    extra_excludes: list,
) -> list:
    """Build an rsync command for syncing src to dst.

    Args:
        src: Source directory (trailing slash makes rsync sync its contents)
        dst: Destination directory
        paths: Specific sub-paths to sync (relative to src). If empty, sync all.
            All paths must have already been validated via _validate_sync_paths.
        delete: Include --delete flag (destructive)
        dry_run: Include --dry-run flag
        extra_excludes: Additional patterns to exclude beyond .gitignore
    """
    cmd = ['rsync', '-av']

    if dry_run:
        cmd.append('--dry-run')

    # Exclude .git always
    cmd += ['--exclude=.git/']

    # Use .gitignore rules from the workspace (source side)
    cmd += ['--filter=:- .gitignore']

    for pattern in extra_excludes:
        cmd.append(f'--exclude={pattern}')

    if delete:
        cmd.append('--delete')

    if paths:
        # --relative with /./  preserves the path structure in the destination.
        # e.g. /src_root/./sub/dir/file.py lands at /dst/sub/dir/file.py
        cmd.append('--relative')
        src_resolved = src.resolve()
        dst_resolved = dst.resolve()
        for raw in paths:
            cmd.append(f'{src_resolved}/./{raw}')
        cmd.append(str(dst_resolved))
    else:
        cmd.append(f'{src}/')
        cmd.append(str(dst))

    return cmd


def _find_deletions(cmd: list[str]) -> list[str]:
    """Run a silent rsync dry-run and return paths that would be deleted.

    Parses lines beginning with 'deleting ' from rsync's stdout.
    """
    dry_cmd = list(cmd)
    if '--dry-run' not in dry_cmd:
        dry_cmd.append('--dry-run')
    result = subprocess.run(dry_cmd, capture_output=True, text=True)
    return [
        line[len('deleting '):]
        for line in result.stdout.splitlines()
        if line.startswith('deleting ')
    ]


@main.command()
@click.argument('workspace')
@click.argument('paths', nargs=-1)
@click.option('--delete', is_flag=True, help='Also remove files in host that are absent in container')
@click.option('--dry-run', '-n', is_flag=True, help='Show what would be synced without doing it')
@click.option('--yes', '-y', is_flag=True, help='Skip confirmation for full-tree sync')
@click.option('--force', '-f', is_flag=True, help='Skip all confirmations')
def pull(workspace, paths, delete, dry_run, yes, force):
    """Sync code from container to host workspace.

    WORKSPACE is the workspace directory name or path.
    PATHS are optional relative paths to sync (e.g. src/ app/).
    If no paths given, syncs everything (respecting .gitignore) after confirmation.
    """
    config_dir = Path.home() / '.vibedom'
    containers_dir = config_dir / 'containers'
    registry = ContainerRegistry(containers_dir)

    container_state = registry.find(workspace)
    if container_state is None:
        click.secho(f"No container found for '{workspace}'.", fg='red')
        sys.exit(1)

    if container_state.live:
        click.echo(
            "This is a live-mount container — changes are already on your host; "
            "no sync needed."
        )
        return

    workspace_path = Path(container_state.workspace)
    container_dir = containers_dir / workspace_path.name
    repo_dir = container_dir / 'repo'

    if paths:
        paths = tuple(_make_workspace_relative(p, workspace_path) for p in paths)
        click.echo("Resolved: " + ", ".join(paths))
        try:
            _validate_sync_paths(paths, repo_dir)
        except click.ClickException as e:
            click.secho(f"Error: {e.format_message()}", fg='red')
            sys.exit(1)

    # Full-tree sync without --dry-run requires confirmation
    if not paths and not dry_run and not yes and not force:
        if not click.confirm(
            f"Sync all files from container repo to {workspace_path.name}?",
            default=False,
        ):
            click.echo("Aborted")
            return

    project_config = ProjectConfig.load(workspace_path)
    extra_excludes = (project_config.sync_exclude or []) if project_config else []

    cmd = _build_rsync_cmd(
        src=repo_dir,
        dst=workspace_path,
        paths=paths,
        delete=delete,
        dry_run=dry_run,
        extra_excludes=extra_excludes,
    )

    if delete and not force and not dry_run:
        deletions = _find_deletions(cmd)
        if deletions:
            click.echo("These files will be deleted from the host:")
            for f in deletions:
                click.echo(f"  {f}")
            if not click.confirm("\nProceed?", default=False):
                click.echo("Aborted")
                return

    if dry_run:
        click.echo("Dry run — showing what would be synced:")
    else:
        click.echo(f"Pulling from container to {workspace_path.name}...")

    result = subprocess.run(cmd, capture_output=False, text=True)
    if result.returncode != 0:
        click.secho("rsync failed", fg='red')
        sys.exit(result.returncode)

    if not dry_run:
        click.echo("Done.")


@main.command()
@click.argument('workspace')
@click.argument('paths', nargs=-1)
@click.option('--delete', is_flag=True, help='Also remove files in container that are absent on host')
@click.option('--dry-run', '-n', is_flag=True, help='Show what would be synced without doing it')
@click.option('--yes', '-y', is_flag=True, help='Skip confirmation for full-tree sync')
@click.option('--force', '-f', is_flag=True, help='Skip all confirmations')
def push(workspace, paths, delete, dry_run, yes, force):
    """Sync code from host workspace to container.

    WORKSPACE is the workspace directory name or path.
    PATHS are optional relative paths to sync (e.g. src/ app/).
    If no paths given, syncs everything (respecting .gitignore) after confirmation.
    """
    config_dir = Path.home() / '.vibedom'
    containers_dir = config_dir / 'containers'
    registry = ContainerRegistry(containers_dir)

    container_state = registry.find(workspace)
    if container_state is None:
        click.secho(f"No container found for '{workspace}'.", fg='red')
        sys.exit(1)

    if container_state.live:
        click.echo(
            "This is a live-mount container — changes are already on your host; "
            "no sync needed."
        )
        return

    workspace_path = Path(container_state.workspace)
    container_dir = containers_dir / workspace_path.name
    repo_dir = container_dir / 'repo'

    if paths:
        paths = tuple(_make_workspace_relative(p, workspace_path) for p in paths)
        click.echo("Resolved: " + ", ".join(paths))
        try:
            _validate_sync_paths(paths, workspace_path)
        except click.ClickException as e:
            click.secho(f"Error: {e.format_message()}", fg='red')
            sys.exit(1)

    # Full-tree sync without --dry-run requires confirmation
    if not paths and not dry_run and not yes and not force:
        if not click.confirm(
            f"Sync all files from {workspace_path.name} to container repo?",
            default=False,
        ):
            click.echo("Aborted")
            return

    project_config = ProjectConfig.load(workspace_path)
    extra_excludes = (project_config.sync_exclude or []) if project_config else []

    cmd = _build_rsync_cmd(
        src=workspace_path,
        dst=repo_dir,
        paths=paths,
        delete=delete,
        dry_run=dry_run,
        extra_excludes=extra_excludes,
    )

    if delete and not force and not dry_run:
        deletions = _find_deletions(cmd)
        if deletions:
            click.echo("These files will be deleted from the container:")
            for f in deletions:
                click.echo(f"  {f}")
            if not click.confirm("\nProceed?", default=False):
                click.echo("Aborted")
                return

    if dry_run:
        click.echo("Dry run — showing what would be synced:")
    else:
        click.echo(f"Pushing from {workspace_path.name} to container...")

    result = subprocess.run(cmd, capture_output=False, text=True)
    if result.returncode != 0:
        click.secho("rsync failed", fg='red')
        sys.exit(result.returncode)

    if not dry_run:
        click.echo("Done.")


if __name__ == '__main__':
    main()
