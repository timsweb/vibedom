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

## DLP (Data Loss Prevention)

Real-time scrubbing of secrets and PII from HTTP traffic.

### Two Enforcement Points

```
Pre-flight (before VM):    Gitleaks binary → scans workspace files
Runtime (inside VM):       DLP scrubber → scrubs HTTP traffic
                           ↑ Same gitleaks.toml patterns
```

### What Gets Scrubbed

**Secrets** (patterns from `lib/vibedom/config/gitleaks.toml`):
- API keys (AWS, Stripe, OpenAI, GitHub, GitLab, Slack)
- Database connection strings and passwords
- Private keys, JWTs, bearer tokens

**PII** (built-in patterns):
- Email addresses, credit card numbers
- US Social Security numbers, phone numbers
- Private IP addresses

### How It Works

1. Agent makes HTTP request with body containing secrets
2. Mitmproxy addon scrubs request body, response body, and sensitive headers
3. Secrets replaced with `[REDACTED_PATTERN_NAME]` placeholders
4. Request forwarded with scrubbed content (agent flow uninterrupted)
5. All scrubbed findings logged to `network.jsonl` for audit

### Design Decisions

- **Scrub, don't block**: Agent workflow continues uninterrupted
- **No Presidio**: Custom regex is lighter (0 deps vs 150-500MB) and catches API keys which Presidio cannot
- **Shared patterns**: gitleaks.toml serves both pre-flight and runtime detection
- **Content-type aware**: Only scrubs text content (skips binary)
- **Size-limited**: Skips bodies >512KB for performance

## Future Enhancements

- Context-aware rules (internal vs external traffic)
- High-severity real-time alerting
- Metrics and dashboards
