# Diseño — Módulo `experimental-setup`: configuración de experimentos de la plataforma

**Fecha:** 2026-06-27
**Estado:** Implementado (2026-07-03)
**Ámbito:** plataforma E-OVRT-VDP — relocalización de la **declaración de experimentos** (prompt sets +
manifiestos de corrida) a un repo externo `e-ovrt_experimental-setup`, y los cambios en
`e-ovrt_media-plane` (loader + CLI) para consumirlos.
**Orientación:** ejecuciones **experimentales** (no productivo). Prioriza separación de
responsabilidades, reproducibilidad y composición declarativa, no robustez operacional.
**Specs relacionados:** `2026-06-25-prompt-layer-design.md` (capa de prompts; este diseño la
relocaliza pero **no** altera su diseño interno — ver §7).

---

## 1. Problema y motivación

Hoy el `RunConfig` del media-plane (`config/schemas.py:286`) bundlea en un solo objeto dos
naturalezas que pertenecen a planos distintos de la plataforma:

- **A — Definición del experimento** (qué se estudia): `prompts` (fraseo/estrategias, la variable
  de estudio), `model`/variante, `source`/dataset, `postprocess.min_confidence` (umbral que afecta
  resultados). En el futuro: reglas de riesgo (control plane), umbrales de alerta (módulo de alertas).
- **B — Mecánica de runtime del media-plane** (cómo corre el plano): `topology`, `transport`,
  `rate_control`, `outputs`, `logging`, `debug`.

La columna A no es del media-plane: es la definición de un experimento que —cuando la plataforma
crezca— abarcará varios planos (medios, control, alertas). Mantenerla dentro del media-plane
implica que:

1. **No hay un lugar único para definir un experimento end-to-end.** Un experimento se reduce hoy
   a una corrida del media-plane; no existe el concepto de "configuración completa de la
   plataforma para este experimento".
2. **La declaración del experimento queda acoplada al código del plano que la ejecuta**, mezclando
   "qué quiero medir" con "cómo corre el plano".
3. **Los prompt sets** (la variable de estudio principal) viven en `configs/prompts/` del
   media-plane, sin un home conceptual que refleje que son material de experimentación.

## 2. Objetivos / No-objetivos

**Objetivos**
- Repo externo `e-ovrt_experimental-setup` como home de la **declaración de experimentos**:
  prompt sets + manifiestos de corrida.
- El media-plane conserva el **contrato** (schemas, `PromptPlan`, adaptadores) y las **capacidades**
  (catálogos `models/`, `datasets/`), y consume manifiestos externos.
- El experimento **referencia capacidades del plano por id**; cada plano resuelve el id contra su
  propio catálogo (patrón que escala a control-plane/alertas).
- El media-plane sigue siendo **ejecutable standalone** con sus fixtures de test.
- Reproducibilidad: el manifiesto registra su provenance (qué prompts/modelo/dataset) en el run.

**No-objetivos** (YAGNI para experimental)
- **No** se construye configuración de control-plane ni alertas: esos planos **no existen** (cero
  código, cero config). Se dejan como puntos de extensión documentados (§9), sin schema ni consumo.
- **No** se extrae un catálogo de runtime en el plano: la mecánica de runtime (B) viaja **inline**
  en el manifiesto (decisión de alcance; ver §4).
- **No** se versiona/serializa el manifiesto más allá de la provenance que ya emite el run.
- **No** se cambia el diseño interno de la capa de prompts (ver `2026-06-25-prompt-layer-design.md`);
  solo cambia **dónde viven** los prompt sets y la **raíz** de resolución de `prompts.ref` (§7).
- **No** se crea un runner/orquestador cross-plano: el media-plane se sigue invocando por su CLI;
  el manifiesto es declarativo, no ejecutable por sí mismo.

## 3. Arquitectura: fronteras (qué vive dónde)

```
e-ovrt_experimental-setup/        (repo hermano NUEVO; lo crea el usuario)
├── prompts/                      ← prompt sets (se mudan del media-plane)
│   ├── cr01_cr02_bench_v2.yaml
│   └── ppe_v2_descriptive.yaml
└── experiments/                  ← manifiestos de corrida (se mudan del media-plane)
    └── bench_v2/
        └── gdino_tiny.yaml

e-ovrt_media-plane/               (el plano: CONTRATO + CAPACIDADES)
├── src/eovrt_media/config/
│   ├── schemas.py                ← PromptsFile, PromptPlan, RunConfig   (SE QUEDA)
│   └── loader.py                 ← resolución de refs                   (CAMBIA: dos raíces, §5)
├── src/eovrt_media/models/       ← adaptadores, binding por construcción (SE QUEDA)
└── configs/
    ├── models/                   ← catálogo de capacidades del plano    (SE QUEDA)
    ├── datasets/                 ← catálogo de capacidades del plano    (SE QUEDA)
    └── (fixtures de smoke-test)  ← tests del plano, no experimentos     (SE QUEDA)

e-ovrt_datasets/                  (sin cambios)
```

**Principio rector:** el contrato lo define el consumidor (media-plane), el productor
(experimental-setup) se conforma a él. El plano expone capacidades por id; el experimento las
compone. El media-plane corre standalone con fixtures; experimental-setup es la fuente canónica de
experimentos.

## 4. El manifiesto de experimento

Archivo `e-ovrt_experimental-setup/experiments/<grupo>/<nombre>.yaml`. Estructura **híbrida**:
definición de experimento (A) + runtime del media-plane (B) inline.

```yaml
experiment:
  id: bench_v2_gdino_tiny           # provenance / agrupación de runs (mínimo; ver abajo)

# --- A: Definición del experimento ---
prompts:
  ref: ppe_v2_descriptive           # → raíz EXPERIMENTO: experimental-setup/prompts/ppe_v2_descriptive.yaml
  active_ids: [person, helmet, vest, bare_head]
model:
  ref: grounding-dino/gdino-tiny    # → raíz PLANO: media-plane/configs/models/grounding-dino/gdino-tiny.yaml
  device: cuda                      # override inline (semántica actual: catálogo + overrides)
source:
  ref: bench_v2_val                 # → raíz PLANO: media-plane/configs/datasets/bench_v2_val.yaml
postprocess:
  min_confidence: 0.25              # variable de estudio (A)

# --- B: Runtime del media-plane (inline) ---
run: { scenario: DBE, name: bench_v2_gdino_tiny }
topology: { mode: single_host }
transport: { backend: memory }
rate_control: { policy: deterministic }
outputs: { base_dir: runs/ }
logging: { level: INFO }

# --- Puntos de extensión (futuro; NO consumidos hoy, §9) ---
# control_plane: { ref: ... }       # reglas de riesgo (cuando exista el plano)
# alerts:        { ref: ... }       # umbrales/notificaciones (cuando exista el módulo)
```

**Bloque `experiment` (mínimo).** Solo `id` (str) como provenance/agrupación de corridas. El
media-plane lo propaga al `summary.json` del run (junto a la provenance ya existente). **No** se
añaden hipótesis/tags estructurados por ahora (YAGNI; se puede enriquecer luego sin romper nada).

**Por qué runtime inline (B) y no catálogo.** Decisión de alcance: evita el refactor de extraer un
catálogo de runtime en el plano. El costo es que cada manifiesto re-declara su mecánica de
deployment (se pierde reutilización de perfiles). Aceptable para experimental; revisable si los
manifiestos proliferan (ver §11).

**Qué se logra y qué no (honestidad de alcance).** Como B viaja inline, A y B **no** quedan
separados a nivel de campos dentro del manifiesto: siguen conviviendo en el mismo archivo. La
distinción A/B del §1 explica *qué partes son conceptualmente el experimento*, pero lo que este
diseño entrega no es esa separación de campos, sino **relocalización + propiedad**: la declaración
del experimento sale del plano hacia un home propio, y el plano queda como dueño del contrato y de
las capacidades (referenciadas por id). La separación de campos A/B (catálogo de runtime) queda
**diferida** como extensión aditiva futura (§11), no es objetivo de esta iteración.

**Relación con `RunConfig`.** El manifiesto **es** un `RunConfig` (mismas secciones), con dos
diferencias: (a) gana el bloque opcional `experiment`; (b) sus refs `prompts`/`model`/`source`
resuelven contra raíces distintas (§5). El pipeline sigue recibiendo un `RunConfig` resuelto
idéntico al de hoy — no se entera de la relocalización.

## 5. Resolución de referencias: dos raíces

El loader pasa de **una** raíz (`find_configs_root`, `loader.py:150`) a **dos**, separadas por
propiedad del recurso:

| Ref | Raíz de resolución | Cómo se descubre |
|---|---|---|
| `prompts.ref` | **experimento** | sube desde el manifiesto hasta el dir que contiene `prompts/` (raíz del repo experimental-setup) |
| `model.ref`, `source.ref` | **catálogo del plano** | repo-relative del media-plane (`Path(__file__).resolve().parents[...]` → dir con `configs/`); override `--catalog-root` / env |

**Mecanismo:**
- `find_plane_catalog_root()` (nuevo): descubre el `configs/` del media-plane relativo a la
  ubicación del paquete instalado (editable), igual que el repo `e-ovrt_datasets` localiza su raíz.
  Override explícito vía flag `--catalog-root <path>` o variable de entorno
  `EOVRT_MEDIA_CATALOG_ROOT` (para CI o layouts no estándar).
- `find_experiment_root(manifest_path)` (nuevo): sube desde el manifiesto hasta encontrar un dir
  con subdir `prompts/` (marcador de raíz del repo de experimentos). `prompts.ref` →
  `<experiment_root>/prompts/<ref>.yaml`.
- `_resolve_section_ref` (`loader.py:185`) se parametriza con la raíz correcta según la sección:
  `model`/`source` → raíz del plano; `prompts` → raíz del experimento.

**CLI.** `eovrt-media run --config <ruta-al-manifiesto-externo>` (también `run-producer` /
`run-consumer`). El manifiesto es **location-independent** para refs del plano: `model.ref` resuelve
igual sin importar dónde esté el manifiesto.

**Convención operativa (CWD).** El catálogo `datasets/` contiene rutas relativas
`../e-ovrt_datasets/...` que resuelven contra CWD (quirk actual; ver `CLAUDE.md` del workspace).
Se **preserva la convención de correr `eovrt-media` desde la raíz del media-plane**: así esas rutas
y `outputs.base_dir: runs/` siguen resolviendo igual que hoy. Solo cambia el `--config` (apunta
afuera). No se introduce dependencia nueva de CWD; se mantiene la existente.

## 6. Cambios en el media-plane

Acotados al borde de configuración; el pipeline no cambia.

1. **`config/loader.py`**: dividir `find_configs_root` en `find_plane_catalog_root()` +
   `find_experiment_root()`; parametrizar `_resolve_section_ref` por raíz según sección; aceptar
   override de catálogo (flag/env). El resto del flujo (`_derive_defaults`, `_validate_deployment`,
   instanciación de `RunConfig`, carga de `PromptsFile`) intacto.
2. **`cli.py`**: los comandos `run`/`run-producer`/`run-consumer` aceptan un `--config` que puede
   apuntar a un manifiesto externo; opción `--catalog-root` (o env) para override. Sin cambios de
   firma aguas abajo.
3. **`config/schemas.py`**: añadir el bloque opcional `experiment` (`ExperimentSection` con `id:
   str | None = None`, extensible). `RunConfig` gana el campo opcional; `to_effective_dict` lo
   incluye en provenance.
4. **Provenance del run**: añadir `experiment_id` al contrato `RunSummary` (`contracts/events.py`,
   que ya tiene `prompt_set_id` y `run_descriptor`); `RunArtifactWriter` lo serializa en `summary.json`
   si está presente. (Evaluar en el plan si conviene reutilizar `run_descriptor` en vez de un campo
   nuevo.)
5. **Reubicación de archivos** (§8): mover prompt sets y manifiestos de experimento al repo nuevo;
   degradar los configs de smoke-test a fixtures del plano.

## 7. Relación con el spec de prompts (`2026-06-25-prompt-layer-design.md`)

El diseño **interno** de la capa de prompts no cambia: `PromptPlan`, binding por construcción,
fraseo por backend, firma de adaptadores, `DetectionNormalizer` — todo queda como está especificado
ahí. Solo cambian dos cosas, que se reflejan como **enmienda** a ese spec:

| En el spec de prompts | Antes | Ahora |
|---|---|---|
| Ubicación de los prompt sets (§3, §9.3) | `media-plane/configs/prompts/<set>.yaml` | `e-ovrt_experimental-setup/prompts/<set>.yaml` |
| Raíz de resolución de `prompts.ref` | raíz única `configs/` | raíz del experimento (§5) |
| Schema / `build_plan` / adaptadores / contratos | media-plane | **media-plane (sin cambios)** |

Los prompt sets migrados en el plan de prompts (`cr01_cr02_bench_v2.yaml` congelado,
`ppe_v2_descriptive.yaml` nuevo) **aterrizan en `experimental-setup/prompts/`**, no en el
media-plane. La reproducibilidad byte-equivalente del BENCH se mantiene (las frases no cambian, solo
la ubicación del archivo).

## 8. Migración (corte limpio)

**Se mueve a `e-ovrt_experimental-setup`** (repo creado por el usuario):
- `configs/prompts/*` → `prompts/`.
- Experimentos reales: `configs/runs/experiments/bench_v2/*`, `configs/runs/{gdino,yoloe,yoloe_video}.yaml`
  → `experiments/` (reorganizados por grupo).

**Queda en `e-ovrt_media-plane`:**
- Todo `src/` (schemas, loader, adaptadores, contratos).
- Catálogos `configs/models/`, `configs/datasets/`.
- Fixtures de smoke-test (`configs/runs/mock*.yaml`) — son tests del plano, no experimentos.
  Propuesta: moverlos a `tests/fixtures/` para que la frontera quede explícita.
- **Un prompt set mínimo de test** en `tests/fixtures/prompts/` (p.ej. `test_ppe.yaml`). **Imprescindible:**
  el test suite del plano debe quedar **self-contained**, sin depender de que exista el repo hermano
  `experimental-setup`. Hoy ≥5 tests cargan `RunConfig`s con `prompts.ref` y romperían si los sets se
  van sin reemplazo local:
  - `tests/test_config.py` — `PROMPTS_PATH` apunta directo a `configs/prompts/cr01_cr02_v2_short.yaml`;
    `test_prompts_loaded` carga `gdino.yaml` (con `prompts.ref`).
  - `tests/test_pipeline_mock.py` — carga `gdino.yaml`.
  - `tests/test_two_node_local.py` — usa `prompts_ref="cr01_cr02_bench_v2"`.
  - (`tests/test_config_refs.py` ya crea su propio catálogo temporal → no se ve afectado.)
  Acción: estos tests se repuntan al fixture local y a una raíz de experimento de prueba. La
  resolución de `prompts.ref` debe poder apuntar a `tests/fixtures/` (raíz de experimento de test),
  no solo al repo hermano.

**Configs locales/efímeros** (`configs/runs/local/`, `configs/runs/local/generated/`): son salidas
generadas localmente, típicamente git-ignored. No se migran; se documenta que el flujo que los genera
ahora escribe (o lee) manifiestos según el nuevo layout. (Verificar en el plan qué los genera.)

**Orden sugerido de implementación** (a detallar en el plan):
1. Cambios de loader/CLI/schema en el media-plane (dos raíces + `experiment` + override), con tests
   apuntando a fixtures locales y a un manifiesto externo de prueba.
2. Reubicación física de prompt sets y experimentos al repo nuevo.
3. Verificación end-to-end: una corrida del BENCH desde el manifiesto externo reproduce los
   resultados previos.

*(Nota: este orden es independiente del plan de prompts; ese rediseño interno puede aterrizar antes,
in-place, y luego relocalizarse. Lo resuelve el plan de implementación.)*

## 9. Puntos de extensión (control plane / alertas)

Cuando esos planos existan, el patrón es el mismo que para el media-plane:
- Cada plano expone un catálogo de capacidades por id (reglas de riesgo, perfiles de alerta).
- El manifiesto los referencia: `control_plane.ref: <id>`, `alerts.ref: <id>`.
- Cada plano resuelve el id contra **su propio** catálogo (su propia raíz), igual que el media-plane
  resuelve `model.ref`/`source.ref` contra el suyo.

Hoy se dejan **comentados** en el manifiesto y **sin** schema ni consumo. No se especula con su
estructura: se diseñarán cuando exista el consumidor (mismo principio que rige todo este diseño).

## 10. Testing

- `loader`: descubrimiento de raíz del plano (repo-relative) y override por flag/env; resolución de
  `model.ref`/`source.ref` contra raíz del plano y de `prompts.ref` contra raíz del experimento;
  manifiesto externo (fuera del árbol del media-plane) resuelve correctamente; error claro si no se
  encuentra `prompts/` para un manifiesto dado.
- `schemas`: `experiment` opcional (default ausente); `experiment.id` se propaga a `to_effective_dict`.
- `cli`: `--config` con ruta externa; `--catalog-root`/env override.
- `run_artifact_writer`: `experiment.id` aparece en `summary.json` cuando está presente.
- End-to-end con `MockDetector` y un manifiesto externo de fixture: el pipeline produce el mismo
  `RunConfig` resuelto y los mismos artefactos que con un config local equivalente.
- Reproducibilidad: una corrida desde el manifiesto externo migrado produce las **mismas
  detecciones** (boxes/scores) que el run previo, porque las frases alimentadas al modelo son
  byte-equivalentes. *Caveat:* si el rediseño de la capa de prompts ya aterrizó, el **esquema** del
  `detections.jsonl` difiere (campos `prompt_id`/`strategy`/`condition_id` ahora poblados) — la
  reproducibilidad es de los **resultados**, no del registro byte-a-byte. La relocalización **sola**
  (sin el cambio de prompts) sí produce un archivo idéntico salvo timestamps.
- `make test` (pytest) y `make lint` (ruff) en verde.

## 11. Riesgos

- **Resolución cross-repo frágil al layout.** El descubrimiento repo-relative del catálogo del plano
  asume el media-plane instalado editable y un `configs/` localizable. Mitigación: override explícito
  `--catalog-root`/env; mensajes de error claros cuando una raíz no se encuentra.
- **Dependencia de CWD para datasets/outputs.** Se hereda el quirk actual (`../e-ovrt_datasets`
  relativo a CWD). Mitigación: preservar la convención "correr desde la raíz del media-plane";
  documentarlo en el README del repo de experimentos. No se agrava respecto de hoy.
- **Runtime inline duplicado entre manifiestos.** Sin catálogo de runtime, perfiles de deployment
  (two-node, etc.) se re-declaran por experimento. Mitigación: si proliferan, extraer un catálogo
  `configs/runtime/` en el plano es un cambio aditivo y compatible (el manifiesto pasaría a
  `runtime.ref` con overrides inline, mismo patrón que `model.ref`).
- **Dos repos que deben mantenerse en sync** (contrato vs instancias). Mitigación: el contrato vive
  en un solo lugar (media-plane); el repo de experimentos solo produce YAML validado por ese
  contrato. Un cambio de schema rompe la validación de forma visible, no silenciosa.
- **Coordinación con el plan de prompts.** Ambos trabajos tocan loader y prompt sets. Mitigación:
  secuenciar (prompts interno primero, relocalización después) o unificar en un solo plan; lo decide
  el plan de implementación.
