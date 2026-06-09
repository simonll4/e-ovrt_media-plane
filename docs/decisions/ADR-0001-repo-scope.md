# ADR-0001: Repositorio dedicado al plano de medios

## Estado
Aceptada

## Contexto
La arquitectura de E-OVRT-VDP separa plano de medios y plano de control.

## Decisión
Implementar el plano de medios en un repositorio separado llamado `eovrt-media-plane`.

## Incluye
- Lectura de fuentes visuales.
- Inferencia OVD.
- Normalización de detecciones.
- Métricas básicas.
- Persistencia experimental de resultados.

## Excluye
- Patrones de riesgo.
- Alertas.
- UI.
- Notificaciones.
- MOT formal.
- Zonas.
- Fine-tuning.

## Consecuencias
El plano de control consumirá evidencia perceptiva normalizada generada por este repositorio.
