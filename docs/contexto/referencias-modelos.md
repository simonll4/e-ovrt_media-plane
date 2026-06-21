### Referencias oficiales de pesos, documentación y descarga

La matriz experimental debe incluir referencias explícitas a la fuente oficial de documentación y pesos de cada familia de modelos. Estas referencias sirven para que los agentes de código sepan dónde verificar nombres de checkpoints, variantes disponibles, ejemplos de uso y cambios de API.

Los pesos no deben versionarse en Git.
Si se descargan manualmente, deben guardarse bajo `models/` o en la caché propia de la librería correspondiente.

---

#### YOLOE / YOLOE-26

Fuente principal:

```text
Ultralytics Docs -> Models -> YOLOE
```

Documentación oficial:

```text
https://docs.ultralytics.com/models/yoloe/
```

Repositorio/librería principal:

```text
https://github.com/ultralytics/ultralytics
```

Ubicación de pesos:

```text
Ultralytics YOLOE GitHub release assets
Ultralytics assets releases
Auto-download mediante ultralytics cuando el checkpoint se referencia por nombre
```

Pesos candidatos para la matriz:

```text
yoloe-26n-seg.pt
yoloe-26s-seg.pt
yoloe-26m-seg.pt
yoloe-26l-seg.pt
yoloe-26x-seg.pt
```

Pesos prompt-free, si se quieren probar más adelante:

```text
yoloe-26n-seg-pf.pt
yoloe-26s-seg-pf.pt
yoloe-26m-seg-pf.pt
yoloe-26l-seg-pf.pt
yoloe-26x-seg-pf.pt
```

Para el MVP del plano de medios, priorizar checkpoints con prompts de texto:

```text
yoloe-26s-seg.pt
yoloe-26m-seg.pt
yoloe-26l-seg.pt
```

Los modelos `*-pf.pt` pueden ser útiles como referencia prompt-free, pero no son la prioridad inicial porque el objetivo del TFG es mantener evaluación open-vocabulary guiada por prompts.

Ejemplo conceptual de carga:

```python
from ultralytics import YOLOE

model = YOLOE("yoloe-26s-seg.pt")
model.set_classes(["person", "safety helmet", "high visibility safety vest"])
results = model.predict("path/to/image.jpg", imgsz=640, conf=0.25)
```

Notas para el adaptador:

```text
- No hardcodear el checkpoint en código.
- El checkpoint debe venir desde RunConfig.
- El adaptador debe aceptar tanto nombres remotos como rutas locales.
- Si se usa una ruta local, debe apuntar a models/<checkpoint>.pt.
- Aunque YOLOE produzca máscaras, el núcleo inicial puede usar solo bounding boxes.
- set_classes() debe ejecutarse una vez al cargar el modelo con los prompts activos.
```

Ejemplo de configuración:

```yaml
model:
  name: yoloe
  model_id: yoloe-26s-seg.pt
  device: cuda
  image_size: 640
  confidence_threshold: 0.25
```

Ejemplo usando pesos locales:

```yaml
model:
  name: yoloe
  model_id: models/yoloe-26s-seg.pt
  device: cuda
  image_size: 640
  confidence_threshold: 0.25
```

---

#### Grounding DINO vía Hugging Face Transformers

Fuente principal:

```text
Hugging Face Transformers -> Grounding DINO
```

Documentación oficial:

```text
https://huggingface.co/docs/transformers/model_doc/grounding-dino
```

Model cards principales:

```text
https://huggingface.co/IDEA-Research/grounding-dino-tiny
https://huggingface.co/IDEA-Research/grounding-dino-base
```

Model IDs recomendados para integración inicial:

```text
IDEA-Research/grounding-dino-tiny
IDEA-Research/grounding-dino-base
```

Para el MVP del plano de medios, priorizar:

```text
IDEA-Research/grounding-dino-tiny
```

Luego probar:

```text
IDEA-Research/grounding-dino-base
```

En esta vía no hace falta descargar manualmente un `.pth`. Hugging Face descarga y cachea automáticamente los pesos cuando se llama a:

```python
from transformers import AutoProcessor, AutoModelForZeroShotObjectDetection

processor = AutoProcessor.from_pretrained("IDEA-Research/grounding-dino-tiny")
model = AutoModelForZeroShotObjectDetection.from_pretrained(
    "IDEA-Research/grounding-dino-tiny"
)
```

Ejemplo conceptual de configuración:

```yaml
model:
  name: grounding_dino
  backend: transformers
  model_id: IDEA-Research/grounding-dino-tiny
  device: cuda
  box_threshold: 0.30
  text_threshold: 0.25
```

Notas para el adaptador:

```text
- Esta vía es la más simple para empezar.
- El model_id debe venir desde RunConfig.
- No acoplar el pipeline general a Transformers.
- AutoProcessor y AutoModelForZeroShotObjectDetection solo deben aparecer dentro del adaptador.
- Los prompts deben llegar desde PromptSet.
- Grounding DINO suele requerir prompts en minúscula y terminados con punto.
```

Ejemplo de prompt concatenado para Grounding DINO:

```text
person. safety helmet. high visibility safety vest. reflective vest.
```

---

#### Grounding DINO vía repositorio oficial y checkpoints `.pth`

Fuente principal:

```text
IDEA-Research / GroundingDINO
```

Repositorio oficial:

```text
https://github.com/IDEA-Research/GroundingDINO
```

Checkpoints oficiales relevantes:

```text
groundingdino_swint_ogc.pth
groundingdino_swinb_cogcoor.pth
```

Ubicaciones habituales:

```text
GitHub releases del repositorio IDEA-Research/GroundingDINO
Hugging Face: ShilongLiu/GroundingDINO
```

Archivos de configuración asociados:

```text
GroundingDINO_SwinT_OGC.py
GroundingDINO_SwinB_cfg.py
```

Esta vía puede ser útil si se quiere usar el código oficial original en lugar de Transformers, pero no debería ser la primera integración salvo que Transformers no cubra alguna necesidad del pipeline.

Ejemplo conceptual de estructura local:

```text
models/
  groundingdino/
    groundingdino_swint_ogc.pth
    groundingdino_swinb_cogcoor.pth
```

Ejemplo de configuración:

```yaml
model:
  name: grounding_dino
  backend: official_repo
  model_id: models/groundingdino/groundingdino_swint_ogc.pth
  config_path: third_party/GroundingDINO/groundingdino/config/GroundingDINO_SwinT_OGC.py
  device: cuda
  box_threshold: 0.30
  text_threshold: 0.25
```

Notas:

```text
- No copiar el repositorio oficial dentro de src/eovrt_media.
- Si se usa el repo oficial, tratarlo como dependencia externa o third_party documentado.
- No mezclar imports del repo oficial fuera del adaptador.
- Verificar compatibilidad CUDA/PyTorch antes de asumir que esta vía funciona.
```

---

#### Grounding DINO 1.5 Edge / 1.5 Pro / 1.6 Pro

Fuente principal:

```text
IDEA-Research / Grounding-DINO-1.5-API
```

Repositorio:

```text
https://github.com/IDEA-Research/Grounding-DINO-1.5-API
```

Uso previsto en este proyecto:

```text
Referencia experimental o benchmark externo.
No núcleo obligatorio del MVP local.
```

Motivo:

```text
Grounding DINO 1.5/1.6 Pro se presenta principalmente mediante API/DeepDataSpace.
Puede requerir token externo.
Puede no ser reproducible 100% local.
No debe bloquear el desarrollo del plano de medios.
```

Regla para el repositorio:

```text
- No depender de una API externa para el MVP.
- No incluir tokens en configs versionadas.
- Si se implementa un adaptador API, debe ser opcional.
- Las corridas G-E3/G-E4 deben quedar marcadas como experimentales.
```

Ejemplo de configuración futura, no prioritaria:

```yaml
model:
  name: grounding_dino_api
  backend: deepdataspace
  model_id: grounding-dino-1.5-pro
  device: remote
  api_token_env: GROUNDING_DINO_API_TOKEN
```

---

#### Convención recomendada para descarga/cache de modelos

Agregar un script o comando CLI para preparar modelos sin mezclar esa lógica con el pipeline de inferencia.

Comando deseado:

```bash
eovrt-media download-models --model yoloe --variant yoloe-26s-seg.pt
eovrt-media download-models --model grounding_dino --variant IDEA-Research/grounding-dino-tiny
```

Comportamiento esperado:

```text
- Para YOLOE:
  - intentar cargar el checkpoint con Ultralytics;
  - permitir auto-download si la librería lo soporta;
  - si falla, imprimir instrucciones para descargar el .pt manualmente.

- Para Grounding DINO Transformers:
  - llamar AutoProcessor.from_pretrained(model_id);
  - llamar AutoModelForZeroShotObjectDetection.from_pretrained(model_id);
  - dejar los pesos en la caché de Hugging Face.

- Para Grounding DINO official_repo:
  - no descargar automáticamente si la URL no está versionada en config;
  - validar existencia de model_id y config_path;
  - imprimir mensaje claro si faltan archivos.
```

No guardar pesos dentro del repositorio Git.

`.gitignore` debe cubrir:

```gitignore
models/*.pt
models/*.pth
models/*.onnx
models/*.engine
models/groundingdino/*.pth
```

---

#### Regla para agentes de código

Los agentes no deben inventar nombres de checkpoints.

Antes de agregar una nueva variante deben verificar:

```text
- documentación oficial;
- model card;
- release asset;
- ejemplo de carga;
- licencia;
- disponibilidad local o remota;
- requisitos de VRAM aproximados;
- compatibilidad con el adaptador existente.
```

Si un checkpoint no está disponible o cambia de nombre, el agente debe:

```text
- no romper el pipeline;
- dejar la corrida como pendiente/no disponible;
- documentar el motivo;
- proponer una alternativa compatible.
```
