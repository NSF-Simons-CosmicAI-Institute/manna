#!/usr/bin/env bash
# Build the gp13 single-user image, using THIS directory as the build context
# (the repo-root .dockerignore hides docs/, so a root context can't see the hook
# or config). Run from anywhere.
#
#   ./build.sh
#   BASE_IMAGE=<adl-notebook-base> ./build.sh   # gp13's real base, once known
#
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

IMAGE="${IMAGE:-astro-archives-singleuser:dev}"
BASE_IMAGE="${BASE_IMAGE:-quay.io/jupyter/minimal-notebook:latest}"

echo "Building $IMAGE  (BASE_IMAGE=$BASE_IMAGE)"
docker build -t "$IMAGE" --build-arg BASE_IMAGE="$BASE_IMAGE" "$HERE"
echo "Built $IMAGE — smoke-test with:  IMAGE=$IMAGE $HERE/smoke-test.sh"
