# ADR-0002: DBE como primer escenario de implementación

## Estado
Aceptada

## Contexto
El sistema debe estabilizar la ruta crítica perceptiva antes de incorporar streaming, cámaras o edge nodes.

## Decisión
La primera implementación se hará sobre imágenes y videos locales en modo DBE (Dataset-Based Evaluation).

## Consecuencias
Se reduce complejidad inicial y se obtiene una base reproducible para comparar modelos, prompts y métricas.
