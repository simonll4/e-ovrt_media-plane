# Despliegue de dos nodos con Docker

Empaqueta el plano de medios EBE distribuido en dos imágenes:

- **node-a** (edge, sin GPU): ingesta RTSP, rate control, normalización y servidor ZeroMQ.
- **node-b** (GPU): cliente ZeroMQ, inferencia OVD, postproceso y artefactos.

## Requisitos

- Docker y el plugin Docker Compose.
- En el host del Nodo B: GPU NVIDIA y [nvidia-container-toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html).
- **WSL2**: el soporte CUDA en Docker depende del driver NVIDIA del host Windows. Verificarlo con `docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi`.

## Configuración del endpoint

Los dos nodos necesitan endpoints distintos. Crear dos YAML con la misma configuración de corrida y cambiar solo `transport.endpoint`:

- `two_node_a.yaml`: `topology.mode: two_node` y `transport.endpoint: "tcp://0.0.0.0:5555"`.
- `two_node_b.yaml`: `topology.mode: two_node` y `transport.endpoint: "tcp://node-a:5555"`.

El compose monta ambos archivos bajo `/configs` y cada imagen usa el que corresponde por defecto.

## Uso

```bash
cd docker
docker compose build
docker compose up
```

Los artefactos quedan en `runs/` del host, montado en el Nodo B.

## Fricciones conocidas

- Las imágenes CUDA y PyTorch son grandes; el primer build es lento.
- La imagen de Nodo B usa Python 3.12 sobre Ubuntu 24.04, que cumple el requisito del proyecto (Python ≥3.11).
- La cámara OAK-D Pro PoE, vía DepthAI, requerirá acceso a dispositivos o red adicional en Nodo A; queda pendiente junto con `OakDSource`.
