# ADR-0003: Integración de modelos mediante adaptadores

## Estado
Aceptada

## Contexto
El proyecto debe comparar modelos OVD sin acoplar el pipeline a una implementación concreta.

## Decisión
Cada modelo se integrará mediante un adaptador que implemente una interfaz común (`BaseDetectorAdapter`).

## Consecuencias
Grounding DINO, YOLOE y futuros modelos podrán intercambiarse desde configuración sin modificar el pipeline.
