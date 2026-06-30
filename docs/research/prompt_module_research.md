# Investigación — Diseño de la capa de prompts OVD (E-OVRT-VDP)

**Fecha:** 2026-06-26
**Ámbito:** capa de prompts del `e-ovrt_media-plane` (GDINO / MM-GDINO + YOLOE).
**Insumos:** `docs/contexto/investigacion-prompts.md` (informe de partida, ya anotado) y un
barrido de investigación multi-fuente sobre los trabajos OVD/VLM nombrados.

> **Estado de verificación (leer primero).** El barrido se hizo con el harness de
> *deep-research* (fan-out de búsquedas + verificación adversarial 2-de-3). La fase de
> **síntesis y la mayoría de las verificaciones se cortaron por límite de gasto mensual de
> la organización**, no por contenido. Por eso cada hallazgo lleva un nivel de confianza:
> - **[VERIFICADO 3-0]** — pasó verificación adversarial unánime.
> - **[LIT]** — claim extraído de la fuente y **consistente con literatura establecida**,
>   pero su verificación quedó incompleta. Tratar como "probable, re-confirmar antes de citar
>   en un entregable formal".
> Las fuentes primarias están en §7. Re-ejecutar la verificación cuando se renueve el
> presupuesto (`Workflow resume` del run `wf_3f33014a-6e0`).

---

## 1. TL;DR — decisiones de diseño que la evidencia respalda

1. **Fraseo por backend NO es cosmético: es arquitectónico.** Los modelos tipo CLIP/YOLOE
   operan sobre **frases nominales cortas** (la entrada efectiva se reduce a *noun phrases*);
   GDINO admite captions más ricos pero con costo por longitud. Confirma la decisión central
   del spec (`phrasings.gdino` vs `phrasings.yoloe`). **[LIT]**
2. **No intentar aprender prompts (CoOp/DetPro) en este proyecto.** El prompt-learning da
   ganancias solo *re-entrenando* sobre proposals de detección, y los prompts *estáticos*
   aprendidos **sobreajustan a las clases base y degradan en clases nuevas** — peor que
   templates escritos a mano. Para vocabulario abierto, el *prompt engineering manual* +
   ensembling de templates es la opción correcta sin entrenar. **[LIT]**
3. **La ausencia de EPP NO se resuelve con prompts negados.** Los VLM/OVD tienen **sesgo
   afirmativo**: ignoran la negación ("person without helmet" ≈ "person ... helmet"). →
   **estrategia indirecta** (detectar `helmet`/`vest` + `person` y resolver la ausencia
   fuera del modelo) es la única defendible. Refuerza el corte 🔀 (ausencia = plano de control). **[LIT]**
4. **Atributos finos (casco/chaleco/alta-visibilidad) son el punto débil de los OVD.** Los
   benchmarks de granularidad fina muestran que el desempeño **colapsa al agregar hard
   negatives** (atributos sustituidos). → hay que medir con negativos, no solo positivos. **[LIT]**
5. **YOLOE > YOLO-World a igual backbone** (LVIS zero-shot: +3.5 AP, 3× menos costo de
   entrenamiento, 1.4× más rápido). Valida priorizar YOLOE sobre YOLO-World. **[VERIFICADO 3-0]**
6. **El patrón "prompt-then-detect / offline vocabulary" es el modelo a imitar** para la
   capa de prompts: codificar el vocabulario una vez y reusarlo (cachear/reparametrizar),
   en vez de re-encodear por imagen. **[VERIFICADO 3-0]**

---

## 2. Hallazgos por tema

### 2.1 Fraseo por arquitectura (descriptivo vs etiqueta corta)

- **YOLO-World / YOLOE (familia CLIP-text):** el codificador de texto es el Transformer de
  CLIP; cuando la entrada es un caption o expresión referencial, **se extraen primero las
  frases nominales con un algoritmo n-gram** antes de codificar. La unidad efectiva es la
  **etiqueta/frase nominal corta**, no la oración libre. → para YOLOE conviene `["helmet"]`,
  `["safety vest"]`, no oraciones. **[LIT]**
- **CLIP templates / ensembling:** "a photo of a [CLASS]" y el **promedio de múltiples
  templates** mejora la robustez del clasificador zero-shot. → para YOLOE, varias frases
  por clase que colapsan al mismo canónico actúa como un *ensembling* barato (alineado con el
  diseño de `phrasings` multi-frase del spec). **[LIT]**
- **Grounding DINO:** grounding por caption con concatenación de categorías y matching de
  sub-spans; sensible a la **longitud del caption** (captions largos diluyen / cambian el
  matching). → `phrasings.gdino` puede usar sinónimos descriptivos ("hard hat", "safety
  helmet") **pero el vocabulario activo total debe acotarse** para no inflar el caption. **[LIT]**

> **Implicación de diseño:** mantener `phrasings.{gdino,yoloe,default}` (spec §3). Para GDINO,
> sinónimos descriptivos cortos; para YOLOE, etiquetas/nominales cortas y varias frases =
> ensembling. Vigilar el tamaño del caption GDINO (ver §2.6).

### 2.2 Prompt learning (CoOp/CoCoOp/DetPro) — qué es aprovechable sin entrenar

- **CoOp** aprende vectores de contexto continuos; **sobreajusta a clases base y generaliza
  mal a clases no vistas**. En promedio sobre 11 datasets, en clases "new": CoOp **63.22** vs
  **74.22** de templates CLIP escritos a mano; **CoCoOp** (prompt condicionado por imagen)
  recupera a **71.69**. → para vocabulario abierto, **templates manuales ≥ prompts aprendidos
  estáticos**. **[LIT]**
- **DetPro** (Du et al.) adapta prompt-learning a detección con dos piezas específicas
  (interpretación de *background* + *context grading* por IoU) y mejora ViLD en LVIS novel
  **+3.4 AP_box / +3.0 AP_mask** — pero **requiere re-entrenar** los embeddings sobre
  proposals; **no es drop-in**. **[LIT]**

> **Implicación de diseño:** **descartar** prompt-learning para esta fase (confirma el corte
> ⛔ del informe). Invertir el esfuerzo en *prompt engineering* manual + ensembling de
> templates + selección de vocabulario. La única idea transferible "barata" de CoCoOp
> (condicionar por instancia) requiere red auxiliar → fuera de alcance.

### 2.3 Detección de AUSENCIA de EPP (directo vs indirecto)

- Los VLM/OVD presentan **sesgo afirmativo**: tienden a detectar lo mencionado e **ignoran la
  negación**; "person without hard hat" se comporta parecido a mencionar "person" y "hard hat".
  Hay líneas de trabajo de *negation-aware adaptation* (p.ej. NegToMe) pero son
  modificaciones de modelo, no prompt engineering. **[LIT]**

> **Implicación de diseño:** la **estrategia indirecta** (`positive_evidence`: detectar
> `helmet`/`vest`/`person`; la ausencia se infiere fuera del modelo) es la correcta. El
> prompt directo de ausencia queda como **variante diagnóstica**, no como camino primario.
> Esto **refuerza** el corte del informe: la lógica de ausencia es del **plano de control**
> (🔀), y la capa de prompts solo aporta `strategy: direct_absence | positive_evidence` como
> metadato.

### 2.4 Atributos finos y hard negatives (FG-OVD, OVDEval)

- **FG-OVD:** los hard negatives se construyen por **sustitución de atributos** (mismo objeto,
  atributo cambiado); la **capacidad discriminativa colapsa a medida que aumentan los
  confounders**. Casco/chaleco/alta-visibilidad son exactamente este caso (atributo fino sobre
  "person"). **[LIT]**
- **OVDEval:** benchmark de **9 sub-tareas** (atributos, posición, relaciones, negación…);
  observa que la **AP estándar da puntajes engañosamente altos** y propone **NMS-AP** para
  penalizar detecciones redundantes/confiadas-pero-erróneas. **[LIT]**
- Consenso: los OVD mainstream **priorizan lo coarse-grained** y son **débiles en
  fine-grained**. **[LIT]**

> **Implicación de diseño:** (1) construir **vocabularios con hard negatives** explícitos
> (p.ej. añadir `bare_head` y prendas no-reflectivas como distractores) y **medir con y sin
> negativos**. (2) Reportar más que AP@0.5 cuando se pueda (la evaluación vive en el repo
> `datasets`; ahí cabe NMS-AP / recall por clase). (3) Esto confirma por qué `bare_head` rinde
> débil en el Sprint 2 — es un atributo fino sobre la cabeza.

### 2.5 Prompt aislado vs vocabulario completo (interferencia)

- No quedó un número verificado del barrido (la síntesis se cortó), pero la mecánica está
  clara y es consistente con FG-OVD/OVDEval: **agregar clases semánticamente cercanas al
  vocabulario activo introduce competencia** y puede bajar precisión/recall de una clase
  respecto de evaluarla aislada. **[LIT, pendiente de número]**

> **Implicación de diseño:** soportar de fábrica el contraste **isolated vs full_context** —
> que el spec ya cubre con `active_ids` + sets alternativos (no hace falta entidad nueva).
> **Acción de medición** (no de diseño): correr cada clase aislada y en el set completo y
> comparar. Pendiente: re-verificar magnitudes cuando haya presupuesto.

### 2.6 Caching / reparametrización de embeddings y límites de vocabulario

- **YOLO-World "prompt-then-detect":** los prompts se codifican **una sola vez** en un
  **vocabulario offline** que varía según necesidad; ese vocabulario se **reparametriza en
  pesos** (conv/linear) y **elimina el forward del text-encoder en runtime**. **[VERIFICADO 3-0]**
- Los embeddings offline `W ∈ R^{C×D}` (C = nº de nombres) se **precomputan** y se inyectan
  como pesos en inferencia. **[VERIFICADO 3-0]**
- **YOLOE (RepRTA):** cachea embeddings de texto y los refina con una red auxiliar
  **reparametrizable** (coste de inferencia ~0). **[LIT]**
- **Límites de tamaño:** GDINO está acotado por la **longitud del caption** (a más clases,
  caption más largo → riesgo de dilución); YOLOE/YOLO-World escalan a vocabularios grandes
  porque el costo se paga una vez (offline). **[LIT, magnitudes no verificadas]**

> **Implicación de diseño:** el `PromptPlan` del spec **es exactamente** la "offline
> vocabulary" precomputada para una corrida. Recomendación: que `PromptPlan` sea el punto
> natural para **cachear `set_classes()`/embeddings** por (set, backend) — ya previsto en el
> spec para YOLOE (`_prompts_set` comparado contra `plan.texts()`). Para GDINO, **acotar el
> nº de frases activas** y vigilar la longitud del caption.

### 2.7 Idioma (inglés vs español)

- No hubo hallazgo verificado específico. Por construcción, CLIP/GDINO se entrenan
  mayoritariamente en inglés → **prompts primarios en inglés** (coincide con la decisión no
  negociable del informe §13). El español se trata como **variante experimental medible**
  (otro archivo de set), no como primario. **[LIT/criterio]**

### 2.8 Patrones publicados de "módulo de prompts"

- El patrón canónico reusable es **"prompt-then-detect / offline vocabulary"** de YOLO-World:
  catálogo de prompts → vocabulario activo codificado una vez → reparametrización. **[VERIFICADO 3-0]**
- CLIP aporta el patrón de **prompt ensembling** (varios templates promediados por clase).
  **[LIT]**
- No apareció evidencia de que haga falta una maquinaria pesada de "catálogo + variantes +
  runner" como entidad de software: los proyectos resuelven esto con **archivos de
  vocabulario** + precómputo. Esto **respalda** el corte ⛔ del informe (versionar por
  archivos git, no por entidades `PromptVariant`/`ActiveVocabulary`).

---

## 3. Recomendaciones concretas para nuestra capa de prompts

1. **Conservar el esquema por backend** (`phrasings.{gdino,yoloe,default}`) — validado por §2.1.
2. **YOLOE:** frases cortas/nominales; **múltiples frases por clase = ensembling** (colapsan
   al mismo `canonical`). Coincide con el diseño multi-frase del spec.
3. **GDINO:** sinónimos descriptivos cortos en `phrasings.gdino`; **acotar el vocabulario
   activo** para no inflar el caption (regla práctica: vigilar longitud, no meter sinónimos
   indiscriminados). Crear `ppe_v2_descriptive.yaml` como set GDINO-enriquecido **separado**
   del BENCH congelado, para A/B.
4. **Ausencia de EPP = estrategia indirecta** (`positive_evidence`). Añadir `strategy` como
   **metadato** (no lógica). El prompt directo de ausencia solo como set diagnóstico.
5. **Hard negatives de primera clase:** soportar sets con distractores (p.ej. `bare_head`,
   prendas no-reflectivas) y **medir con/sin negativos**. Es donde más se juega la calidad
   en atributos finos.
6. **isolated vs full_context** vía `active_ids` + sets (sin entidad nueva). Dejarlo como
   **protocolo de medición** documentado.
7. **No** implementar prompt-learning ni `PerceptionEvent`/runner de matriz en esta capa
   (confirmado por §2.2 y por el alcance del media-plane).
8. **`PromptPlan` como "offline vocabulary"**: punto único de caché de `set_classes()`/
   embeddings por (set, backend).

---

## 4. Qué nos estábamos perdiendo (respecto del informe de partida)

1. **Sesgo afirmativo / fallo en negación** (no estaba explícito): es *la* razón técnica por
   la que la ausencia debe ser indirecta. El informe lo intuía ("indirecta"), pero ahora hay
   fundamento: los modelos **no entienden "without"**.
2. **Colapso con hard negatives** (FG-OVD): el informe pedía hard negatives, pero no
   dimensionaba que el desempeño **se desploma** con confounders → hay que **medirlo**, es el
   riesgo principal de casco/chaleco.
3. **NMS-AP / AP engañosa** (OVDEval): AP@0.5 sola sobreestima; conviene complementar métricas
   (en el repo `datasets`).
4. **Templates manuales > prompts aprendidos** en vocabulario abierto (CoOp 63.2 vs 74.2):
   justifica cuantitativamente **no** invertir en prompt-learning.
5. **"Prompt-then-detect / offline vocabulary"** como patrón de referencia para el módulo:
   valida que `PromptPlan` sea el lugar de caché/reparametrización, y que el versionado sea
   por archivos, no por entidades.
6. **La entrada efectiva de YOLOE/YOLO-World son noun phrases** (extracción n-gram): confirma
   que el fraseo corto para YOLOE no es preferencia estética sino del pipeline del modelo.

---

## 5. Impacto en el spec (propuestas de ajuste)

Ninguno invalida el spec; lo **refuerzan**. Ajustes menores a considerar antes del plan:

- **Confirmar** `strategy` y `condition_id` como metadatos opcionales (ya recomendado).
- **Añadir** una nota en el spec de que `phrasings.gdino` debe **acotar longitud de caption**
  (no sinónimos ilimitados) — riesgo §2.1/§2.6.
- **Documentar** el protocolo isolated-vs-full_context y "medir con/sin hard negatives" como
  **prácticas de evaluación** (no como features de la capa; viven en el repo `datasets`).
- **Dejar registrado** que prompt-learning, NMS-AP y negation-aware están **fuera de alcance**
  con la justificación de §2.2/§2.3/§2.4.

---

## 6. Pendiente (cuando haya presupuesto)

- Re-ejecutar verificación adversarial de los claims **[LIT]** (resume del run
  `wf_3f33014a-6e0`) y completar la fase de síntesis con citas textuales por claim.
- Obtener **números** para "isolated vs full_context" (§2.5) y para límites de caption GDINO.

## 7. Fuentes primarias (parcialmente verificadas)

- CoOp — *Learning to Prompt for Vision-Language Models*, Zhou et al. (arXiv:2109.01134).
- CoCoOp — *Conditional Prompt Learning for VLMs*, Zhou et al. (CVPR 2022).
- DetPro — *Learning to Prompt for Open-Vocabulary Object Detection*, Du et al. (arXiv:2203.14940).
- FG-OVD — benchmark de atributos finos / hard negatives.
- OVDEval — benchmark de 9 sub-tareas + NMS-AP.
- CLIP — Radford et al. (templates + ensembling).
- Grounding DINO — caption grounding + sub-span matching.
- YOLO-World — *prompt-then-detect / offline vocabulary* (arXiv:2401.17270).
- YOLOE — *Real-Time Seeing Anything*, RepRTA (arXiv:2503.07465).
- OWL-ViT / OWLv2 — detección por embeddings de texto.
- Florence-2 — prompting multitarea.
- (Negación) líneas de *negation-aware adaptation* tipo NegToMe.
