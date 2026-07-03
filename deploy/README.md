# Deploy del Media Plane

Infraestructura de despliegue del plano de medios. En **Fase 1** el media-plane dejó de
ser un CLI y pasó a **servicio de inferencia HTTP/WS** (Spec A). El único despliegue
vigente es la **imagen GPU única single-host** (`Dockerfile` de la raíz). El split
**two-node (edge sin GPU / GPU sobre ZeroMQ)** quedó **DIFERIDO A FASE 2**: sus artefactos
en `deploy/docker/` y los `docker-compose*.yml` están **deprecados/rotos** (referencian el
CLI `eovrt-media run-producer/run-consumer`, eliminado) y se conservan solo como
referencia del wiring para Fase 2.

## Single-host (Fase 1, vigente)

El servicio carga el modelo una vez al arrancar (`EOVRT_MODEL_REF`) y expone la API para
disparar corridas. No hay CLI: las corridas se lanzan vía `POST /api/runs`.

### Arranque nativo (venv)

```bash
python3.11 -m venv .venv && source .venv/bin/activate && pip install -e ".[gpu,dev]"
EOVRT_MODEL_REF=mock make serve   # uvicorn --factory eovrt_media.service.app:create_app en :8080
make smoke                        # curl a /healthz + /readyz -> OK
```

`make serve` levanta uvicorn en `0.0.0.0:8080`. El readiness está en `/readyz` (usado como
HEALTHCHECK); `/healthz` es liveness.

### Imagen Docker (GPU única)

El `Dockerfile` de la **raíz** del repo empaqueta el servicio (imagen DBE única, Spec A
§3.3) sobre `nvidia/cuda` con `HEALTHCHECK` a `/readyz`. Requiere runtime NVIDIA
(`--gpus all` / nvidia-container-toolkit) en el host.

```bash
make docker-build       # docker build -t eovrt-media-plane .
make docker-run-mock    # docker run -p 8080:8080 -e EOVRT_MODEL_REF=mock -v ./runs:/data/runs ...
```

Para GPU real, correr la imagen con `--gpus all` y `EOVRT_MODEL_REF` apuntando a un modelo
del catálogo (no `mock`).

### Variables de entorno (`EOVRT_*`)

| Variable | Rol | Default (imagen) |
| --- | --- | --- |
| `EOVRT_MODEL_REF` | **Obligatoria.** Ref del modelo a cargar al arrancar el servicio | `mock` |
| `EOVRT_RUNS_DIR` | Directorio donde se persisten los artefactos de cada corrida | `/data/runs` |
| `EOVRT_DATASETS_ROOT` | Raíz de datasets cross-repo para fuentes tipo `image_folder` | `/data/datasets` |
| `EOVRT_MEDIA_CATALOG_ROOT` | Raíz de catálogos de capacidades (`configs/models`, `configs/datasets`) | `/app/configs` |
| `HF_HOME` | Caché de pesos HuggingFace | `/data/weights` |

### Disparar corridas (API)

```bash
curl -X POST http://localhost:8080/api/runs \
  -H "Content-Type: application/json" \
  -d '{
        "ingest": {"plugin": "image_folder", "config": {"path": "/path/to/images"}},
        "prompts": {
          "set_inline": {"id": "demo", "classes": [{"id": "person", "phrasings": {"default": ["person"]}}]},
          "active_ids": ["person"]
        }
      }'

# GET  /api/runs/{run_id}            — estado/resumen de la corrida
# WS   /api/runs/{run_id}/stream     — eventos en vivo (detecciones/métricas)
# POST /api/runs/{run_id}/stop       — detener la corrida activa
```

## Two-node (DEFERIDO A FASE 2 — no soportado en Fase 1)

> **No corre hoy.** Los `Dockerfile.node-a` / `Dockerfile.node-b` y los tres
> `docker-compose*.yml` de este directorio están **deprecados y rotos**: su
> `ENTRYPOINT`/`command` invoca el CLI `eovrt-media run-producer/run-consumer`, eliminado
> al pasar el media-plane a servicio. Se conservan como referencia del wiring ZeroMQ que
> Fase 2 reusará para rehacer el split edge/GPU. Para desplegar hoy, usar el single-host de
> arriba.

Topología prevista (referencia Fase 2):

- **node-a** (edge, sin GPU): ingesta, rate control, normalización, servidor ZeroMQ.
- **node-b** (GPU): cliente ZeroMQ, inferencia OVD, postproceso, artefactos.

### Contrato de datos / puertos (referencia)

- **TCP/5555** transporta unidades normalizadas por REQ/REP; **TCP/5556** es el heartbeat
  PUSH/PULL. En un despliegue real ambos puertos deben estar permitidos desde node-b hacia
  node-a.
- `payload_format: fp16` usa el wire raw y conserva `float16`; JPEG sólo codifica
  `uint8_rgb`. Si se combina JPEG con FP16, el transporte usa raw de forma intencional.
- Grounding DINO y YOLOE consumen la preparación tensorial BCHW común en node-b. Los
  previews anotados se generan desde el payload recibido, por lo que vídeo, RTSP y Nodo B
  no necesitan montar ni reabrir el archivo fuente del edge.

El código en proceso de ambos nodos sigue existiendo (`runtime/two_node.py:run_node_a()` /
`run_node_b()`, ejercitado por `tests/test_two_node.py`); lo que falta para Fase 2 es
rehacer el empaquetado Docker (dos imágenes) sobre el servicio, no el wiring de transporte.

### Estructura del directorio (artefactos deprecados)

```
deploy/
  docker-compose.yml         [DEPRECADO] Stack local: node-a + node-b en red bridge
  docker-compose.node-a.yml  [DEPRECADO] Host edge: sólo node-a, publica TCP/5555 y TCP/5556
  docker-compose.node-b.yml  [DEPRECADO] Host GPU: sólo node-b
  .env.example               Plantilla: qué config monta cada nodo (two-node)
  docker/                    [DEPRECADO] Dockerfile.node-a (edge), Dockerfile.node-b (GPU)
  configs/                   two_node_{a,b}.example.yaml (versionados, sin IPs reales)
```

### Fricciones conocidas (Fase 2)

- Las imágenes CUDA/PyTorch son grandes; el primer build de node-b es lento.
- OAK-D Pro PoE queda diferido hasta integrar el SDK DepthAI y disponer del hardware.
