# Deploy two-host alignment — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the deploy artifacts support both local two-container execution and real two-host deployment without hidden services or runtime downloads.

**Architecture:** Keep `docker-compose.yml` as the local integration stack and add a compose file per independently deployed node. Pin the CLIP source revision and materialize the MobileCLIP asset at image build time, so Node B starts without Internet.

**Tech Stack:** Docker Compose, NVIDIA CUDA image, Python/pytest, Ultralytics YOLOE.

---

### Task 1: Specify deployment-mode contracts

**Files:**
- Create: `tests/test_deploy_contract.py`

- [x] **Step 1: Write failing tests**

Assert that the local stack has both services and `node-b.depends_on == ["node-a"]`; assert that the Node A and Node B host manifests each define exactly one service and Node B has no `depends_on`; assert that Node B installs CLIP from a full commit SHA and downloads `mobileclip2_b.ts` during the Docker build.

- [x] **Step 2: Run the test to verify it fails**

Run: `pytest -q tests/test_deploy_contract.py`

Expected: FAIL because no dedicated two-host manifests exist and the CLIP dependency is unpinned.

### Task 2: Implement isolated host manifests and deterministic model provisioning

**Files:**
- Create: `deploy/docker-compose.node-a.yml`
- Create: `deploy/docker-compose.node-b.yml`
- Modify: `deploy/docker/Dockerfile.node-b`

- [x] **Step 1: Add Node A manifest**

Define only `node-a`, keep the producer command/config and mounts, publish `5555:5555` for data
and `5556:5556` for the dedicated heartbeat, and remove bridge-network-only assumptions.

- [x] **Step 2: Add Node B manifest**

Define only `node-b`, keep config/models/runs mounts and GPU reservation, and omit `depends_on` and Node A.

- [x] **Step 3: Pin build dependencies and cache the model**

Install CLIP by immutable commit SHA and execute a Python build step that invokes `MobileCLIPTS` so the `mobileclip2_b.ts` TorchScript asset exists in the image before runtime.

- [x] **Step 4: Run contract tests**

Run: `pytest -q tests/test_deploy_contract.py`

Expected: PASS.

### Task 3: Align user-facing documentation and validate operational artifacts

**Files:**
- Modify: `deploy/README.md`
- Modify: `deploy/.env.example`
- Modify: `docs/superpowers/specs/2026-06-24-infra-deploy-design.md`
- Modify: `docs/superpowers/plans/2026-06-24-infra-deploy.md`

- [x] **Step 1: Document the explicit compose commands**

Describe `docker compose -f docker-compose.yml` for local integration; `docker compose -f docker-compose.node-a.yml` on edge; `docker compose -f docker-compose.node-b.yml` on GPU. State the exposed port and that Node B starts offline after image construction.

- [x] **Step 2: Align CUDA version and environment-template scope**

Use CUDA 12.6.3 in the GPU verification command. Clarify that `.env.example` belongs to the local stack while the host manifests consume the same `NODE_*_CONFIG` variables.

- [x] **Step 3: Validate**

Run: `docker compose -f docker-compose.yml config`, `docker compose -f docker-compose.node-a.yml config`, `docker compose -f docker-compose.node-b.yml config`, `pytest -q`, `ruff check src tests`, and build Node B.

Expected: all Compose manifests parse; tests and lint pass; Node B builds successfully with its model asset already materialized.

## Execution record — 2026-06-24

- `tests/test_deploy_contract.py` passed (3 tests); the local stack and the two independent-host
  manifests rendered successfully.
- Docker built both images and the local CUDA stack completed with 114 processed units, 0 failed
  units and `mobileclip2_b.ts` present in Node B.
