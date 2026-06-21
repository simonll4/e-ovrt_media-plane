## Matriz experimental candidata de modelos

El repositorio debe permitir comparar distintos modelos OVD bajo una misma estructura de corrida, sin acoplar el pipeline a un modelo específico.

Dado el hardware disponible para desarrollo local, una GPU NVIDIA RTX 4060, se define la siguiente matriz experimental candidata. Esta matriz no representa un compromiso obligatorio de implementación completa en el primer sprint; funciona como guía para organizar pruebas progresivas de factibilidad, rendimiento y calidad perceptiva.

La prioridad es que todas las corridas compartan los mismos contratos internos:

```text
RunConfig
VisualUnit
RawDetection
DetectionEvent
MetricSample
summary.json
```

De esta forma, los resultados de distintos modelos pueden compararse sin modificar el resto del pipeline.

### Corridas candidatas

| Corrida | Modelo                     | Resolución         | Objetivo                                       | Prioridad |
| ------- | -------------------------- | ------------------ | ---------------------------------------------- | --------- |
| Y-E1    | YOLOE-26s                  | 640                | Baseline realtime                              | Alta      |
| Y-E2    | YOLOE-26m                  | 640                | Balance velocidad/precisión                    | Alta      |
| Y-E3    | YOLOE-26l                  | 640                | Precisión alta manteniendo posible realtime    | Media     |
| Y-E4    | YOLOE-26l                  | 960                | Precisión para objetos pequeños: casco/chaleco | Media     |
| Y-E5    | YOLOE-26x                  | 640/960            | Techo de precisión local, si entra en memoria  | Baja      |
| G-E1    | GroundingDINO-T            | default/800 aprox. | Baseline semántico local                       | Alta      |
| G-E2    | GroundingDINO-B            | default/800 aprox. | Precisión alta offline                         | Media     |
| G-E3    | Grounding DINO 1.5 Edge    | 640/800            | Realtime optimizado si está disponible         | Media     |
| G-E4    | Grounding DINO 1.5/1.6 Pro | offline/API        | Referencia SOTA, no núcleo del MVP             | Baja      |

### Interpretación de la matriz

Las corridas `Y-*` corresponden a la familia YOLOE. Su objetivo principal es evaluar factibilidad realtime o near-realtime en hardware local, especialmente para detección de entidades frecuentes como `person`, `helmet` y `safety vest`.

Las corridas `G-*` corresponden a la familia Grounding DINO. Su objetivo principal es evaluar expresividad semántica y robustez frente a prompts, aunque puedan tener mayor costo computacional.

La comparación no debe limitarse a precisión visual aparente. Cada corrida debe producir métricas técnicas y artefactos reproducibles.

### Criterios mínimos de comparación

Para cada corrida se deben registrar, como mínimo:

```text
modelo
model_id
resolución de entrada
device usado
prompts activos
cantidad de unidades procesadas
cantidad total de detecciones
latencia promedio
latencia p95
FPS efectivo
VRAM máxima observada si está disponible
errores recuperables
cantidad de unidades fallidas
```

También conviene registrar observaciones cualitativas, especialmente para objetos pequeños:

```text
casco detectado / no detectado
chaleco detectado / no detectado
falsos positivos frecuentes
detecciones inestables
sensibilidad a resolución
sensibilidad a prompts
```

### Reglas de ejecución

La matriz no debe romper la simplicidad del pipeline.

Las corridas deben implementarse como configuraciones YAML separadas, no como ramas especiales de código.

Ejemplo:

```text
configs/experiments/
  y_e1_yoloe_26s_640.yaml
  y_e2_yoloe_26m_640.yaml
  y_e3_yoloe_26l_640.yaml
  y_e4_yoloe_26l_960.yaml
  y_e5_yoloe_26x_640.yaml
  g_e1_grounding_dino_t.yaml
  g_e2_grounding_dino_b.yaml
```

El código del pipeline no debe conocer los nombres `Y-E1`, `G-E1`, etc.
Esos identificadores pertenecen a la configuración experimental y a los artefactos de salida.

### Criterios de descarte temprano

Una corrida puede descartarse o dejarse como no prioritaria si ocurre alguno de estos casos:

```text
no carga en la GPU disponible
requiere demasiada VRAM
tiene latencia incompatible con el objetivo del experimento
requiere una dependencia inestable
requiere acceso a una API externa no prevista para el núcleo local
no produce mejoras relevantes frente a una variante más liviana
```

El descarte no debe considerarse un fallo del proyecto. Es parte de la evaluación experimental.

### Estrategia recomendada de ejecución

El orden sugerido de pruebas es:

```text
1. mock
2. YOLOE-26s a 640
3. GroundingDINO-T
4. YOLOE-26m a 640
5. YOLOE-26l a 640
6. YOLOE-26l a 960
7. GroundingDINO-B
8. variantes Edge/Pro solo si están disponibles y justificadas
```

El objetivo es avanzar desde modelos livianos y corridas rápidas hacia modelos más costosos.

Primero se valida que el pipeline funcione.
Después se mide.
Después se comparan modelos.
Recién al final se decide qué candidato queda como baseline principal.

### Relación con el MVP

Para el MVP del plano de medios no es necesario completar toda la matriz.

El MVP se considera suficiente si existen:

```text
una corrida mock funcional
una corrida YOLOE funcional
una corrida Grounding DINO funcional
artefactos comparables en runs/
summary.json por corrida
métricas básicas de latencia y FPS
```

Las demás corridas forman parte de la exploración experimental posterior.
