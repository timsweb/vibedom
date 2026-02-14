# Usage Guide

## First-Time Setup

1. Set up virtual environment:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```

2. Install vibedom:
   ```bash
   pip install -e .
   ```

3. Initialize:
   ```bash
   vibedom init
   ```

4. Add the displayed SSH public key to your GitLab account:
   - GitLab → Settings → SSH Keys
   - Paste the key shown by `vibedom init`

5. Edit `~/.vibedom/trusted_domains.txt` to add your internal domains

## Running a Sandbox

```bash
vibedom run ~/projects/myapp
```

This will:
1. Scan workspace for secrets (Gitleaks)
2. Show findings for review
3. Start VM with workspace mounted
4. Launch mitmproxy

The sandbox is now running. You can:

- Run your AI agent inside the container:
  ```bash
  docker exec -it vibedom-myapp claude-code
  ```

- Inspect the overlay:
  ```bash
  docker exec -it vibedom-myapp ls /work
  ```

- Monitor network requests:
  ```bash
  tail -f ~/.vibedom/logs/session-*/network.jsonl
  ```

## Stopping a Sandbox

```bash
vibedom stop ~/projects/myapp
```

You'll see a diff of changes made by the agent. Choose:
- **Yes**: Apply changes to your workspace
- **No**: Discard all changes
- **Review**: Open diff in your editor

## Network Whitelisting

The sandbox enforces domain whitelisting for both HTTP and HTTPS traffic.

### Adding Domains

Edit `~/.vibedom/trusted_domains.txt`:

```
pypi.org
npmjs.com
github.com
gitlab.com
```

### Testing Network Access

```bash
# Inside sandbox
curl https://pypi.org/simple/    # ✅ Whitelisted, succeeds
curl https://example.com/         # ❌ Not whitelisted, blocked
```

### How It Works

Vibedom uses mitmproxy in explicit proxy mode with HTTP_PROXY/HTTPS_PROXY environment variables. Most modern tools (curl, pip, npm, git) respect these variables automatically.

**Supported tools:**
- curl, wget, httpie
- pip (Python packages)
- npm, yarn (Node.js packages)
- git (over HTTPS)
- Most language HTTP clients (requests, axios, etc.)

**Tools that may need configuration:**
- Docker client: Set HTTP_PROXY in daemon config
- Java applications: May need -Dhttp.proxyHost/-Dhttp.proxyPort
- Custom binaries: Check tool documentation for proxy support

## Troubleshooting

### "Domain not whitelisted"

Add the domain to `~/.vibedom/trusted_domains.txt`:

```bash
echo "new-domain.com" >> ~/.vibedom/trusted_domains.txt
```

Then restart the sandbox.

### "Gitleaks found secrets"

Review the findings:
- **LOW_RISK** (local dev): Safe to continue
- **MEDIUM_RISK**: Will be scrubbed by DLP (Phase 2)
- **HIGH_RISK**: Fix before continuing

### VM won't start

Check Docker:
```bash
docker ps -a | grep vibedom
docker logs vibedom-<name>
```

Rebuild VM image:
```bash
./vm/build.sh
```

## Advanced

### Attach to running VM

```bash
docker exec -it vibedom-<workspace-name> sh
```

### Inspect logs

```bash
ls ~/.vibedom/logs/session-*/
cat ~/.vibedom/logs/session-*/session.log
```

### Clean up old sessions

```bash
rm -rf ~/.vibedom/logs/session-*
```
