# Deploy del Media Plane

Infraestructura de despliegue del plano de medios. Las topologías **single-host
(DBE/EBE)** y **two-node (DBE/EBE)** están soportadas; la primera corre nativa con
venv y la segunda se empaqueta en dos imágenes Docker.

## Single-host (DBE/EBE) — nativo

```bash
python3.11 -m venv .venv && source .venv/bin/activate && pip install -e ".[gpu,dev]"
eovrt-media run --config configs/runs/<file>.yaml
```

## Two-node (DBE/EBE) — Docker

- **node-a** (edge, sin GPU): ingesta, rate control, normalización, servidor ZeroMQ.
- **node-b** (GPU): cliente ZeroMQ, inferencia OVD, postproceso, artefactos.

### Contrato de datos

- TCP/5555 transporta unidades normalizadas por REQ/REP; TCP/5556 es el heartbeat PUSH/PULL.
  En despliegue real ambos puertos deben estar permitidos desde node-b hacia node-a.
- `payload_format: fp16` usa el wire raw y conserva `float16`; JPEG sólo codifica `uint8_rgb`.
  Si se combina JPEG con FP16, el transporte usa raw de forma intencional.
- Grounding DINO y YOLOE consumen la preparación tensorial BCHW común en node-b. Los previews
  anotados se generan desde el payload recibido, por lo que vídeo, RTSP y Nodo B no necesitan
  montar ni reabrir el archivo fuente del edge.

### Requisitos

- Docker + plugin Compose.
- En el host de node-b: GPU NVIDIA + [nvidia-container-toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html).
- **WSL2**: CUDA en Docker depende del driver NVIDIA del host Windows. Verificar:
  `docker run --rm --gpus all nvidia/cuda:12.6.3-cudnn-runtime-ubuntu24.04 nvidia-smi`.

### Estructura

```
deploy/
  docker-compose.yml       Stack local: node-a + node-b en una red bridge
  docker-compose.node-a.yml  Host edge: sólo node-a, publica TCP/5555 y TCP/5556
  docker-compose.node-b.yml  Host GPU: sólo node-b, sin dependencia local de node-a
  .env.example             Plantilla: qué config monta cada nodo
  docker/                  Dockerfile.node-a (edge), Dockerfile.node-b (GPU)
  configs/                 two_node_{a,b}.example.yaml (versionados, sin IPs reales)
```

### Quickstart — test local (un host)

Levanta ambos nodos en la red bridge; node-b resuelve `node-a` por DNS interno.

```bash
cd deploy
cp .env.example .env          # defaults apuntan a los *.example.yaml
docker compose -f docker-compose.yml build
docker compose -f docker-compose.yml up
```

Requiere el repo `e-ovrt_datasets` como hermano en disco (se monta en `/datasets`).
Los artefactos quedan en `runs/` del host.

### Quickstart — deploy real (dos hosts)

En el **host edge**:

```bash
cd deploy
cp .env.example .env
docker compose -f docker-compose.node-a.yml up -d
```

El manifiesto publica `TCP/5555` (datos REQ/REP) y `TCP/5556` (heartbeat
PUSH/PULL); permitir ambos puertos desde el host GPU en el firewall o la red
privada correspondiente.

En el **host GPU**, copiar el config de B y apuntar el endpoint al IP del edge:

```bash
cd deploy/configs
cp two_node_b.example.yaml two_node_b.yaml
# editar two_node_b.yaml:
#   transport.endpoint: "tcp://<ip-edge>:5555"
#   transport.heartbeat_endpoint: "tcp://<ip-edge>:5556"
cd ..
echo "NODE_B_CONFIG=/app/deploy-configs/two_node_b.yaml" > .env
docker compose -f docker-compose.node-b.yml up -d
```

El manifiesto de GPU contiene sólo `node-b`: no crea un Nodo A local y no requiere
el dataset del edge. La imagen materializa `mobileclip2_b.ts` mediante `MobileCLIPTS` al construirla;
una vez construida, el primer arranque de Nodo B no necesita Internet para configurar
los prompts. Los pesos YOLOE siguen siendo un volumen explícito en `../models/`.

### Variables `.env`

| Variable | Default | Descripción |
| --- | --- | --- |
| `NODE_A_CONFIG` | `/app/deploy-configs/two_node_a.example.yaml` | Config montado en node-a |
| `NODE_B_CONFIG` | `/app/deploy-configs/two_node_b.example.yaml` | Config montado en node-b |

El endpoint NO se parametriza por `.env` (el loader no soporta env vars); vive dentro
del YAML de config. `.env` solo selecciona qué archivo se monta. Las tres variantes de
Compose cargan estas mismas variables desde `deploy/.env`.

### Fricciones conocidas

- Las imágenes CUDA/PyTorch son grandes; el primer build de node-b es lento.
- OAK-D Pro PoE queda diferido hasta integrar el SDK DepthAI y disponer del hardware.
