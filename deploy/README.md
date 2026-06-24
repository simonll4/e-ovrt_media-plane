# Deploy del Media Plane

Infraestructura de despliegue del plano de medios. El **single-host (DBE)** corre
nativo con venv; el **two-node (EBE)** se empaqueta en dos imágenes Docker.

## Single-host (DBE) — nativo

```bash
python3.11 -m venv .venv && source .venv/bin/activate && pip install -e ".[gpu,dev]"
eovrt-media run --config configs/runs/<file>.yaml
```

## Two-node (EBE) — Docker

- **node-a** (edge, sin GPU): ingesta, rate control, normalización, servidor ZeroMQ.
- **node-b** (GPU): cliente ZeroMQ, inferencia OVD, postproceso, artefactos.

### Requisitos

- Docker + plugin Compose.
- En el host de node-b: GPU NVIDIA + [nvidia-container-toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html).
- **WSL2**: CUDA en Docker depende del driver NVIDIA del host Windows. Verificar:
  `docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi`.

### Estructura

```
deploy/
  docker-compose.yml       Stack two-node (parametrizado por .env)
  .env.example             Plantilla: qué config monta cada nodo
  docker/                  Dockerfile.node-a (edge), Dockerfile.node-b (GPU)
  configs/                 two_node_{a,b}.example.yaml (versionados, sin IPs reales)
```

### Quickstart — test local (un host)

Levanta ambos nodos en la red bridge; node-b resuelve `node-a` por DNS interno.

```bash
cd deploy
cp .env.example .env          # defaults apuntan a los *.example.yaml
docker compose build
docker compose up
```

Requiere el repo `e-ovrt_datasets` como hermano en disco (se monta en `/datasets`).
Los artefactos quedan en `runs/` del host.

### Quickstart — deploy real (dos hosts)

En el **host edge**:

```bash
cd deploy && docker compose up node-a
```

En el **host GPU**, copiar el config de B y apuntar el endpoint al IP del edge:

```bash
cd deploy/configs
cp two_node_b.example.yaml two_node_b.yaml
# editar two_node_b.yaml: transport.endpoint: "tcp://<ip-edge>:5555"
cd ..
echo "NODE_B_CONFIG=/app/deploy-configs/two_node_b.yaml" > .env
docker compose up node-b
```

### Variables `.env`

| Variable | Default | Descripción |
| --- | --- | --- |
| `NODE_A_CONFIG` | `/app/deploy-configs/two_node_a.example.yaml` | Config montado en node-a |
| `NODE_B_CONFIG` | `/app/deploy-configs/two_node_b.example.yaml` | Config montado en node-b |

El endpoint NO se parametriza por `.env` (el loader no soporta env vars); vive dentro
del YAML de config. `.env` solo selecciona qué archivo se monta.

### Fricciones conocidas

- Las imágenes CUDA/PyTorch son grandes; el primer build de node-b es lento.
- La cámara RTSP/OAK-D Pro PoE en contenedor queda pendiente hasta disponer del hardware.
