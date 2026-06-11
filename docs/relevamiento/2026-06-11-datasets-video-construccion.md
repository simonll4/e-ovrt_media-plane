# Relevamiento de datasets de video para CR-01 y CR-02

**Fecha:** 2026-06-11

## Objetivo

Encontrar material de video para probar el pipeline sobre las dos condiciones
priorizadas:

- **CR-01:** persona sin casco en zona de obra.
- **CR-02:** persona sin chaleco reflectivo en zona de trafico o maquinaria.

El plano de medios no concluye que existe un riesgo. Debe producir evidencia
observable para `person`, `helmet` y `vest`; la asociacion persona-EPP y la
persistencia temporal corresponden al plano de control.

## Conclusion

No se encontro un dataset publico, descargable y listo para usar que cumpla al
mismo tiempo estos requisitos:

1. videos o secuencias temporales;
2. obras reales;
3. personas visibles;
4. casos con y sin casco;
5. casos con y sin chaleco;
6. licencia y procedencia suficientemente claras.

La revision OpenConstruction releva 51 datasets visuales de construccion y
reporta que menos del 3% contiene video o secuencias temporales. El dataset de
video explicitamente destacado, *Earthmoving Equipment Tracking*, contiene 479
videos de actividades de maquinaria, no anotaciones de casco o chaleco.

Por lo tanto, la opcion recomendada es construir un benchmark local y congelado
con clips seleccionados de Pexels o Pixabay, acompanado por un manifiesto y una
anotacion manual minima. Los datasets de imagen anotados se mantienen como
complemento cuantitativo, no como sustituto de la prueba temporal.

## Fuentes evaluadas

| Fuente | Modalidad y cobertura | Licencia | Decision |
|---|---|---|---|
| [OpenConstruction](https://github.com/ruoxinx/OpenConstruction-Datasets) | Catalogo de 51 datasets de construccion. Documenta la escasez de video y permite descartar rapidamente candidatos solo de imagen. | Catalogo MIT; cada dataset conserva su propia licencia. | Usar como referencia de cobertura, no como dataset. |
| Earthmoving Equipment Tracking (Roberts y Golparvar-Fard, 2019) | 479 videos, 7 actividades de excavadoras y camiones. Tiene temporalidad y obra real, pero no EPP. | CC BY 4.0 segun OpenConstruction. | Descartado para CR-01/CR-02; util en el futuro para maquinaria. |
| [SH17](https://github.com/ahmadmughees/SH17dataset) | 8.099 imagenes, 75.994 instancias y 17 clases. Incluye `Person`, `Helmet` y `Safety-vest`; mezcla construccion y entornos industriales. No es video. | CC BY-NC-SA 4.0 y condiciones de las imagenes de Pexels. | Mejor complemento estatico para las tres entidades del pipeline. |
| [SFCHD](https://github.com/lijfrank/SFCHD-SCALE) | 12.373 imagenes de dos plantas quimicas reales; casco y ropa de seguridad, incluidos escenarios de baja iluminacion. No es obra edilicia ni video. | El repositorio no declara una licencia explicita. | Solo evaluacion exploratoria hasta aclarar licencia. |
| [SHWD](https://github.com/njvisionpower/Safety-Helmet-Wearing-Dataset) | 7.581 imagenes; 9.044 objetos con casco y 111.514 cabezas sin casco. No cubre chaleco ni video. | MIT en el repositorio. | Buen complemento cuantitativo para CR-01. |
| MOCS local (`data/samples/dataset_v1`) | Imagenes reales de obra con anotacion de `Worker`; casco y chaleco no tienen ground truth. | CC BY 4.0 segun el manifiesto local. | Mantener para dominio de obra y evaluacion cualitativa. |
| [Pexels Videos](https://www.pexels.com/search/videos/construction%20worker/) | Clips MP4 de obra e industria, con variedad de planos y EPP. Sin anotaciones. | Uso y modificacion gratuitos; aplican restricciones sobre redistribucion y personas identificables. | Fuente primaria para curar clips locales. |
| [Pixabay Videos](https://pixabay.com/videos/search/construction%20worker/) | Clips HD/4K cortos de obras, trabajadores y maquinaria. Sin anotaciones. | Uso y adaptacion gratuitos; no distribuir el contenido sin valor agregado de forma independiente. | Fuente secundaria para cubrir huecos. |

El preprint de 2026 sobre *Ironsite* menciona un corpus de 12 videos, pero no se
localizo una distribucion publica con licencia y descarga verificables. No debe
considerarse disponible hasta que aparezca un artefacto oficial.

## Benchmark recomendado

Crear `video_benchmark_v1` con clips individuales de 10 a 30 segundos. El
objetivo inicial son 8 a 12 clips y entre 2 y 4 minutos totales.

| Escenario | Casco | Chaleco | Personas | Contexto minimo |
|---|---:|---:|---:|---|
| V01 compliant | Si | Si | 1+ | Obra real; control positivo de EPP |
| V02 CR-01 | No | Si | 1+ | Cabeza y torso visibles |
| V03 CR-02 | Si | No | 1+ | Trafico, vehiculo o maquinaria visible |
| V04 CR-01 + CR-02 | No | No | 1+ | Obra real, no bricolaje domestico |
| V05 mixto | Mixto | Mixto | 3+ | Personas con distinto cumplimiento |
| V06 distancia | Variable | Variable | 3+ | Personas pequenas u ocluidas |
| V07 adverso | Variable | Variable | 1+ | Baja luz, lluvia, polvo o movimiento |
| V08 negativo | N/A | N/A | 0 | Obra o maquinaria sin personas |

No alcanza con buscar "construction worker": cada clip debe revisarse
visualmente y asignarse a un escenario solo si el casco y el chaleco son
observables durante un intervalo util.

## Manifiesto minimo

Versionar un CSV o JSON, no los videos de terceros, con:

```text
clip_id
local_filename
source_url
source_provider
creator
license
downloaded_at
sha256
duration_s
fps
width
height
scenario
helmet_state
vest_state
people_count_range
machinery_or_traffic
difficulty_tags
review_notes
```

Para una primera evaluacion temporal, anotar intervalos a nivel de persona:

```text
clip_id, start_ms, end_ms, person_ref, helmet, vest, visibility, notes
```

Estados recomendados para `helmet` y `vest`: `present`, `absent`, `unknown`.
`unknown` evita convertir oclusiones o baja resolucion en falsos casos de
incumplimiento.

## Protocolo de uso

1. Descargar los clips a `data/raw/video_benchmark_v1/`.
2. Conservar cada clip original y registrar SHA-256 y URL.
3. Normalizar copias de trabajo a MP4/H.264, sin audio, conservando FPS.
4. Ejecutar primero cada clip por separado para no perder trazabilidad.
5. Crear opcionalmente un montaje de 45 a 60 segundos como `sample.mp4` para
   smoke tests, con separadores visuales entre escenarios.
6. Muestrear inicialmente a 2 FPS. Para clips con movimiento rapido, repetir a
   5 FPS.
7. Comparar detecciones por etiqueta y revisar previews contra los intervalos
   anotados.

## Criterios de aceptacion

El benchmark queda listo cuando:

- V01 a V04 tienen al menos dos clips cada uno;
- existe al menos un caso mixto y un negativo sin personas;
- hay planos cercanos y lejanos;
- todos los clips tienen URL, licencia, fecha y SHA-256;
- ningun caso `absent` fue inferido solo por oclusion;
- los archivos son legibles por `cv2.VideoCapture`;
- cada escenario se probo con YOLOE y Grounding DINO usando los mismos frames.

## Fuentes

- OpenConstruction, revision y catalogo:
  <https://arxiv.org/abs/2508.11482>
- OpenConstruction, catalogo:
  <https://github.com/ruoxinx/OpenConstruction-Datasets>
- SH17:
  <https://github.com/ahmadmughees/SH17dataset>
- SFCHD:
  <https://github.com/lijfrank/SFCHD-SCALE>
- SHWD:
  <https://github.com/njvisionpower/Safety-Helmet-Wearing-Dataset>
- Pexels, licencia:
  <https://www.pexels.com/license/>
- Pixabay, resumen de licencia:
  <https://pixabay.com/service/license-summary/>
- Ironsite, preprint:
  <https://arxiv.org/abs/2605.19869>
