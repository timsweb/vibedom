#!/bin/bash
# Build Alpine Linux VM image for vibedom

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IMAGE_NAME="vibedom-alpine"

echo "Building VM image: $IMAGE_NAME"

# Build Docker image (we'll convert to apple/container format)
docker build -t "$IMAGE_NAME:latest" -f "$SCRIPT_DIR/Dockerfile.alpine" "$SCRIPT_DIR"

echo "✅ VM image built successfully: $IMAGE_NAME:latest"
echo ""
echo "Note: For production, this would be converted to apple/container format"
echo "      For now, we'll use Docker as a proof-of-concept"
