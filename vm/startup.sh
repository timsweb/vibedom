#!/bin/bash
set -e

echo "Starting vibedom VM..."

# Initialize git repository from workspace
if [ -d /mnt/workspace/.git ]; then
    echo "Cloning git repository from workspace..."
    git clone /mnt/workspace/.git /work/repo
    cd /work/repo

    # Checkout the same branch user is on
    CURRENT_BRANCH=$(git -C /mnt/workspace rev-parse --abbrev-ref HEAD 2>/dev/null || echo "main")
    echo "Detected branch: $CURRENT_BRANCH"

    # Checkout branch (create if doesn't exist locally)
    if git show-ref --verify --quiet refs/heads/"$CURRENT_BRANCH"; then
        git checkout "$CURRENT_BRANCH"
    else
        git checkout -b "$CURRENT_BRANCH"
    fi

    echo "Working on branch: $CURRENT_BRANCH"
else
    echo "Non-git workspace, initializing fresh repository..."
    mkdir -p /work/repo
    rsync -a --exclude='.git' /mnt/workspace/ /work/repo/ || true
    cd /work/repo
    git init
    
    # Set git identity for agent commits
    git config user.name "Vibedom Agent"
    git config user.email "agent@vibedom.local"
    
    git add .
    git commit -m "Initial snapshot from vibedom session" || echo "No files to commit"
fi

# Set git identity for agent commits (for git workspaces)
git config user.name "Vibedom Agent"
git config user.email "agent@vibedom.local"

echo "Git repository initialized at /work/repo"

# Start SSH agent with deploy key
if [ -f /mnt/config/id_ed25519_vibedom ]; then
    eval $(ssh-agent -s)
    ssh-add /mnt/config/id_ed25519_vibedom 2>/dev/null || true
fi

# Proxy environment variables are set by container runtime (-e flags)
# and are available to all processes including docker exec sessions
echo "Configuring explicit proxy mode..."
echo "Proxy environment: HTTP_PROXY=$HTTP_PROXY HTTPS_PROXY=$HTTPS_PROXY"

# Start mitmproxy (using mitmdump for non-interactive mode)
echo "Starting mitmproxy..."
mkdir -p /var/log/vibedom
mitmdump \
    --mode regular \
    --listen-port 8080 \
    --set confdir=/tmp/mitmproxy \
    -s /mnt/config/mitmproxy_addon.py \
    > /var/log/vibedom/mitmproxy.log 2>&1 &

# Wait for mitmproxy to generate certificate
sleep 2

# Install mitmproxy CA certificate
echo "Installing mitmproxy CA certificate..."
if [ -f /tmp/mitmproxy/mitmproxy-ca-cert.pem ]; then
    cp /tmp/mitmproxy/mitmproxy-ca-cert.pem /usr/local/share/ca-certificates/mitmproxy.crt
    update-ca-certificates

    # Also set environment variables for tools that don't use system certs
    export REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt
    export SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt
    export CURL_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt
fi

# Signal readiness
touch /tmp/.vm-ready

echo "VM ready!"

# Keep container running
tail -f /dev/null
