#!/usr/bin/env bash
# rescue-bird/scripts/run_mission.sh
# Run a named mission. Sets up RUN_ID and run directory, brings up the ROS 2
# stack with the right env vars, waits for the mission to complete, then
# runs the SoC partition report.
#
# Usage:
#     ./scripts/run_mission.sh <mission_name> [--target imx95]
# Example:
#     ./scripts/run_mission.sh rescue_bird_full --target imx95

set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

MISSION="${1:-search_pattern}"
TARGET=""
shift || true
while [[ $# -gt 0 ]]; do
    case "$1" in
        --target) TARGET="$2"; shift 2 ;;
        *)        echo "Unknown arg: $1"; exit 1 ;;
    esac
done

MISSION_FILE="missions/${MISSION}.yaml"
[[ -f "$MISSION_FILE" ]] || { echo "Mission not found: $MISSION_FILE"; exit 1; }

# Run identity
RUN_ID="$(date -u +%Y-%m-%dT%H-%M-%S)"
RUN_DIR="runs/${RUN_ID}"
mkdir -p "$RUN_DIR"
echo "$MISSION" > "$RUN_DIR/mission.txt"
cp "$MISSION_FILE" "$RUN_DIR/mission.yaml"

echo "── Run ${RUN_ID}  mission=${MISSION} ──"

# Bring up the stack (perception + comms + behavior + telemetry).
# Sim should already be running in another terminal via run_sim.sh.
RUN_ID="$RUN_ID" \
RUN_DIR="/runs/${RUN_ID}" \
MISSION="/opt/missions/${MISSION}.yaml" \
docker compose -f docker/docker-compose.yml --env-file docker/.env \
    up --abort-on-container-exit \
    perception comms behavior &

COMPOSE_PID=$!

# Wait for the mission duration (read from yaml)
DURATION=$(awk '/^duration_s:/ {print $2}' "$MISSION_FILE")
DURATION="${DURATION:-180}"
echo "── Mission running for ${DURATION}s ──"
sleep "$DURATION"

# Tear down
docker compose -f docker/docker-compose.yml --env-file docker/.env \
    stop perception comms behavior

wait "$COMPOSE_PID" 2>/dev/null || true

# Generate report
echo "── Generating SoC partition report ──"
TARGET_FLAG=""
[[ -n "$TARGET" ]] && TARGET_FLAG="--target $TARGET"
python3 instrumentation/analysis/soc_partition_report.py "$RUN_DIR" $TARGET_FLAG || \
    echo "(report generation failed — check Parquet files in $RUN_DIR)"

echo "── Done. Output: $RUN_DIR ──"
