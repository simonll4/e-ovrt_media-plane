# Deploy Validation Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Establish reproducible, evidence-backed deployment status before reconciling documentation and historical plan checkboxes.

**Architecture:** Validate in increasing-cost order: repository contracts, Docker daemon and GPU access, image builds, then an isolated local two-node run. Preserve all existing containers, images, volumes, and run artifacts; record any external block precisely rather than changing application code.

**Tech Stack:** Docker Compose v5, NVIDIA Container Toolkit, CUDA 12.6.3 image, pytest, Ruff.

**Constraint:** `docs/superpowers/plans/2026-06-24-infra-deploy.md` requires a single final commit for the whole workstream. Do not create intermediate commits while executing this validation layer.

---

### Task 1: Establish the static baseline

**Files:**
- Verify only: `deploy/docker-compose.yml`
- Verify only: `deploy/docker-compose.node-a.yml`
- Verify only: `deploy/docker-compose.node-b.yml`
- Verify only: `tests/test_deploy_contract.py`

- [x] **Step 1: Render each Compose manifest without starting services**

Run:

```bash
docker compose -f deploy/docker-compose.yml config --quiet
docker compose -f deploy/docker-compose.node-a.yml config --quiet
docker compose -f deploy/docker-compose.node-b.yml config --quiet
```

Expected: the three commands exit with status 0.

- [x] **Step 2: Run the deploy contract test in the project virtual environment**

Run:

```bash
.venv/bin/pytest -q tests/test_deploy_contract.py
```

Expected: 3 passed.

- [x] **Step 3: Run the complete Python validation baseline**

Run:

```bash
.venv/bin/pytest -q
.venv/bin/ruff check src tests
git diff --check
```

Expected: the suite and Ruff pass; `git diff --check` produces no output.

### Task 2: Verify Docker execution prerequisites

**Files:**
- Verify only: `deploy/docker/Dockerfile.node-b`

- [x] **Step 1: Confirm the Docker daemon is reachable and the validation project is not already running**

Run with permission to access `/var/run/docker.sock`:

```bash
docker info --format '{{.ServerVersion}} {{.Driver}}'
docker compose -p eovrt-deploy-validation -f deploy/docker-compose.yml ps --all
```

Expected: Docker prints its server version and storage driver; the project has no active services before the validation begins.

- [x] **Step 2: Confirm CUDA is available to Docker**

Run with permission to access the Docker daemon and GPU:

```bash
docker run --rm --gpus all nvidia/cuda:12.6.3-cudnn-runtime-ubuntu24.04 nvidia-smi
```

Expected: `nvidia-smi` reports at least one GPU. If it fails, retain the command output and stop before any image build; the outcome is `blocked externally`.

### Task 3: Build deterministic images

**Files:**
- Verify only: `deploy/docker/Dockerfile.node-a`
- Verify only: `deploy/docker/Dockerfile.node-b`

- [x] **Step 1: Build the edge image**

Run with permission to access Docker and image registries:

```bash
docker compose -p eovrt-deploy-validation -f deploy/docker-compose.yml build node-a
```

Expected: build exits 0 and installs the `edge` dependency set without Torch.

- [x] **Step 2: Build the GPU image**

Run with permission to access Docker and image registries:

```bash
docker compose -p eovrt-deploy-validation -f deploy/docker-compose.yml build node-b
```

Expected: build exits 0; the Dockerfile's `RUN test -s /app/mobileclip2_b.ts` step passes, proving the MobileCLIP asset is present in the image.

- [x] **Step 3: Record a build failure without altering source code** *(not applicable: both image builds passed)*

If either build fails, retain its complete command output and stop this plan. Classify the result as `blocked externally` when the failure is due to Docker, registry access, GPU runtime, unavailable model/dependency, or host capacity; otherwise open a separate debugging task before making any implementation change.

### Task 4: Execute an isolated local two-node run

**Files:**
- Verify only: `deploy/docker-compose.yml`
- Verify only: `deploy/configs/two_node_a.example.yaml`
- Verify only: `deploy/configs/two_node_b.example.yaml`
- Inspect: `runs/`

- [x] **Step 1: Create an evidence marker before starting the isolated stack**

Run:

```bash
touch /tmp/eovrt-deploy-validation.started
```

Expected: the marker exists and is newer than all subsequent validation artifacts.

- [x] **Step 2: Run the local stack under its own Compose project name**

Run with permission to access Docker and the GPU:

```bash
timeout 30m docker compose -p eovrt-deploy-validation -f deploy/docker-compose.yml up
```

Expected: Node A serves the configured image folder, Node B connects through `tcp://node-a:5555`, runs YOLOE on CUDA, and both services exit naturally after `END`. Do not use `--abort-on-container-exit` or `--exit-code-from`: the latter implies the former in Compose and can mask Node B's exit status.

- [x] **Step 3: Inspect container exits and artifacts created by this run**

Run:

```bash
docker compose -p eovrt-deploy-validation -f deploy/docker-compose.yml ps --all
find runs -type f -newer /tmp/eovrt-deploy-validation.started \( -name detections.jsonl -o -name summary.json -o -name errors.jsonl \) -print | sort
```

Expected: Node A and Node B both show `Exited (0)`; at least one new `detections.jsonl` and one new `summary.json` exist; `errors.jsonl` is absent or contains only recoverable errors.

- [x] **Step 4: Verify the generated summaries have no failed units**

Run:

```bash
.venv/bin/python -c 'import json, pathlib, sys; paths = list(pathlib.Path("runs").rglob("summary.json")); recent = [p for p in paths if p.stat().st_mtime >= pathlib.Path("/tmp/eovrt-deploy-validation.started").stat().st_mtime]; assert recent, "no new summary.json"; failed = [p for p in recent if json.loads(p.read_text()).get("units_failed") != 0]; assert not failed, failed; print("validated summaries:", *recent, sep="\\n")'
```

Expected: the command prints the newly generated summaries and exits 0.

- [x] **Step 5: Preserve Docker resources and report the evidence**

Do not run `docker compose down -v`, delete images, remove volumes, or delete any file under `runs/`. Report whether the result meets `validated E2E`, `validated static`, or `blocked externally` from the design specification.

## Execution record — 2026-06-24

- Static validation: the three Compose manifests rendered; `tests/test_deploy_contract.py`
  passed (3 tests); the complete suite passed (187 tests); Ruff and `git diff --check`
  were clean.
- Docker prerequisites: Docker Engine 29.5.3 with `overlayfs`; Docker exposed an NVIDIA
  GeForce RTX 4060 to `nvidia/cuda:12.6.3-cudnn-runtime-ubuntu24.04`.
- Images: Node A built without Torch (237 MB); Node B built at 5.55 GB with CLIP and
  `/app/mobileclip2_b.ts` present.
- E2E: `run_20260624_144813_ebe_yoloe_deterministic` completed on `cuda:0` with 114
  processed units, 0 failed units, 193 detections and an empty `errors.jsonl`.
- Observation for the next documentation layer: Node B emitted recoverable preview
  warnings because its two-host manifest deliberately does not mount the edge dataset.
