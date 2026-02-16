# Vibedom Usability Improvements Design

**Date:** 2026-02-16
**Status:** Approved
**Context:** Make vibedom usable for daily work by installing Claude Code, fixing mitmproxy logging, and adding whitelist reload

---

## Problem Statement

Vibedom with apple/container migration is nearly complete, but two critical usability issues block daily use:

1. **Claude Code not available in container** - Users must manually install/configure Claude Code every time they exec into a container
2. **mitmproxy logs trapped in container** - Network logs written to `/var/log/vibedom/network.jsonl` inside container, not accessible from host or persisted after container stops
3. **No whitelist reload mechanism** - When a domain is blocked, users must restart entire container to reload whitelist

## Goals

1. Install Claude Code CLI in container image, mount user's `~/.claude` config for seamless authentication
2. Fix mitmproxy to write logs to session directory (accessible from host, persists after container stops)
3. Add `vibedom reload-whitelist <workspace>` command to reload whitelist without restarting

## Non-Goals

- Installing other AI coding tools (Cursor, etc.) - will be handled separately using same pattern
- Automatic whitelist reload via file watching - manual reload is simpler and more reliable in container environments

## Architecture

### Key Principle

Keep containers stateless and reproducible:
- Claude Code binary installed in image (Linux/Alpine compatible)
- User settings mounted from host `~/.claude` (read-only for security)
- Logs written to mounted session directory (persist on host)
- Container can be destroyed and recreated without losing state

### Affected Components

1. **vm/Dockerfile.alpine** - Install Claude Code + dependencies
2. **lib/vibedom/vm.py** - Mount user's `~/.claude` config files
3. **vm/mitmproxy_addon.py** - Change log path + add SIGHUP handler for reload
4. **lib/vibedom/cli.py** - Add `reload-whitelist` command
5. **vm/startup.sh** - Set `USE_BUILTIN_RIPGREP=0` for Alpine compatibility

---

## Design Details

### 1. Claude Code Installation

**Approach:** Install Claude Code in Dockerfile using official installer, mount user's config files individually to avoid conflicts.

**Why not mount entire ~/.claude from host?**
- macOS binaries (Mach-O) won't run in Linux container (ELF)
- Need Alpine-native Claude binary installed in container
- But want user's settings/API key from host macOS

**Solution:** Install to `/root/.claude/bin/claude` in Dockerfile, mount only config files:

```dockerfile
# Install Claude Code dependencies (Alpine/musl requirements)
RUN apk add --no-cache libgcc libstdc++ ripgrep bash curl

# Install Claude Code CLI (goes to /root/.claude/bin/claude)
RUN curl -fsSL https://claude.ai/install.sh | bash
ENV USE_BUILTIN_RIPGREP=0
ENV PATH="/root/.claude/bin:$PATH"
```

**In vm.py start() method:**

```python
# Claude Code config files (read-only)
claude_home = Path.home() / '.claude'
if claude_home.exists():
    # Mount API key if exists
    if (claude_home / 'api_key').exists():
        cmd += ['-v', f'{claude_home / "api_key"}:/root/.claude/api_key:ro']

    # Mount settings if exists
    if (claude_home / 'settings.json').exists():
        cmd += ['-v', f'{claude_home / "settings.json"}:/root/.claude/settings.json:ro']

    # Mount skills directory if exists
    if (claude_home / 'skills').is_dir():
        cmd += ['-v', f'{claude_home / "skills"}:/root/.claude/skills:ro']
```

**Result:**
- Claude binary at `/root/.claude/bin/claude` (from Dockerfile)
- User's settings at `/root/.claude/api_key`, `/root/.claude/settings.json`, etc. (mounted from host)
- No conflicts, both coexist

---

### 2. mitmproxy Logging to Session Directory

**Current issue:** Logs written to `/var/log/vibedom/network.jsonl` inside container's ephemeral filesystem. Not accessible from host, lost when container stops.

**Fix:** Write logs to `/mnt/session/network.jsonl` (mounted from `~/.vibedom/logs/session-*/` on host)

**Change in mitmproxy_addon.py:**

```python
def __init__(self):
    self.whitelist = self.load_whitelist()
    # Write to session directory instead of container-local /var/log
    self.network_log_path = Path('/mnt/session/network.jsonl')
    self.network_log_path.parent.mkdir(parents=True, exist_ok=True)
    # ... rest of init
```

**Result:**
- Logs immediately visible on host at `~/.vibedom/logs/session-*/network.jsonl`
- Logs persist after container stops
- Can monitor in real-time: `tail -f ~/.vibedom/logs/session-*/network.jsonl`

---

### 3. Whitelist Reload Command

**Approach:** Use Unix signals (SIGHUP) for reload trigger. CLI command sends signal to mitmproxy process inside container.

**Add signal handler in mitmproxy_addon.py:**

```python
import signal

class VibedomProxy:
    def __init__(self):
        # ... existing init code ...

        # Register SIGHUP handler for whitelist reload
        signal.signal(signal.SIGHUP, self._reload_whitelist)

    def _reload_whitelist(self, signum, frame):
        """Reload whitelist when SIGHUP received."""
        self.whitelist = self.load_whitelist()
        print(f"Reloaded whitelist: {len(self.whitelist)} domains", file=sys.stderr)
```

**Add CLI command in cli.py:**

```python
@cli.command('reload-whitelist')
@click.argument('workspace', type=click.Path(exists=True))
def reload_whitelist(workspace: str) -> None:
    """Reload domain whitelist without restarting container."""
    workspace_path = Path(workspace).resolve()
    container_name = f'vibedom-{workspace_path.name}'

    try:
        runtime, runtime_cmd = VMManager._detect_runtime()
    except RuntimeError as e:
        click.secho(f"❌ {e}", fg='red')
        sys.exit(1)

    # Send SIGHUP to mitmdump process
    result = subprocess.run(
        [runtime_cmd, 'exec', container_name, 'pkill', '-HUP', 'mitmdump'],
        capture_output=True, text=True
    )

    if result.returncode == 0:
        click.echo(f"✅ Reloaded whitelist for {workspace_path.name}")
    else:
        click.secho(f"❌ Failed to reload: {result.stderr}", fg='red')
        sys.exit(1)
```

**Usage workflow:**
1. Request gets blocked (403)
2. Edit `~/.vibedom/config/trusted_domains.txt` to add domain
3. Run: `vibedom reload-whitelist ~/projects/myapp`
4. Retry request - now succeeds

---

## Data Flow

### Claude Code Usage
1. User starts vibedom: `vibedom run ~/projects/myapp --runtime docker`
2. Container starts with Claude binary + user's settings mounted
3. User execs into container: `docker exec -it vibedom-myapp /bin/bash`
4. Inside container: `claude` (finds binary in PATH, reads mounted api_key/settings)
5. Claude Code works in `/work/repo` with user's authenticated session

### mitmproxy Logging (Fixed)
1. Container makes HTTP/HTTPS request (proxied through mitmproxy)
2. mitmproxy addon intercepts, checks whitelist, scrubs secrets
3. Logs written to `/mnt/session/network.jsonl` (mounted from host)
4. Logs immediately visible at `~/.vibedom/logs/session-*/network.jsonl`
5. Logs persist after container stops

### Whitelist Reload
1. Request blocked (403 error)
2. User edits `~/.vibedom/config/trusted_domains.txt` on host
3. User runs: `vibedom reload-whitelist ~/projects/myapp`
4. CLI sends SIGHUP to mitmdump inside container
5. Signal handler reloads whitelist from `/mnt/config/trusted_domains.txt`
6. User retries request - succeeds

---

## Error Handling

### Claude Code Installation (Build-Time)
- If `curl` to claude.ai fails → Build fails with clear error
- If dependencies missing → apk fails during build
- **Mitigation:** Build failures are acceptable - immediate feedback

### Claude Settings Mount (Runtime)
- If `~/.claude` doesn't exist → Skip mounts, Claude not authenticated (graceful degradation)
- If specific files missing → Skip those mounts, Claude uses defaults
- No errors thrown - degrades gracefully

### mitmproxy Logging
- If `/mnt/session` not mounted → Logs fail, warning to stderr (existing behavior)
- If disk full → OSError caught, warning printed (already handled)

### Whitelist Reload
- If container not running → `pkill` fails, CLI shows: "❌ Failed to reload: container not found"
- If mitmdump not found → `pkill` non-zero exit, CLI shows: "❌ Failed to reload: process not found"
- If whitelist malformed → Loads successfully but domains may not parse (no schema validation)

**Philosophy:** Fail fast at build time, degrade gracefully at runtime. No retry logic or complex validation.

---

## Testing Plan

**Note:** apple/container has a DNS bug. Use `--runtime docker` for all testing until Apple fixes it.

### Build Verification

```bash
# Test 1: Build image with Claude Code installed
./vm/build.sh --runtime docker
# Expected: Successful build, no errors

# Test 2: Verify Claude binary exists
docker run --rm vibedom-alpine:latest which claude
# Expected: /root/.claude/bin/claude
```

### Runtime Verification

```bash
# Test 3: Start container with Docker
vibedom run ~/projects/test-workspace --runtime docker

# Test 4: Verify Claude available and authenticated
docker exec vibedom-test-workspace claude --version
# Expected: Claude Code version info

# Test 5: Verify settings mounted
docker exec vibedom-test-workspace ls -la /root/.claude/
# Expected: api_key, settings.json, skills/ visible

# Test 6: Verify network logs go to session directory
docker exec vibedom-test-workspace curl https://pypi.org
cat ~/.vibedom/logs/session-*/network.jsonl
# Expected: Log entry visible on host immediately

# Test 7: Test whitelist reload
# Edit ~/.vibedom/config/trusted_domains.txt to add 'example.com'
vibedom reload-whitelist ~/projects/test-workspace
docker exec vibedom-test-workspace curl https://example.com
# Expected: Request succeeds (not blocked)
```

**No new unit tests** - these are integration-level changes. Manual verification sufficient.

---

## Implementation Notes

### Dockerfile Security Note
- Installing Claude via `curl | bash` is not ideal from security perspective
- This is Anthropic's official installation method
- Risk accepted since we trust Anthropic and source (claude.ai)
- Alternative would be pre-downloading and verifying binary, but adds complexity

### Mount Read-Only Strategy
- All user config mounts are `:ro` (read-only)
- Prevents accidental modifications from inside container
- Container should never write to user's host `~/.claude` directory

### Signal Handling
- SIGHUP is standard Unix convention for config reload
- Python's `signal.signal()` is thread-safe and reliable
- Alternative (polling for trigger file) is less elegant and has latency

---

## Future Enhancements

1. **Add other AI coding tools** - Use same pattern for Cursor, Windsurf, etc.
2. **Whitelist validation** - Validate `trusted_domains.txt` syntax before reload
3. **Hot reload option** - Add file watching if manual reload proves too cumbersome
4. **Session log streaming** - `vibedom logs <workspace>` to tail session logs from host

---

## References

- [Claude Code Installation Docs](https://code.claude.com/docs/en/setup)
- [Alpine Linux musl compatibility](https://wiki.alpinelinux.org/wiki/Running_glibc_programs)
- [Python signal handling](https://docs.python.org/3/library/signal.html)

---

## Approval

Design approved: 2026-02-16

Next step: Create implementation plan using writing-plans skill.
