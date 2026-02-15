#!/bin/bash
# Build Alpine Linux VM image for vibedom
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IMAGE_NAME="vibedom-alpine"
RUNTIME=""

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --runtime|-r)
            RUNTIME="$2"
            shift 2
            ;;
        *)
            echo "Unknown option: $1"
            echo "Usage: $0 [--runtime|-r (auto|docker|apple)]"
            exit 1
            ;;
    esac
done

# Detect or use specified runtime
if [ -z "$RUNTIME" ] || [ "$RUNTIME" = "auto" ]; then
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
elif [ "$RUNTIME" = "apple" ]; then
    if ! command -v container &>/dev/null; then
        echo "Error: apple/container runtime requested but not found on system."
        exit 1
    fi
    BUILD_CMD="container build"
elif [ "$RUNTIME" = "docker" ]; then
    if ! command -v docker &>/dev/null; then
        echo "Error: Docker runtime requested but not found on system."
        exit 1
    fi
    BUILD_CMD="docker build"
else
    echo "Error: Invalid runtime. Must be 'auto', 'docker', or 'apple'."
    exit 1
fi

echo "Building VM image: $IMAGE_NAME (using $RUNTIME)"

# Build with explicit DNS for Docker (workaround for DNS issues)
if [ "$RUNTIME" = "docker" ]; then
    $BUILD_CMD --dns 8.8.8.8 --dns 1.1.1.1 -t "$IMAGE_NAME:latest" -f "$SCRIPT_DIR/Dockerfile.alpine" "$SCRIPT_DIR"
else
    $BUILD_CMD -t "$IMAGE_NAME:latest" -f "$SCRIPT_DIR/Dockerfile.alpine" "$SCRIPT_DIR"
fi

echo "✅ VM image built successfully: $IMAGE_NAME:latest"
