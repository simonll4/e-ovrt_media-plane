# Diseño: cierre verificable del despliegue two-node

**Fecha:** 2026-06-24  
**Estado:** capas 1–4 completadas; validado E2E

## Propósito

Cerrar las brechas entre el código de despliegue, sus pruebas, los documentos
operativos y los artefactos Superpowers. El estado publicado debe distinguir lo
que está implementado y verificado de lo que sólo ha pasado validación estática.

## Alcance y capas

1. **Evidencia técnica del deploy.** No modifica código ni documentación. Comprueba
   Compose, disponibilidad CUDA, build de las imágenes y una corrida local aislada.
2. **Estado operativo.** Actualiza `docs/implementation-status.md` con el conteo de
   pruebas y las capacidades que la capa 1 haya demostrado. Si el build o E2E no
   puede completarse por una dependencia externa, se registra como pendiente con
   la causa exacta.
3. **Trazabilidad Superpowers.** Marca como completados sólo los pasos de los planes
   cuya evidencia exista; conserva sin marcar los pasos no ejecutados. Alinea el
   plan two-host con el diseño y Dockerfile: el asset se materializa mediante
   `MobileCLIPTS`, no mediante una llamada distinta de `YOLOE.get_text_pe`.
4. **Cierre.** Ejecuta el conjunto final de pruebas y lint, revisa el diff y deja
   listo el único commit final requerido por el plan de infraestructura.

## Diseño de la capa 1

La evidencia se recoge en orden ascendente y sin borrar imágenes, contenedores,
volúmenes ni artefactos previos:

1. Validar los tres manifiestos con `docker compose ... config` y los contratos
   estáticos con la suite Python.
2. Verificar que Docker puede exponer la GPU con la imagen CUDA declarada.
3. Construir Node B y Node A desde los manifiestos actuales. El build de Node B debe
   demostrar que CLIP se instala desde un SHA completo y que
   `/app/mobileclip2_b.ts` existe antes del arranque.
4. Sólo si los prerrequisitos anteriores pasan y no existe un stack con el mismo
   proyecto en ejecución, levantar el compose local bajo un nombre de proyecto
   exclusivo. Se inspeccionan logs y los artefactos de la corrida; no se ejecuta
   `down -v` ni se elimina contenido del repositorio.

Una limitación de GPU, red, modelo o dataset no se disimula ni se corrige en esta
capa: se conserva la salida de la herramienta y las capas posteriores la reflejan
con precisión.

## Criterios de resultado

- **Validado E2E:** build de ambos nodos, GPU visible en Node B, comunicación A→B y
  artefactos de salida con `units_failed: 0`.
- **Validado estático:** Compose, pruebas y lint pasan, pero falta alguna condición
  externa para construir o ejecutar contenedores.
- **Bloqueado externamente:** Docker, GPU, red, modelos o dataset impiden continuar;
  se documenta el comando y el motivo comprobable.

## Decisiones de consistencia

- `docs/implementation-status.md` es la fuente operativa y debe usar el conteo real
  de la suite ejecutada, no un número histórico.
- Una casilla Superpowers es un registro de evidencia, no una previsión: no se marca
  por la mera presencia de archivos.
- La provisión de MobileCLIP se especifica por el mecanismo real, `MobileCLIPTS`,
  que coincide con el Dockerfile y elimina la descarga de ese asset en runtime.
