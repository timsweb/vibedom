#!/bin/bash
set -e

echo "Starting vibedom VM..."

# Setup overlay filesystem
echo "Setting up overlay filesystem..."
# Create tmpfs for overlay upper/work dirs (overlay doesn't support itself as upperdir)
mkdir -p /overlay
mount -t tmpfs tmpfs /overlay
mkdir -p /overlay/upper /overlay/work
mount -t overlay overlay -o lowerdir=/mnt/workspace,upperdir=/overlay/upper,workdir=/overlay/work /work

# Start SSH agent with deploy key
if [ -f /mnt/config/id_ed25519_vibedom ]; then
    eval $(ssh-agent -s)
    ssh-add /mnt/config/id_ed25519_vibedom 2>/dev/null || true
fi

# Setup iptables to redirect all HTTP/HTTPS to mitmproxy
echo "Configuring network interception..."
iptables -t nat -A OUTPUT -p tcp --dport 80 -j REDIRECT --to-port 8080
iptables -t nat -A OUTPUT -p tcp --dport 443 -j REDIRECT --to-port 8080

# Start mitmproxy (using mitmdump for non-interactive mode)
echo "Starting mitmproxy..."
mkdir -p /var/log/vibedom
mitmdump \
    --mode transparent \
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
