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
    ssh-add /mnt/config/id_ed25519_vibedom
fi

# Start mitmproxy in background (will be configured in later task)
# mitmproxy --mode transparent --listen-port 8080 &

echo "VM ready!"

# Keep container running
tail -f /dev/null
