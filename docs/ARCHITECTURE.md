# Architecture

See [design document](plans/2026-02-13-ai-agent-sandbox-design.md) for full details.

## Components

### VM Layer
- Alpine Linux on apple/container (Docker for PoC)
- OverlayFS for read-only workspace with writable overlay
- iptables for forcing traffic through proxy

### Network Layer
- mitmproxy in transparent mode
- Custom addon for whitelist enforcement
- Structured logging to network.jsonl

### Security Layer
- Gitleaks pre-flight scanning
- SSH deploy keys (not personal keys)
- Session audit logs

## Data Flow

```
User runs: vibedom run ~/project
  ↓
Pre-flight: Gitleaks scan → user reviews findings
  ↓
VM start: Mount workspace (read-only) + create overlay
  ↓
Proxy: mitmproxy starts, iptables redirects all traffic
  ↓
Agent: Works in /work (overlay), network filtered
  ↓
Stop: Generate diff, user reviews, optionally applies
  ↓
Cleanup: VM destroyed, logs saved
```

## Future: Phase 2

- Presidio DLP for intelligent scrubbing
- Context-aware rules (external vs internal)
- Real-time alerting for high-severity events
