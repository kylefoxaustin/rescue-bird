#!/usr/bin/env bash
# Started inside the sim container. Brings up PX4 SITL with the configured
# airframe + world.

set -euo pipefail
source /opt/ros/humble/setup.bash

PX4_DIR="/opt/PX4-Autopilot"
cd "$PX4_DIR"

WORLD="${PX4_GZ_WORLD:-search_area}"
MODEL="${PX4_SIM_MODEL:-gazebo-classic_iris}"

echo "── Starting PX4 SITL  model=${MODEL}  world=${WORLD} ──"

# Use Gazebo Classic for now (more stable + better tooling than Garden for SITL today).
# Switch to gz (Garden) by changing the make target if you need higher fidelity.
HEADLESS=0 PX4_GZ_WORLD="$WORLD" make px4_sitl "$MODEL"
