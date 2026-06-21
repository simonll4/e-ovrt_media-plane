# Prueba RTSP EZVIZ con YOLOE en un solo host — Plan de Implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ejecutar una validación reproducible de una cámara EZVIZ RTSP usando YOLOE-26s en `cuda:0`, sin versionar la URI ni las credenciales.

**Architecture:** La corrida usa el pipeline `single_host`: `RtspSource` lee el stream, `bounded_freshness` conserva los frames recientes en memoria y YOLOE-26s procesa los payloads en la RTX 4060. Un script de sonda reutiliza `RtspSource` para aislar conectividad RTSP antes de cargar el modelo y nunca imprime usuario, contraseña ni query string.

**Tech Stack:** Python 3.14 del entorno local, OpenCV, PyTorch CUDA, Ultralytics YOLOE, Pydantic, pytest y YAML.

---

## Estructura de archivos

- Modificar: `.gitignore` — ignorar configuraciones operativas locales de RTSP.
- Modificar: `docs/usage.md` — documentar el flujo single-host y la política de secretos.
- Crear: `scripts/probe_rtsp.py` — sonda RTSP de 30 frames con salida sanitizada.
- Crear: `tests/test_probe_rtsp.py` — tests unitarios de redacción y sonda sin red real.
- Crear local, no versionado: `configs/runs/local/ezviz_yoloe_rtsp.yaml` — configuración operativa con la URI real.
- Crear local, no versionado: `configs/runs/local/ezviz_yoloe_rtsp_sustained.yaml` — perfil de cinco minutos derivado de la corrida corta.

## Task 1: Aislar configuración local y documentar el flujo

**Files:**
- Modify: `.gitignore`
- Modify: `docs/usage.md`

- [ ] **Step 1: Añadir el directorio de configuraciones locales a Git ignore**

Agregar justo después de la regla `.env` en `.gitignore`:

```gitignore
# Configuraciones operativas con endpoints o credenciales locales
configs/runs/local/
```

- [ ] **Step 2: Verificar que Git ignora una configuración RTSP local**

Run:

```bash
mkdir -p configs/runs/local
touch configs/runs/local/.gitkeep
git check-ignore -v configs/runs/local/.gitkeep
rm configs/runs/local/.gitkeep
```

Expected: `git check-ignore` imprime la regla `configs/runs/local/`. El archivo temporal no queda en el árbol.

- [ ] **Step 3: Documentar la ejecución RTSP con detector real**

Agregar al final de la sección `## Ejecutar pipeline` de `docs/usage.md`:

```markdown
### Cámara RTSP con YOLOE en GPU (single-host)

Crear una configuración local bajo `configs/runs/local/`; ese directorio está ignorado por Git.
La URI RTSP contiene credenciales y no debe copiarse a archivos versionados ni a tickets.

Usar `model.ref: yoloe/yoloe-26s` con `model.device: cuda:0`, y para una fuente
viva usar `source.type: rtsp` junto con `rate_control.policy: bounded_freshness`.

Antes de cargar el modelo, verificar 30 frames del stream:

~~~bash
python scripts/probe_rtsp.py --config configs/runs/local/ezviz_yoloe_rtsp.yaml --frames 30
~~~

Luego ejecutar la corrida limitada:

~~~bash
eovrt-media run --config configs/runs/local/ezviz_yoloe_rtsp.yaml
~~~

Los artefactos en `runs/` incluyen `effective_config.yaml` y `detections.jsonl`, que
conservan la ruta de la fuente. Mantenerlos locales o sanearlos antes de compartirlos.
```

- [ ] **Step 4: Verificar formato y alcance del cambio**

Run:

```bash
git diff --check
git status --short
```

Expected: sólo `.gitignore` y `docs/usage.md` aparecen modificados; no hay URI RTSP ni credenciales en el diff.

- [ ] **Step 5: Commit**

```bash
git add .gitignore docs/usage.md
git commit -m "docs: preparar configuración local para pruebas RTSP"
```

## Task 2: Crear una sonda RTSP que no filtre credenciales

**Files:**
- Create: `scripts/probe_rtsp.py`
- Create: `tests/test_probe_rtsp.py`

- [ ] **Step 1: Escribir tests rojos para la redacción y el conteo de frames**

Crear `tests/test_probe_rtsp.py`:

```python
from __future__ import annotations

from types import SimpleNamespace

from eovrt_media.contracts import VisualUnit
from scripts import probe_rtsp


def test_redact_rtsp_url_hides_credentials_and_query():
    assert probe_rtsp.redact_rtsp_url(
        "rtsp://user:secret@192.168.1.82:554/Streaming/Channels/1?token=value"
    ) == "rtsp://192.168.1.82:554/Streaming/Channels/1"


def test_probe_reads_requested_number_of_frames(monkeypatch, tmp_path):
    class FakeRtspSource:
        def __init__(self, url, reconnect_retries, reconnect_delay_ms, max_units):
            assert url == "rtsp://user:secret@camera:554/live"
            assert reconnect_retries == 3
            assert reconnect_delay_ms == 0
            assert max_units == 3

        def __iter__(self):
            for index in range(3):
                yield VisualUnit(
                    unit_id=f"frame_{index:06d}",
                    source_path="rtsp://user:secret@camera:554/live",
                    source_type="video_frame",
                    frame_index=index,
                    width=1920,
                    height=1080,
                    timestamp_ms=1000.0 + index,
                )

    config = SimpleNamespace(
        source=SimpleNamespace(
            type="rtsp",
            url="rtsp://user:secret@camera:554/live",
            path="unused",
            reconnect_retries=3,
            reconnect_delay_ms=0,
        )
    )
    monkeypatch.setattr(probe_rtsp, "load_run_config", lambda _: config)
    monkeypatch.setattr(probe_rtsp, "RtspSource", FakeRtspSource)

    result = probe_rtsp.probe(tmp_path / "local.yaml", frames=3)

    assert result.endpoint == "rtsp://camera:554/live"
    assert result.frames_read == 3
    assert result.width == 1920
    assert result.height == 1080
```

- [ ] **Step 2: Verificar el estado rojo**

Run:

```bash
source .venv/bin/activate && pytest tests/test_probe_rtsp.py -v
```

Expected: fallo de colección porque `scripts.probe_rtsp` no existe.

- [ ] **Step 3: Implementar la sonda**

Crear `scripts/probe_rtsp.py`:

```python
"""Sonda segura de conectividad RTSP para una configuración local."""
from __future__ import annotations

import argparse
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from eovrt_media.config import load_run_config
from eovrt_media.sources import RtspSource


@dataclass(frozen=True)
class ProbeResult:
    endpoint: str
    frames_read: int
    width: int
    height: int
    elapsed_seconds: float


def redact_rtsp_url(url: str) -> str:
    """Devuelve esquema, host, puerto y path; omite credenciales y query string."""
    parsed = urlsplit(url)
    host = parsed.hostname or "unknown-host"
    port = f":{parsed.port}" if parsed.port is not None else ""
    return urlunsplit((parsed.scheme or "rtsp", f"{host}{port}", parsed.path or "/", "", ""))


def probe(config_path: Path, frames: int) -> ProbeResult:
    """Lee exactamente ``frames`` unidades desde la fuente RTSP configurada."""
    if frames < 1:
        raise ValueError("frames debe ser mayor o igual a 1.")
    config = load_run_config(config_path)
    if config.source.type.lower() != "rtsp":
        raise ValueError("La configuración de la sonda requiere source.type=rtsp.")

    source = RtspSource(
        url=config.source.url or config.source.path,
        reconnect_retries=config.source.reconnect_retries,
        reconnect_delay_ms=config.source.reconnect_delay_ms,
        max_units=frames,
    )
    started = time.perf_counter()
    units = list(source)
    elapsed = time.perf_counter() - started
    if len(units) != frames:
        raise RuntimeError(f"RTSP entregó {len(units)} frames; se esperaban {frames}.")

    last = units[-1]
    return ProbeResult(
        endpoint=redact_rtsp_url(config.source.url or config.source.path),
        frames_read=len(units),
        width=last.width,
        height=last.height,
        elapsed_seconds=elapsed,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Comprueba un stream RTSP sin revelar credenciales.")
    parser.add_argument("--config", type=Path, required=True, help="YAML local con source.type=rtsp.")
    parser.add_argument("--frames", type=int, default=30, help="Cantidad de frames a leer.")
    args = parser.parse_args()
    result = probe(args.config, args.frames)
    fps = result.frames_read / result.elapsed_seconds if result.elapsed_seconds else 0.0
    print(f"RTSP: {result.endpoint}")
    print(f"Frames: {result.frames_read}; resolución: {result.width}x{result.height}; FPS observado: {fps:.2f}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Verificar estado verde y redacción**

Run:

```bash
source .venv/bin/activate && pytest tests/test_probe_rtsp.py -v
ruff check scripts/probe_rtsp.py tests/test_probe_rtsp.py
```

Expected: 2 tests pasan y Ruff no reporta errores.

- [ ] **Step 5: Commit**

```bash
git add scripts/probe_rtsp.py tests/test_probe_rtsp.py
git commit -m "feat: agregar sonda RTSP sanitizada"
```

## Task 3: Crear y validar el perfil local de la cámara

**Files:**
- Create locally, ignored: `configs/runs/local/ezviz_yoloe_rtsp.yaml`

- [ ] **Step 1: Crear el directorio local ignorado**

Run:

```bash
mkdir -p configs/runs/local
git check-ignore -q configs/runs/local/ezviz_yoloe_rtsp.yaml
```

Expected: exit code 0; Git ignorará el YAML antes de que incluya la URI.

- [ ] **Step 2: Crear el YAML de corrida en un editor local**

Crear `configs/runs/local/ezviz_yoloe_rtsp.yaml` con este contenido. Al editar las dos
ocurrencias de `RTSP_URI_DE_LA_CAMARA`, pegar la URI que el usuario entregó fuera del repositorio.

```yaml
run:
  id: rtsp_ezviz_yoloe_short
  scenario: EBE
  name: ezviz_yoloe_rtsp_short
  description: "Validación RTSP local con YOLOE-26s GPU"
  max_units: 120

source:
  type: rtsp
  path: "RTSP_URI_DE_LA_CAMARA"
  url: "RTSP_URI_DE_LA_CAMARA"
  reconnect_retries: 5
  reconnect_delay_ms: 1000

model:
  ref: yoloe/yoloe-26s
  device: cuda:0

prompts:
  ref: cr01_cr02_v1
  active_ids: [person, helmet, vest]

rate_control:
  policy: bounded_freshness
  buffer_size: 2
  max_staleness_ms: 1000

topology:
  mode: single_host

transport:
  backend: memory
  payload_format: uint8_rgb

outputs:
  run_dir: runs
  base_dir: runs
  save_previews: false
```

- [ ] **Step 3: Validar sólo el esquema local**

Run:

```bash
source .venv/bin/activate && eovrt-media validate-config --config configs/runs/local/ezviz_yoloe_rtsp.yaml
```

Expected: `✓ Configuración válida` y ningún intento de abrir RTSP ni cargar YOLOE.

- [ ] **Step 4: Ejecutar la sonda de conectividad**

Run:

```bash
source .venv/bin/activate && python scripts/probe_rtsp.py --config configs/runs/local/ezviz_yoloe_rtsp.yaml --frames 30
```

Expected: informa host/puerto/ruta sanitizados, 30 frames, resolución y FPS observado. Si falla,
no iniciar el pipeline: comprobar que la PC y la cámara están en la misma LAN, que RTSP está
habilitado en EZVIZ y que la ruta configurada es la del canal primario.

- [ ] **Step 5: Confirmar que no se versionó la URI**

Run:

```bash
git status --short
git ls-files configs/runs/local
```

Expected: el YAML local no aparece en ambos comandos.

## Task 4: Ejecutar y evaluar la corrida corta con YOLOE GPU

**Files:**
- Read local, ignored: `configs/runs/local/ezviz_yoloe_rtsp.yaml`
- Read generated: `runs/rtsp_ezviz_yoloe_short/`

- [ ] **Step 1: Verificar el preflight de GPU y pesos**

Run:

```bash
nvidia-smi --query-gpu=name,memory.free --format=csv,noheader
source .venv/bin/activate && python - <<'PY'
from pathlib import Path
import torch
from ultralytics import YOLOE

weights = Path("models/yoloe/original/yoloe-26s-seg.pt")
assert torch.cuda.is_available(), "CUDA no está disponible"
assert weights.is_file(), f"No existe {weights}"
model = YOLOE(str(weights))
assert model is not None
print("CUDA:", torch.cuda.get_device_name(0))
print("YOLOE-26s cargó correctamente")
PY
```

Expected: CUDA disponible, RTX 4060 detectada y peso YOLOE cargado.

- [ ] **Step 2: Ejecutar la corrida limitada**

Run:

```bash
source .venv/bin/activate && eovrt-media run --config configs/runs/local/ezviz_yoloe_rtsp.yaml
```

Expected: procesa hasta 120 unidades, finaliza y crea `runs/rtsp_ezviz_yoloe_short/`.

- [ ] **Step 3: Validar los artefactos sin imprimir la URI**

Run:

```bash
source .venv/bin/activate && python - <<'PY'
import json
from pathlib import Path

run_dir = Path("runs/rtsp_ezviz_yoloe_short")
summary = json.loads((run_dir / "summary.json").read_text())
metrics = [json.loads(line) for line in (run_dir / "metrics.jsonl").read_text().splitlines()]
errors = (run_dir / "errors.jsonl").read_text().splitlines()

assert summary["source_type"] == "rtsp"
assert summary["run_descriptor"]["topology"] == "single_host"
assert summary["run_descriptor"]["transport"]["backend"] == "memory"
assert summary["run_descriptor"]["rate_control"]["policy"] == "bounded_freshness"
assert summary["units_processed"] > 0
assert summary["units_failed"] == 0
assert summary["gpu_memory_peak_mb"] > 0
assert metrics and all(metric["device"] == "cuda:0" for metric in metrics)
assert not errors
print({key: summary[key] for key in ("units_processed", "total_detections", "p50_latency_ms", "p95_latency_ms", "gpu_memory_peak_mb")})
PY
```

Expected: todas las aserciones pasan y sólo se imprimen contadores y latencias.

- [ ] **Step 4: Registrar la decisión de ajuste**

Usar esta tabla exactamente una variable por vez:

| Evidencia en `summary.json` / `metrics.jsonl` | Cambio siguiente |
| --- | --- |
| `p95_latency_ms` supera el intervalo entre frames observado | Cambiar `model.image_size` de `640` a `512`. |
| `units_dropped` crece mientras la latencia es aceptable | Cambiar `rate_control.buffer_size` de `2` a `3`. |
| No hay detecciones de EPP pero sí personas | Mantener tamaño y ajustar sólo `model.confidence_threshold` de `0.25` a `0.20`. |
| Hay detecciones espurias repetidas | Mantener tamaño y ajustar sólo `model.confidence_threshold` de `0.25` a `0.35`. |

Después de cada cambio, restaurar `run.id: rtsp_ezviz_yoloe_short`, borrar únicamente
`runs/rtsp_ezviz_yoloe_short/`, repetir Steps 2-3 y comparar los cinco campos impresos.

## Task 5: Ejecutar la corrida sostenida

**Files:**
- Create locally, ignored: `configs/runs/local/ezviz_yoloe_rtsp_sustained.yaml`
- Read generated: `runs/rtsp_ezviz_yoloe_sustained/`

- [ ] **Step 1: Derivar la cantidad de unidades para cinco minutos**

Run:

```bash
source .venv/bin/activate && python - <<'PY'
import json
import math
from pathlib import Path

summary = json.loads(Path("runs/rtsp_ezviz_yoloe_short/summary.json").read_text())
fps = summary["fps_effective"]
assert fps > 0, "La corrida corta no produjo FPS efectivo"
print(math.ceil(fps * 300))
PY
```

Expected: imprime un entero positivo `N` equivalente a cinco minutos al FPS efectivo medido.

- [ ] **Step 2: Crear el perfil sostenido local**

Copiar el YAML corto a `configs/runs/local/ezviz_yoloe_rtsp_sustained.yaml` y cambiar sólo:

```yaml
run:
  id: rtsp_ezviz_yoloe_sustained
  name: ezviz_yoloe_rtsp_sustained
  max_units: N
```

Reemplazar `N` por el entero impreso en Step 1. Conservar idénticos el URI, modelo, prompts,
rate control, transporte y outputs de la corrida corta.

- [ ] **Step 3: Ejecutar y validar la corrida sostenida**

Run:

```bash
source .venv/bin/activate && eovrt-media run --config configs/runs/local/ezviz_yoloe_rtsp_sustained.yaml
source .venv/bin/activate && eovrt-media inspect-run runs/rtsp_ezviz_yoloe_sustained
```

Expected: la corrida alcanza `N` unidades o termina con un error de fuente registrado; el resumen
expone latencias, FPS, descartes y pico de VRAM para decidir el siguiente experimento.

- [ ] **Step 4: Confirmar higiene del repositorio**

Run:

```bash
git status --short
git check-ignore -q configs/runs/local/ezviz_yoloe_rtsp.yaml
git check-ignore -q configs/runs/local/ezviz_yoloe_rtsp_sustained.yaml
```

Expected: los perfiles locales no aparecen en el estado de Git y ambas comprobaciones devuelven exit code 0.

---

## Verificación final

Run:

```bash
source .venv/bin/activate && pytest -q && ruff check src tests scripts
git diff --check
```

Expected: suite completa verde, Ruff sin errores y ningún diff accidental con la URI RTSP.
