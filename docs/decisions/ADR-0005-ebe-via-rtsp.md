# ADR-0005 — EBE vía RtspSource (fuente viva)

**Fecha:** 2026-06-21  
**Estado:** Aceptado  
**Autores:** equipo E-OVRT-VDP  

---

## Contexto

El escenario EBE (Edge-Based Evaluation) requiere ingestar frames en tiempo real
desde una cámara IP o cámara de borde. Las alternativas consideradas eran:

1. Implementar `LiveSource` como clase abstracta intermedia que RTSP y OAK-D
   heredarían.
2. Implementar `RtspSource` directamente en `BaseSource`, sin intermediario
   abstracto.
3. Delegar la ingesta viva a un proceso externo (MediaMTX u otro servidor de
   stream) y consumir desde un archivo temporal.

## Decisión

Se implementó **`RtspSource` heredando directamente de `BaseSource`** (opción 2),
junto con un `OakDSource` diferido del mismo estilo.

`LiveSource` (la clase abstracta intermedia de la opción 1) fue descartada y
eliminada del árbol porque:
- Añadía una capa de herencia sin lógica propia.
- `BaseSource` ya define el contrato correcto: `__iter__` + `stop()` + `__len__`
  con `TypeError` para fuentes sin longitud.
- RTSP y OAK-D difieren demasiado en inicialización como para compartir una base
  intermedia sin forzar abstracción prematura.

## Implicaciones de diseño

- `RtspSource` embebe `pixel_data` directamente en `VisualUnit` para evitar
  reabrir el stream RTSP en `normalize_spatial` (la sonda de URI y la lectura de
  frames ocurren en el mismo flujo).
- El rate control con `policy=bounded_freshness` y `buffer_size` acota la
  antigüedad de los frames: unidades más viejas que `max_staleness_ms` son
  descartadas con `units_dropped` contabilizado en `summary.json`.
- `RtspSource.__len__` lanza `TypeError` (sin longitud definida), conforme al
  contrato de `BaseSource`.
- El campo `source.kind=live` se deriva automáticamente de `source.type=rtsp`
  en `loader.py`; el loader a su vez deriva `policy=bounded_freshness`.

## Consecuencias

- **Positivas:** código más simple, sin herencia intermedia, sin la fricción de
  una clase abstracta vacía. El contrato de `BaseSource` es suficientemente
  expresivo.
- **A monitorear:** `OakDSource` queda diferido y lanza `NotImplementedError` hasta
  integrar el SDK DepthAI. Cuando se integre, deberá seguir el mismo patrón de
  `RtspSource` (pixel_data en VisualUnit, stop() para interrumpir el loop).
- **FP16:** el formato de payload `fp16` está implementado de extremo a extremo:
  normalización a `[0, 1]`, serialización raw preservando `float16` y transporte
  two-node. JPEG permanece limitado a `uint8_rgb`; una configuración JPEG+FP16
  selecciona raw de forma explícita.
