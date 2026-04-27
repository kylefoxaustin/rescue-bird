#!/usr/bin/env bash
# rescue-bird/scripts/run_sim.sh
# Bring up Gazebo + PX4 SITL. Usually run in its own terminal — leave it
# running while you fire missions from another terminal via run_mission.sh.

set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

xhost +local:docker 2>/dev/null || true   # allow GUI from container

docker compose -f docker/docker-compose.yml --env-file docker/.env \
    up sim
