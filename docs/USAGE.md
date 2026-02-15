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
3. Start VM with workspace mounted as read-only
4. Clone/create git repository in isolated session
5. Launch mitmproxy

The sandbox is now running. You can:

- Run your AI agent inside the container:
  ```bash
  docker exec -it vibedom-myapp claude-code
  ```

- Inspect the git repository:
  ```bash
  docker exec -it vibedom-myapp sh -c "cd /work/repo && git log --oneline"
  ```

- Monitor network requests:
  ```bash
  tail -f ~/.vibedom/logs/session-*/network.jsonl
  ```

## Working with Git Bundles

### Starting a Session

When you start a vibedom session, the container clones your workspace repository and checks out your current branch:

```bash
# On your feature branch
git checkout feature/add-authentication
vibedom run ~/projects/myapp
```

The agent will work on the same branch (`feature/add-authentication`) inside an isolated git repository.

### Testing Changes Mid-Session

You can fetch from the live repository to test changes while the session is still running:

```bash
# Add live repo as remote (once per session)
git remote add vibedom-live ~/.vibedom/sessions/session-20260214-123456/repo

# Fetch latest commits anytime
git fetch vibedom-live

# Create test branch
git checkout -b test-changes vibedom-live/feature/add-authentication

# Test the changes
npm test
npm run dev

# Session continues...
```

### Reviewing and Merging Changes

After stopping the session, a git bundle is created:

```bash
vibedom stop ~/projects/myapp
# Creates bundle at ~/.vibedom/sessions/session-xyz/repo.bundle
```

**Add bundle as remote and review:**

```bash
git remote add vibedom-xyz ~/.vibedom/sessions/session-xyz/repo.bundle
git fetch vibedom-xyz

# Review commits
git log vibedom-xyz/feature/add-authentication
git log --oneline vibedom-xyz/feature/add-authentication ^feature/add-authentication

# Review changes
git diff feature/add-authentication..vibedom-xyz/feature/add-authentication
```

**Merge (keep commit history):**

```bash
git checkout feature/add-authentication
git merge vibedom-xyz/feature/add-authentication
```

**Merge (squash commits):**

```bash
git checkout feature/add-authentication
git merge --squash vibedom-xyz/feature/add-authentication
git commit -m "Implement authentication system

Agent implemented:
- User login/logout endpoints
- JWT token generation
- Password hashing
"
```

**Push for peer review:**

```bash
git push origin feature/add-authentication
# Create Merge Request in GitLab
```

**Cleanup:**

```bash
git remote remove vibedom-xyz
```

### Session Management

**List sessions:**

```bash
ls ~/.vibedom/logs/
```

**Clean up old sessions:**

```bash
rm -rf ~/.vibedom/logs/session-20260214-123456
```

### Troubleshooting

**Bundle creation failed:**

If bundle creation fails, the live repo is still available:

```bash
git remote add vibedom-live ~/.vibedom/sessions/session-xyz/repo
git fetch vibedom-live
# Manually create bundle:
cd ~/.vibedom/sessions/session-xyz/repo
git bundle create ../repo.bundle --all
```

**Non-git workspace:**

If your workspace isn't a git repository, vibedom will initialize a fresh repo with an initial snapshot commit.

## Stopping a Sandbox

```bash
vibedom stop ~/projects/myapp
```

This will:
1. Create a git bundle from the session repository
2. Display instructions for reviewing and merging changes
3. Stop and remove the container
4. Finalize session logs

The bundle contains all commits made by the agent and can be reviewed and merged into your workspace.

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
- cargo (Rust packages)
- Go tools (go get)
- Most language HTTP clients (requests, axios, etc.)

**Tools that may need configuration:**
- Docker client: Set HTTP_PROXY in daemon config
- Java applications: May need -Dhttp.proxyHost/-Dhttp.proxyPort
- Custom binaries: Check tool documentation for proxy support

## Data Loss Prevention (DLP)

Vibedom automatically scrubs secrets and PII from HTTP traffic to prevent data exfiltration.

### What Gets Scrubbed

| Category | Examples | Replaced With |
|----------|----------|---------------|
| AWS Keys | `AKIAIOSFODNN7EXAMPLE` | `[REDACTED_AWS_ACCESS_KEY]` |
| API Keys | `sk_test_...`, `sk-proj-...` | `[REDACTED_STRIPE_API_KEY]` etc. |
| Tokens | `ghp_...`, `glpat-...` | `[REDACTED_GITHUB_PAT]` etc. |
| Passwords | `password=secret123` | `[REDACTED_GENERIC_PASSWORD]` |
| Private Keys | `-----BEGIN RSA PRIVATE KEY-----` | `[REDACTED_PRIVATE_KEY]` |
| Emails | `user@company.com` | `[REDACTED_EMAIL]` |
| Credit Cards | `4111111111111111` | `[REDACTED_CREDIT_CARD]` |

### How It Works

- Requests are **scrubbed, not blocked** — the agent continues working normally
- Only text-based content is scrubbed (JSON, form data, plain text)
- Binary content (images, archives) passes through unchanged
- All scrubbed items are logged for audit

### Viewing Scrubbed Activity

```bash
# View all requests where scrubbing occurred
cat ~/.vibedom/logs/session-*/network.jsonl | python3 -c "
import sys, json
for line in sys.stdin:
    entry = json.loads(line)
    if 'scrubbed' in entry:
        print(json.dumps(entry, indent=2))
"
```

### Adding Custom Secret Patterns

Edit `lib/vibedom/config/gitleaks.toml` to add patterns. The same file is used for both pre-flight scanning (Gitleaks) and runtime scrubbing (DLP):

```toml
[[rules]]
id = "my-internal-token"
description = "Internal Service Token"
regex = '''myco_token_[a-zA-Z0-9]{32}'''
tags = ["internal", "token"]
```

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

### Git repository not initialized

If the container fails to initialize the git repository, check:
1. Is the workspace a git repository?
2. Is the `.git` directory accessible?
3. Check container logs for specific errors

```bash
docker logs vibedom-<name>
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
