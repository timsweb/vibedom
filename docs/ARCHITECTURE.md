# Architecture

See [design document](plans/2026-02-13-ai-agent-sandbox-design.md) for full details.

## Components

### VM Layer
- Alpine Linux on apple/container (Docker for PoC)
- OverlayFS for read-only workspace with writable overlay
- iptables for forcing traffic through proxy

### Network Layer
- mitmproxy in explicit proxy mode (HTTP_PROXY/HTTPS_PROXY)
- Custom addon for whitelist enforcement and DLP scrubbing
- Structured logging to network.jsonl (includes scrubbing audit trail)

### Security Layer
- Gitleaks pre-flight scanning (secrets in workspace files)
- DLP runtime scrubbing (secrets and PII in HTTP traffic)
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

## DLP Runtime Scrubbing

**Threat Model:** Prevent prompt injection attacks from exfiltrating secrets found in workspace to external endpoints.

**What We Scrub:**
- Request bodies (main exfiltration vector for large secrets like API keys, connection strings)
- URL query parameters (catches `?api_key=xxx` exfiltration)

**What We Don't Scrub:**
- Request headers (needed for legitimate API calls to Anthropic, Context7, etc.)
- Response bodies (API data entering the VM is not a threat)

**Implementation:**
- Chunked processing for large files (no size bypass)
- Go/Python regex compatibility warnings
- Pattern validation on startup

## Future Enhancements

- Context-aware rules (internal vs external traffic)
- High-severity real-time alerting
- Metrics and dashboards
