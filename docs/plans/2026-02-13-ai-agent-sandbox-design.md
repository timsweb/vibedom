# Secure AI Agent Sandbox - Design Document

**Date**: 2026-02-13
**Status**: Approved
**Target Platform**: macOS (Apple Silicon)

## 1. Overview

A hardware-isolated sandbox environment for running AI coding agents (Claude Code, OpenCode) on Apple Silicon Macs. The system prevents PII leaks, blocks malicious command injection, and restricts network access while supporting internal GitLab/Composer workflows.

### Key Requirements

- **Threat Model**: Comprehensive defense against PII exfiltration, malicious commands, and lateral movement
- **Users**: Internal development team only
- **Usage Pattern**: Mixed (one-off tasks + long-running sessions)
- **Isolation**: Hardware VM-level (not Docker namespaces)
- **Startup Time**: 30-60 seconds acceptable
- **Maintenance**: Moderate (willing to tune rules monthly)

## 2. Architecture

### 2.1 System Overview

```
┌─────────────────────────────────────────────────────────────┐
│ Host (macOS - Apple Silicon)                                │
│  ┌───────────────────────────────────────────────────────┐  │
│  │ apple/container VM (Linux ARM64)                      │  │
│  │  ┌─────────────────────────────────────────────────┐  │  │
│  │  │ AI Agent (Claude Code / OpenCode)              │  │  │
│  │  │  - Workspace: /mnt/workspace (read-only)       │  │  │
│  │  │  - Overlay: /work (read-write)                 │  │  │
│  │  │  - Git SSH: Deploy key only                    │  │  │
│  │  └─────────────────────────────────────────────────┘  │  │
│  │                        ↓                               │  │
│  │  ┌─────────────────────────────────────────────────┐  │  │
│  │  │ Transparent Proxy (mitmproxy)                   │  │  │
│  │  │  - Egress whitelist enforcement                │  │  │
│  │  │  - Request/response interception               │  │  │
│  │  └─────────────────────────────────────────────────┘  │  │
│  │                        ↓                               │  │
│  │  ┌─────────────────────────────────────────────────┐  │  │
│  │  │ DLP Layer (Presidio) [Phase 2]                  │  │  │
│  │  │  - PII detection & anonymization               │  │  │
│  │  │  - Custom recognizers (GitLab tokens, etc.)    │  │  │
│  │  └─────────────────────────────────────────────────┘  │  │
│  └───────────────────────────────────────────────────────┘  │
│                                                             │
│  Host Filesystem: ~/projects/myapp ──(mount)──> VM         │
│  Logs: ~/.vibedom/logs/session-YYYYMMDD-HHMMSS/           │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 Core Design Decisions

1. **VM-level isolation**: Using Apple's Virtualization.framework via apple/container prevents kernel-level escapes (unlike Docker's namespace-only isolation).

2. **Overlay filesystem**: Host workspace mounts read-only at `/mnt/workspace`. An OverlayFS provides a writable layer at `/work`. Changes are presented as diffs for review before merging back to host.

3. **Forced proxy**: All network traffic routes through mitmproxy via iptables REDIRECT rules. The agent cannot bypass it.

4. **Phased deployment**: Build core functionality first (Phase 1), add sophisticated DLP later (Phase 2).

## 3. Component Design

### 3.1 Pre-Flight Scanner (Gitleaks)

**Purpose**: Detect hardcoded secrets before agent accesses workspace.

**Behavior**:
- Runs on **host** before VM starts
- If secrets found → present categorized report to user
- User can review and choose: continue, ignore specific items, or cancel

**Smart Categorization**:
```python
def categorize_secret(secret, file_path):
    if '.env.local' in file_path or '.env.development' in file_path:
        return 'LOW_RISK', 'Local dev credential'

    if 'sk_live_' in secret or 'prod' in file_path:
        return 'HIGH_RISK', 'Production credential'

    if secret in workspace_env_values:
        return 'MEDIUM_RISK', 'Environment variable (will be scrubbed in DLP)'

    return 'MEDIUM_RISK', 'Unknown credential'
```

**User Experience**:
```
⚠️  Found 3 potential secrets:

1. .env:5 - DB_PASSWORD=root
   → Local dev credential (LOW RISK)

2. config.php:42 - API_KEY=sk_live_...
   → Production API key (HIGH RISK)

3. .env:8 - GITLAB_TOKEN=glpat-xyz...
   → GitLab token (MEDIUM RISK)

Options:
 [c] Continue anyway (I've reviewed these)
 [a] Approve all for this workspace (don't ask again)
 [i] Ignore specific items (choose which)
 [x] Cancel and fix
```

**Workspace Policy**: Users can create `.vibedom/approved_secrets.txt` to suppress warnings for known safe patterns (e.g., test fixtures, local dev credentials).

### 3.2 Overlay Filesystem

**Mount Structure** (inside VM):
```
/mnt/workspace  → Read-only bind mount of host project
/work           → OverlayFS (lower: /mnt/workspace, upper: /tmp/overlay)
```

**Agent Behavior**: Works in `/work` directory. All file operations write to `/tmp/overlay`, leaving host filesystem untouched.

**Session End Workflow**:
1. Generate diff: `diff -ur /mnt/workspace /work > /tmp/changes.patch`
2. Present to user: "Agent made X changes to Y files. Review? [approve/reject/edit]"
3. If approved: Apply patch to host with `patch -d ~/projects/myapp < /tmp/changes.patch`

**Conflict Detection**: If host workspace was modified during session, warn user during diff review. No automatic locking (too complex).

### 3.3 Network Layer: MITM Proxy + DLP

**Phase 1**: Basic whitelist enforcement
**Phase 2**: Add Presidio for intelligent scrubbing

#### Phase 1: Whitelist-Only

**Configuration** (`~/.vibedom/config/trusted_domains.txt`):
```
# External APIs
api.anthropic.com
packagist.org
github.com

# Internal services
gitlab.company.internal
composer.company.internal
```

**Request Flow**:
```
Request → Domain in whitelist? → No: BLOCK (403)
                                → Yes: ALLOW + log
```

#### Phase 2: Context-Aware DLP

**Pre-flight Workspace Scan** (runs during VM boot):
```python
# Scan workspace for sensitive values to scrub
secrets = []
secrets.extend(scan_env_files(['/mnt/workspace/**/.env*']))
secrets.extend(scan_git_config('/mnt/workspace/.git/config'))
secrets.extend(load_custom_patterns('/mnt/config/custom_secrets.txt'))

# Build dynamic scrubbing rules
for secret in secrets:
    presidio_analyzer.add_recognizer(PatternRecognizer(secret))
```

**Runtime Interception**:
```
Request → Whitelist Check → DLP Scan → Allow/Block/Scrub
```

**Context-Aware Scrubbing Rules**:

| Data Type | External (Anthropic) | Internal (GitLab) | Public (GitHub) |
|-----------|---------------------|-------------------|-----------------|
| PII (names, emails) | **SCRUB** | Allow | **SCRUB** |
| Internal IPs | **SCRUB** | Allow | **SCRUB** |
| .env secrets | **SCRUB** | Allow (logged) | **SCRUB** |
| GitLab tokens | **SCRUB** | Allow | **SCRUB** |
| Code snippets | Allow | Allow | Allow |
| File paths | Allow | Allow | **SCRUB** (home dirs) |

**Blocking Patterns** (always block, regardless of destination):
- Command injection: `curl ... | bash`, `wget ... | sh`
- Reverse shells: `nc -e`, `bash -i`
- Data exfiltration: `base64 encode + POST to unknown domain`

**Logging Only** (warn but allow):
- Large file uploads (>10MB) to external services
- Repeated failed authentication attempts
- Unusual git operations (force push, tag deletion)

**User Override**:
```bash
# For this session, allow sending IP addresses to Anthropic
vibedom run --allow-context=internal_ips
```

**Example Scrubbing**:
```json
// Original request to api.anthropic.com
{
  "messages": [{
    "role": "user",
    "content": "Connect to mysql://admin:MyP@ssw0rd@192.168.1.50/db"
  }]
}

// Scrubbed request
{
  "messages": [{
    "role": "user",
    "content": "Connect to mysql://[REDACTED:CREDENTIALS]@[REDACTED:INTERNAL_IP]/db"
  }]
}
```

### 3.4 Deploy Key Management

**Setup** (one-time):
```bash
vibedom init
  → Generate SSH keypair: ~/.vibedom/keys/id_ed25519_vibedom
  → Print public key: "Add this to GitLab → Settings → SSH Keys"
```

**Session Behavior**:
- VM uses deploy key (not user's personal SSH keys)
- Provides audit trail (which machine/sandbox accessed GitLab)
- Key is reused across sessions (no regeneration needed)

## 4. Data Flow (Session Lifecycle)

### 4.1 First-Time Setup (~2 minutes)

```bash
vibedom init
```

1. Check system: Verify macOS + Apple Silicon
2. Install apple/container if needed
3. Download VM image: Pre-built Alpine Linux ARM64 (~400MB)
4. Generate deploy key
5. Print setup instructions for GitLab

### 4.2 Session Start (~45 seconds)

```bash
vibedom run ~/projects/myapp
```

**Timeline**:
- **T+0s**: Pre-flight Gitleaks scan → present findings if any
- **T+10s**: Boot VM, mount workspace (read-only), create overlay
- **T+20s**: Start mitmproxy, load whitelist
- **T+30s**: [Phase 2] Scan .env files, load Presidio models (background)
- **T+45s**: Agent ready, launch claude-code/opencode

### 4.3 During Session

**Every network request**:
```
Agent → syscall → iptables → mitmproxy → [Phase 1: whitelist check]
                                        → [Phase 2: + DLP scan]
                                        → destination
```

**Every file write**:
```
Agent writes to /work/src/file.php
  → Actually writes to /tmp/overlay/src/file.php
  → /mnt/workspace/src/file.php unchanged (read-only)
```

### 4.4 Session End

**Quick Exit** (one-off task):
```bash
vibedom stop
```
1. Generate diff between `/work` and `/mnt/workspace`
2. Show summary: "Modified 3 files, added 1 file"
3. Prompt: "Apply changes? [y/n/review]"
4. Save logs to `~/.vibedom/logs/session-YYYYMMDD-HHMMSS/`
5. Destroy VM

**Pause** (long-running session):
```bash
vibedom pause
```
1. Snapshot VM state (including overlay)
2. Suspend VM
3. Resume later: `vibedom resume myapp`

**Log Structure**:
```
~/.vibedom/logs/session-20260213-143022/
├── network.jsonl          # All HTTP requests (scrubbed in Phase 2)
├── dlp_audit.jsonl.enc    # Original values (encrypted, Phase 2)
├── alerts.jsonl           # Blocked requests
├── gitleaks_report.json   # Pre-flight scan results
└── session.log            # VM boot, commands, errors
```

## 5. Error Handling

### 5.1 Network Failures

**Problem**: mitmproxy crashes or whitelist misconfigured.

**Recovery**:
- Systemd auto-restarts mitmproxy within 5s
- Queued requests retry automatically
- Debugging: `vibedom attach myapp` to inspect VM
- Emergency bypass: `vibedom run --bypass-proxy` (logged as security event)

### 5.2 DLP False Positives (Phase 2)

**Problem**: Presidio incorrectly scrubs legitimate data.

**Override**:
```bash
# For this session only
vibedom run --allow-pattern="Pearl St"

# Permanently for this workspace
echo "Pearl St" >> ~/projects/myapp/.vibedom/dlp_allowlist.txt
```

### 5.3 Overlay Filesystem Conflicts

**Problem**: User modifies host file while agent modifies same file in VM.

**Resolution**: Detect at session end, present conflict, offer manual merge options. No automatic locking (complexity vs benefit trade-off).

### 5.4 VM Crashes

**Problem**: apple/container VM hangs or crashes.

**Recovery**:
1. Watchdog detects missing heartbeat (30s timeout)
2. Save overlay to `~/.vibedom/crash-recovery/session-XXX/`
3. Offer to restart with recovered state

### 5.5 Deploy Key Issues

**Problem**: GitLab authentication fails.

**Guided Recovery**: Present checklist of common causes (key not added, wrong permissions, SSH host key changed) with actionable fixes.

## 6. Testing Strategy

### Phase 1 Tests

**VM Isolation**:
- Verify agent cannot access host filesystem outside mount
- Verify overlay FS writes don't affect read-only base
- Verify VM cleanup (no orphaned processes/files)

**Proxy**:
- Whitelist enforcement (allowed domain succeeds, blocked domain gets 403)
- Proxy bypass prevention (iptables forces all traffic through proxy)
- Proxy resilience (systemd restart on crash)

**Gitleaks**:
- Secret detection with categorization
- User can approve and continue
- Clean workspace starts without warnings

### Phase 2 Tests

**DLP**:
- .env scanning adds secrets to scrubbing rules
- Context-aware scrubbing (external vs internal destinations)
- Command injection blocking with alerts

**End-to-End**:
- Developer runs agent on real project
- Agent modifies files, runs tests
- Developer reviews diff, applies changes
- Verify complete audit trail

### Performance Benchmarks

| Target | Metric |
|--------|--------|
| < 45s  | Cold start (first run of day) |
| < 30s  | Warm start (VM image cached) |
| < 10s  | Resume from pause |
| < 5s   | Diff generation at session end |
| < 100ms | DLP scrubbing latency (Phase 2) |

### Security Validation

Before team rollout, security team penetration test:
- Path traversal attempts
- Symlink attacks
- Process escape techniques (nsenter, container breakouts)
- Network bypass attempts (raw sockets, DNS tunneling)

**Expected**: All attempts fail and are logged.

## 7. Implementation Phases

### Phase 1: Core Sandbox (Weeks 1-2)

**Goal**: Validate VM isolation + basic network control.

**Deliverables**:
- apple/container VM setup with overlay FS
- mitmproxy with whitelist enforcement
- Gitleaks pre-flight with review UI
- Basic logging (network.jsonl, session.log)
- Deploy key generation

**Success Criteria**: Developer can run agent in sandbox, modify files safely, review changes, and verify no external network access beyond whitelist.

### Phase 2: DLP Layer (Weeks 3-4)

**Goal**: Add intelligent scrubbing and monitoring.

**Deliverables**:
- Presidio integration with .env scanning
- Context-aware scrubbing rules
- Command injection detection
- Encrypted audit logs (dlp_audit.jsonl.enc)
- High-severity alerting (webhook/Slack)

**Success Criteria**: Agent can work on real projects with internal credentials, and all sensitive data to Anthropic is scrubbed while internal GitLab access works normally.

## 8. Open Questions

1. **VM Image Distribution**: Host pre-built image ourselves or build on first run?
2. **Logging Retention**: How long to keep session logs? Auto-purge policy?
3. **Multi-User**: If multiple devs use this, do they share `~/.vibedom/` or isolate per-user?
4. **Performance**: Is 400MB VM image download acceptable, or should we optimize size?

## 9. References

- **apple/container**: https://github.com/apple/container (Swift-based Virtualization.framework wrapper)
- **mitmproxy**: https://mitmproxy.org/ (Transparent HTTPS proxy)
- **Presidio**: https://microsoft.github.io/presidio/ (PII detection/anonymization)
- **Gitleaks**: https://github.com/gitleaks/gitleaks (Secret scanning)
