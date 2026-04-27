#!/usr/bin/env bash
# rescue-bird/scripts/setup.sh
# One-shot environment setup. Idempotent.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

echo "── rescue-bird setup ──"

command -v docker >/dev/null    || { echo "ERROR: docker not installed"; exit 1; }
command -v nvidia-smi >/dev/null || echo "WARNING: nvidia-smi not found — GPU passthrough won't work"

if [[ ! -f docker/.env ]]; then
    cp docker/.env.example docker/.env
    echo "Created docker/.env from template"
fi

mkdir -p runs models

echo "── Building images (slow on first run) ──"
docker compose -f docker/docker-compose.yml --env-file docker/.env build

# Model weight placeholders
mkdir -p models/edgetam models/yolov8 models/sam2
[[ -f models/edgetam/README.txt ]] || echo "TODO: drop EdgeTAM weights here" > models/edgetam/README.txt
[[ -f models/yolov8/README.txt  ]] || echo "TODO: drop YOLOv8 weights here"  > models/yolov8/README.txt
[[ -f models/sam2/README.txt    ]] || echo "TODO: drop SAM2 weights here"    > models/sam2/README.txt

# Host-side analysis deps
pip install --user --quiet pyarrow pandas numpy pyyaml tabulate 2>/dev/null || \
    echo "(skipped pip install — install pyarrow pandas numpy pyyaml tabulate manually if needed)"

echo "── setup complete. Next: ./scripts/run_sim.sh ──"
