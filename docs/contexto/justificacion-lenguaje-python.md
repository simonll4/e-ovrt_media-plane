# Justificación del lenguaje: por qué Python para el plano de medios

- **Fecha**: 2026-06-21
- **Repo**: `e-ovrt_media-plane`
- **Relacionado**: `topologias-despliegue-dbe-ebe.md`, `justificacion_fuentes_externas_plano_medios.md`,
  `../superpowers/specs/2026-06-21-plano-medios-topologia-despliegue-andamiaje-design.md`

## Pregunta

Python es un lenguaje interpretado y, en bytecode puro, lento. ¿Es una elección adecuada para el
plano de medios, un pipeline de detección de objetos de vocabulario abierto (OVD) con requisitos de
caudal y, en EBE, de tiempo real? ¿O la lentitud del lenguaje es un problema?

## Tesis

**Sí, Python es la elección correcta para este proyecto.** El razonamiento no es "Python es rápido"
(no lo es), sino que **en este pipeline el trabajo computacionalmente caro nunca ocurre en bytecode de
Python**: ocurre en bibliotecas nativas (C/C++/CUDA/Rust) que Python solo orquesta. A eso se suma que
el objetivo de caudal es modesto, el "tiempo real" requerido es *blando*, y la arquitectura ya
contempla una salida de emergencia si la concurrencia del lenguaje (el GIL) llegara a molestar.

## 1. Python como capa de orquestación, no de cómputo

Es habitual decir que "para IA, Python es una interfaz". Es cierto: `torch`/`transformers` son
bindings finos sobre C++/ATen/cuDNN/CUDA. Lo importante para nosotros es que **esa propiedad se
generaliza a prácticamente todo el stack del plano de medios**:

| Biblioteca | Trabajo pesado corre en | ¿Libera el GIL? |
|---|---|---|
| `torch` / `transformers` (inferencia OVD) | C++/ATen/cuDNN/CUDA | Sí (durante el forward) |
| `numpy` (operaciones de arrays) | C vectorizado | Sí |
| `OpenCV` / `Pillow` (decode, resize) | C (libjpeg-turbo, etc.) | Sí |
| `torchvision.ops.nms` (postproceso) | C++/CUDA | Sí |
| `pyzmq` (transporte de red) | libzmq en C + hilo de I/O propio | Sí |
| `msgpack` / `orjson` (serialización) | C / Rust | Sí |

Conclusión: el cómputo crítico **no está en Python**. Python arma estructuras, decide control de flujo
y llama a las bibliotecas. La "lentitud del lenguaje" afecta solo a ese glue, que es de microsegundos.

## 2. Dónde está el cómputo, etapa por etapa

| Etapa del pipeline | Dónde corre el cómputo | ¿Overhead de Python relevante? |
|---|---|---|
| OVD Inference | CUDA/cuDNN/C++ | **No.** ~200 ms en GPU vs ~µs de dispatch en Python. |
| Normalización (decode + resize) | OpenCV/PIL/numpy en C | **No**, siempre que se usen ops vectorizadas (no loops por píxel). |
| Postproceso (NMS, filtros, reproyección) | torchvision/numpy, arrays chicos | Marginal a nuestros conteos de detecciones. |
| Rate control / canal (backend memoria) | glue Python (queue, construcción de objetos) | µs por frame (ver §3). |
| Contratos Pydantic v2 | validación implementada en Rust | Bajo; en hot path se puede usar `model_construct()`. |
| Sinks (JSONL) | json/orjson en C + I/O de disco | Domina el disco, no Python. |
| Transporte de red | libzmq en C + msgpack en C | **No.** |

La regla transversal: **cuando algo es caro, delega a código nativo y libera el GIL.** Lo que queda
bajo el intérprete es plomería de microsegundos.

## 3. El único punto donde la semántica del lenguaje importa: el GIL

El diseño de andamiaje desacopla el pipeline en dos roles (productor y consumidor) que, en un host,
corren como **dos hilos** (ver §3 del documento de diseño). El riesgo teórico del GIL (Global
Interpreter Lock) es que dos hilos Python no ejecuten bytecode en paralelo.

**Por qué no es un problema aquí:** los *hot paths* de ambos roles liberan el GIL. Mientras el
consumidor pasa ~200 ms dentro de `torch.forward` (GIL liberado), el productor decodifica y
redimensiona el siguiente frame con OpenCV/numpy (GIL liberado). El solapamiento que el diseño busca
—decodificar mientras se infiere— **ocurre de verdad**. Lo único que compite por el GIL es el glue
(construir el `NormalizedUnit`, `queue.put`/`get`), del orden de microsegundos. A ~5 fps —e incluso a
tasas mucho mayores— es despreciable.

**La salida multiproceso está implementada.** La topología `two_node` ejecuta productor y
consumidor como procesos o contenedores separados y los comunica mediante el backend `network`
de ZeroMQ. Aunque el endpoint habitual es TCP, ZeroMQ admite también `ipc://`; ambas variantes
esquivan el GIL entre procesos sin modificar contratos ni la lógica de los roles. La elección de
lenguaje y la arquitectura son consistentes: no hay un callejón sin salida.

## 4. Cuándo Python sería la elección equivocada (y por qué no es nuestro caso)

| Caso adverso | Por qué Python sufre | ¿Aplica a este proyecto? |
|---|---|---|
| **Tiempo real *duro*** (garantías sub-ms, sin pausas) | Jitter de GC e intérprete | **No.** Nuestro tiempo real es *blando*: frescura de percepción a ~5 fps (`bounded_freshness`), no determinismo de µs. |
| **Throughput extremo en un nodo** (miles de fps) | Los µs por frame se acumulan | **No.** Una cámara, ~5 fps; o batch DBE donde la métrica es reproducibilidad, no wall-clock. |
| **Edge embebido sin runtime** (microcontrolador) | Footprint del runtime Python | **No.** El "Nodo A edge" del doc es un host Linux normal en LAN, no un MCU. |

Ninguno de los tres describe el plano de medios.

## 5. Por qué cambiar de lenguaje no compensa

- **C++ / Rust**: glue más rápido y sin GIL, pero el cómputo **ya es GPU-bound**, así que la ganancia
  de rendimiento sería marginal — y se perdería el ecosistema OVD/`transformers`/processors, que es
  Python-first. Para un proyecto académico, reescribir en C++ cuesta enorme tiempo de desarrollo a
  cambio de performance que no se necesita. (`libtorch`, `tch-rs`, `ort` existen, pero el zoo de
  modelos y el preprocesamiento de OVD viven en Python.)
- **Go**: excelente concurrencia (sin GIL), pero ecosistema de ML pobre; igualmente terminaría
  llamando a Python/C para inferir.

El costo de migrar (perder el ecosistema de IA/CV y la velocidad de iteración experimental) supera
ampliamente cualquier beneficio a esta escala.

## 6. Recomendaciones de implementación derivadas

- **Preferir OpenCV sobre PIL en el path de normalización** (decode/resize más rápido y liberación de
  GIL confiable), especialmente de cara a la fuente `live` futura. El código actual usa PIL
  (`load_image`); para DBE batch alcanza, pero conviene migrar la normalización a OpenCV.
- **Pydantic v2** es adecuado; si el conteo de detecciones por frame fuera alto, usar
  `model_construct()` en el hot path para saltar validación.
- **`orjson`** para los sinks JSONL si el volumen de escritura creciera.
- **Mantener el cómputo vectorizado** (numpy/torch/OpenCV); evitar loops Python por píxel o por
  detección en cualquier etapa caliente.

## 7. Veredicto

Python es adecuado y recomendado para el plano de medios:

1. El cómputo crítico (inferencia, decode/resize, NMS, transporte) corre en bibliotecas nativas que
   liberan el GIL; Python solo orquesta.
2. El objetivo de caudal es modesto y el tiempo real es blando, no duro.
3. La concurrencia productor/consumidor funciona en hilos porque los hot paths liberan el GIL, y la
   topología `two_node` ya ofrece aislamiento en procesos mediante ZeroMQ cuando se requiere.
4. Cambiar de lenguaje sacrificaría el ecosistema de IA/CV sin ganancia real, porque el sistema es
   GPU-bound.

La decisión es coherente con el diseño config-driven y con la arquitectura de costuras del andamiaje
de despliegue.
