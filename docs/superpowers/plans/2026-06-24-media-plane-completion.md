# Media Plane Completion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement every declared media-plane capability except OAK-D Pro PoE.

**Architecture:** Complete wire formats and liveness first, then direct model input and payload previews. The producer/consumer boundary remains unchanged: normalized units flow over ZeroMQ and the consumer owns inference and artifacts.

**Tech Stack:** Python, NumPy, PyTorch, Transformers, Ultralytics, OpenCV, pyzmq, pytest, Docker Compose.

**Constraint:** The current workstream has one final commit only; do not commit individual tasks.

---

### Task 1: Implement FP16 payloads

**Files:** `preprocessing/normalizer.py`, `transport/serialization.py`, `config/loader.py`, `contracts/normalized_unit.py`, `tests/test_normalizer.py`, `tests/test_serialization.py`, `tests/test_config_deployment.py`.

- [x] **Step 1: Write failing tests**

Replace the FP16 rejection test with a normalization assertion: `payload.dtype == np.float16`, values lie in `[0, 1]`, and `payload_format == PayloadFormat.FP16`. Extend `_make_unit` and serialization tests with an FP16 raw round-trip asserting dtype, shape and `np.allclose(..., atol=1e-3)`. Replace the loader test that expects `NotImplementedError` with a successful load.

- [x] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest -q tests/test_normalizer.py tests/test_serialization.py tests/test_config_deployment.py`

Expected: FP16 gate and missing dtype mapping fail.

- [x] **Step 3: Implement FP16**

Remove the FP16 exception in `normalize_spatial` and use `payload.astype(np.float16) / np.float16(255.0)`. Add `PayloadFormat.FP16: np.float16` to `_DTYPE_BY_FORMAT`, remove the loader rejection, and change enum comments to implemented. JPEG remains raw for non-uint8 payloads.

- [x] **Step 4: Verify FP16**

Run: `.venv/bin/pytest -q tests/test_normalizer.py tests/test_serialization.py tests/test_config_deployment.py tests/test_network_transport.py`

Expected: PASS.

### Task 2: Add dedicated PUSH/PULL heartbeat

**Files:** `config/schemas.py`, `config/loader.py`, `transport/network.py`, `transport/factory.py`, `runtime/two_node.py`, both `deploy/configs/two_node_*.example.yaml`, `deploy/docker-compose.node-a.yml`, `tests/test_network_transport.py`, `tests/test_config_deployment.py`.

- [x] **Step 1: Write failing liveness tests**

Create producer and consumer with a second loopback endpoint. Assert the producer becomes alive without any `request()`, then becomes dead after consumer shutdown and the configured timeout. Add a config test requiring `heartbeat_endpoint` for network transport.

- [x] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest -q tests/test_network_transport.py tests/test_config_deployment.py`

Expected: missing endpoint and dedicated heartbeat behavior.

- [x] **Step 3: Implement dedicated liveness**

Add `heartbeat_endpoint: str | None` to `TransportConfig`; loader requires it for network. Producer binds PULL and polls `HEARTBEAT`; consumer connects PUSH and sends it from a daemon thread every interval. Pass the endpoint through factory and two-node runtime. `shutdown()` stops/joins the thread and closes sockets idempotently. `is_peer_alive()` reads only heartbeat activity. Set Node A `tcp://0.0.0.0:5556`, local Node B `tcp://node-a:5556`, and publish `5556:5556` on edge.

- [x] **Step 4: Verify heartbeat**

Run: `.venv/bin/pytest -q tests/test_network_transport.py tests/test_config_deployment.py`

Expected: PASS.

### Task 3: Use shared tensor preparation in both adapters

**Files:** `models/grounding_dino_adapter.py`, `models/yoloe_adapter.py`, `tests/test_gdino_runtime.py`, `tests/test_yoloe_runtime.py`.

- [x] **Step 1: Write failing forward tests**

Use a float16 `NormalizedUnit`; monkeypatch each module's `prepare_model_input` to return a sentinel BCHW tensor. Assert each forward path sends the sentinel into inference and patch `PIL.Image.fromarray` to raise, proving forward does not create PIL.

- [x] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest -q tests/test_gdino_runtime.py tests/test_yoloe_runtime.py`

Expected: current PIL conversion fails the assertions.

- [x] **Step 3: Implement tensor forwards**

GDINO creates text-only processor inputs and supplies common `pixel_values`; YOLOE passes the common BCHW tensor as `source`. Preserve prompts, postprocessing, `device`, confidence/IoU and runtime half precision. No forward method rescales FP16 through uint8.

- [x] **Step 4: Verify adapter behavior**

Run: `.venv/bin/pytest -q tests/test_gdino_runtime.py tests/test_yoloe_runtime.py tests/test_normalizer.py`

Expected: PASS.

### Task 4: Produce previews from payload

**Files:** `visualize.py`, `runtime/pipeline.py`, `tests/test_visualize.py`, `tests/test_pipeline_two_threads.py`.

- [x] **Step 1: Write failing preview tests**

Test a new RGB-array renderer with uint8 and float16 payloads and a nonexistent source path. Add a pipeline test with `source_path=None`, previews enabled and an assertion for `previews/unit-1.preview.jpg`.

- [x] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest -q tests/test_visualize.py tests/test_pipeline_two_threads.py`

Expected: no array renderer and no source-less preview.

- [x] **Step 3: Implement payload previews**

Add `draw_detections_rgb(image_rgb, detections, output_path)`: convert `[0,1]` float values to RGB uint8, convert to BGR for OpenCV and write. In `run_consumer_loop`, call it after inference and before coordinate reprojection, with `raw_detections` and `item.payload`; retain `preview_max` and send preview write errors to the existing recoverable error path.

- [x] **Step 4: Verify previews**

Run: `.venv/bin/pytest -q tests/test_visualize.py tests/test_pipeline_two_threads.py tests/test_cli_two_node.py`

Expected: PASS without Node B reading edge source paths.

### Task 5: Document and verify closure

**Files:** `deploy/README.md`, `docs/implementation-status.md`, `docs/architecture.md`, active Superpowers plans.

- [x] **Step 1: Update operational documentation**

Document port 5556, FP16 raw wire, shared tensor input and payload previews. Mark only OAK-D deferred. Update Superpowers checkboxes from executed evidence and align MobileCLIP wording with `MobileCLIPTS`.

- [x] **Step 2: Run final validation**

Run `.venv/bin/pytest -q`, `.venv/bin/ruff check src tests`, all three `docker compose ... config --quiet`, `docker compose -p eovrt-deploy-validation -f deploy/docker-compose.yml build --quiet node-a node-b`, and `git diff --check`.

Expected: every command exits 0.

- [x] **Step 3: Run FP16 Docker E2E and prepare final commit**

Use ignored local deploy configs selecting `payload_format: fp16` and explicit data/heartbeat endpoints. Assert a new summary has `device: cuda:0`, `units_processed > 0`, `units_failed == 0`. Review the staged diff and create the single commit only with user approval.

## Execution record — 2026-06-24

- FP16 normalization, raw serialization and network configuration are covered by the focused
  suites. The complete local suite passed with **204 tests**.
- Dedicated heartbeat, direct tensor inputs and payload previews passed their focused suites
  (28, 17 and 14 tests respectively).
- Final validation passed: **204 tests**, Ruff, the three Compose manifests, both Docker image
  builds and `git diff --check` completed without errors.
- Docker FP16 E2E: `run_20260624_224818_ebe_yoloe_deterministic` ran on `cuda:0` with
  `payload_format: fp16`; it processed 1 unit, failed 0, produced 9 detections and one preview,
  left `errors.jsonl` empty, and both containers exited 0.
- The workstream is ready for its single final commit; no commit was created during this plan.
