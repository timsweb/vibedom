#!/bin/bash
set -e

echo "Starting vibedom VM..."

# Setup overlay filesystem
echo "Setting up overlay filesystem..."
# Note: overlay mount doesn't work well in Docker Desktop on macOS
# Use cp -a to copy workspace to /work (which is writable)
# This simulates overlay behavior for the PoC
if [ -d /mnt/workspace ] && [ "$(ls -A /mnt/workspace 2>/dev/null)" ]; then
    cp -a /mnt/workspace/. /work/
fi

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
