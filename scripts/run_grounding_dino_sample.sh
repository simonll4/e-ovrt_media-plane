#!/usr/bin/env bash
set -euo pipefail
source .venv/bin/activate
eovrt-media run --config ../e-ovrt_experimental-setup/experiments/gdino.yaml
