#!/usr/bin/env bash
set -euo pipefail
source .venv/bin/activate
eovrt-media run --config configs/dbe_yoloe_cr01_cr02.yaml
