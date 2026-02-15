#!/bin/bash
# Build Alpine Linux VM image for vibedom
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IMAGE_NAME="vibedom-alpine"

# Detect container runtime
if command -v container &>/dev/null; then
    RUNTIME="apple/container"
    BUILD_CMD="container build"
elif command -v docker &>/dev/null; then
    RUNTIME="docker"
    BUILD_CMD="docker build"
else
    echo "Error: No container runtime found. Install apple/container (macOS 26+) or Docker."
    exit 1
fi

echo "Building VM image: $IMAGE_NAME (using $RUNTIME)"

# Add DNS servers to resolve build issues
$BUILD_CMD --dns 8.8.8.8 --dns 1.1.1.1 -t "$IMAGE_NAME:latest" -f "$SCRIPT_DIR/Dockerfile.alpine" "$SCRIPT_DIR"

echo "✅ VM image built successfully: $IMAGE_NAME:latest"
