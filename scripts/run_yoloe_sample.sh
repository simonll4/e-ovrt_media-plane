#!/usr/bin/env bash
set -euo pipefail
source .venv/bin/activate
eovrt-media run --config configs/runs/yoloe.yaml
