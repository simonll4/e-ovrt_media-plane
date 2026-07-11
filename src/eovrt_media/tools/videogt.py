"""Lógica pura del video-gt-lab: asociación EPP→persona, suavizado temporal,
adelgazamiento de keyframes y escritura de CVAT for video 1.1.

Sin dependencias de torch/transformers — testeable sin GPU. La orquestación
con modelo y tracker vive en ``preannotate_video``.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from collections.abc import Callable
from xml.dom import minidom

Box = tuple[float, float, float, float]


def head_region(person: Box) -> Box:
    """Tercio superior de la caja de persona (zona esperable del casco)."""
    x1, y1, x2, y2 = person
    return (x1, y1, x2, y1 + (y2 - y1) / 3)


def torso_region(person: Box) -> Box:
    """Banda 20%–70% de la altura (zona esperable del chaleco)."""
    x1, y1, x2, y2 = person
    h = y2 - y1
    return (x1, y1 + 0.2 * h, x2, y1 + 0.7 * h)


def center_in(box: Box, region: Box) -> bool:
    """True si el centro de ``box`` cae dentro de ``region``."""
    cx = (box[0] + box[2]) / 2
    cy = (box[1] + box[3]) / 2
    return region[0] <= cx <= region[2] and region[1] <= cy <= region[3]


def infer_attributes(person: Box, helmets: list[Box], vests: list[Box]) -> dict:
    """Inicializa has_helmet/has_vest por contención de centro en la región.

    Mismo criterio center-containment que ``bench.geometry`` del repo datasets:
    las cajas de EPP y las regiones tienen áreas muy distintas, IoU no sirve.

    NOTA: esta función asocia EPP→persona de forma independiente por persona
    (``any()``). En escenas con varias personas de cajas solapadas, un único
    casco puede contener su centro dentro del tercio superior de más de una
    caja y marcar has_helmet=True a todas — esconde una violación real de EPP.
    Se mantiene sin cambios (Task 8, ya aprobada/testeada) para no romper su
    contrato; el camino multi-persona usa ``assign_ppe_to_persons`` en su
    lugar (ver ``track_persons`` en ``preannotate_video.py``).
    """
    head = head_region(person)
    torso = torso_region(person)
    return {
        "has_helmet": any(center_in(h, head) for h in helmets),
        "has_vest": any(center_in(v, torso) for v in vests),
    }


def _closest_person_index(
    item: Box, persons: list[Box], region_of: Callable[[Box], Box]
) -> int | None:
    """Índice de la persona cuya región (cabeza o torso) mejor explica ``item``.

    Candidatas: aquellas cuya región contiene el centro de ``item`` (mismo
    criterio center-containment que ``infer_attributes``). Entre candidatas,
    desempata por menor distancia centro-a-centro (item vs. región). Si
    ninguna persona contiene el centro, devuelve ``None`` (EPP sin asignar).
    """
    item_cx = (item[0] + item[2]) / 2
    item_cy = (item[1] + item[3]) / 2
    best_idx: int | None = None
    best_dist = float("inf")
    for i, person in enumerate(persons):
        region = region_of(person)
        if not center_in(item, region):
            continue
        region_cx = (region[0] + region[2]) / 2
        region_cy = (region[1] + region[3]) / 2
        dist = (item_cx - region_cx) ** 2 + (item_cy - region_cy) ** 2
        if dist < best_dist:
            best_dist = dist
            best_idx = i
    return best_idx


def assign_ppe_to_persons(persons: list[Box], helmets: list[Box], vests: list[Box]) -> list[dict]:
    """Asignación EPP→persona 1:1 a nivel frame: cada EPP marca a lo sumo UNA persona.

    Por qué 1:1 y no ``any()`` por-persona (I4 del review): con cajas de persona
    solapadas (escenario P7, multitud), un solo casco puede caer dentro de la
    región-cabeza de varias personas a la vez; ``any()`` marcaría has_helmet=True
    en todas, escondiendo la violación real de la persona sin casco. Además ese
    error correlacionaría con el sistema evaluado, que hace matching 1:1 EPP↔persona
    — sesgando la comparación a favor del SUT. Acá cada casco/chaleco se asigna, a
    lo sumo, a la persona de mejor contención (desempate por distancia); una
    persona cuyo casco fue "robado" por otra más cercana queda has_helmet=False,
    preservando la violación en el GT.
    """
    has_helmet = [False] * len(persons)
    has_vest = [False] * len(persons)
    for helmet in helmets:
        idx = _closest_person_index(helmet, persons, head_region)
        if idx is not None:
            has_helmet[idx] = True
    for vest in vests:
        idx = _closest_person_index(vest, persons, torso_region)
        if idx is not None:
            has_vest[idx] = True
    return [{"has_helmet": h, "has_vest": v} for h, v in zip(has_helmet, has_vest)]


def nms(boxes: list, iou_threshold: float = 0.5) -> list:
    """NMS greedy sobre cajas ``(Box, score)`` de UNA clase → sobrevivientes.

    GDINO no aplica NMS (solo umbraliza), así que emite varias cajas solapadas
    para el mismo objeto. Con el umbral de persona bajo (0.15, orientado a
    recall) eso se dispara: el clip de obra real daba ~6 cajas por operario, es
    decir 58 tracks para ~10 personas. No es recall — son duplicados de la
    MISMA persona — y le cargan al anotador un trabajo de borrado enorme,
    además de inflar ``subjects_in_evidence`` en los episodios de escena.

    Suprimir solapamientos altos NO sacrifica recall de personas distintas: dos
    operarios separados no alcanzan IoU 0.5 salvo oclusión casi total, y en ese
    caso el anotador los separa (split) en CVAT.
    """
    survivors: list = []
    for box, score in sorted(boxes, key=lambda item: item[1], reverse=True):
        if all(_iou(box, kept) <= iou_threshold for kept, _ in survivors):
            survivors.append((box, score))
    return survivors


def _iou(a: Box, b: Box) -> float:
    """Intersection over Union de dos cajas xyxy."""
    ix1, iy1 = max(a[0], b[0]), max(a[1], b[1])
    ix2, iy2 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    if inter == 0.0:
        return 0.0
    area_a = max(0.0, a[2] - a[0]) * max(0.0, a[3] - a[1])
    area_b = max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


def smooth_bool(values: list, window: int = 11) -> list:
    """Voto por mayoría en ventana centrada; None no vota y pasa intacto.

    Mata el parpadeo del detector para que el corrector humano vea
    transiciones reales, no ruido (spec video-gt-lab §3.1).
    """
    half = window // 2
    out = []
    for i, value in enumerate(values):
        if value is None:
            out.append(None)
            continue
        votes = [v for v in values[max(0, i - half):i + half + 1] if v is not None]
        out.append(sum(votes) * 2 >= len(votes))
    return out


def mark_evidence_gaps(boxes: list[dict], max_gap_frames: int) -> list[dict]:
    """Marca con ``outside=True`` los huecos de EVIDENCIA (no de adelgazamiento).

    Invariante central del proyecto: la incertidumbre nunca fabrica una
    infracción. Si el detector pierde a la persona entre dos frames
    muestreados, ese tramo no tiene evidencia — no es lo mismo que una persona
    quieta cuyo estado de EPP no cambió. Sin marcar, dos consumidores aguas
    abajo prolongan el último estado conocido sobre el hueco: CVAT interpola
    linealmente la caja, y el parser del repo hermano (``attribute_states``,
    semántica de escalón) sostiene el último atributo hasta el próximo
    keyframe. El resultado es una infracción (o su ausencia) afirmada sobre un
    tramo donde nadie vio nada.

    Debe aplicarse sobre las boxes SIN adelgazar (todas las detecciones frame
    a frame de ``track_persons``, antes de ``thin_track``): ahí está toda la
    evidencia disponible. Si se aplicara después del adelgazado, un hueco por
    adelgazamiento legítimo (persona quieta, keyframes redundantes borrados)
    se confundiría con un hueco por falta de detección.

    Por cada par consecutivo cuyo salto de frame supera ``max_gap_frames``,
    inserta justo después de la primera un marcador
    ``{"frame": prev["frame"] + 1, "box": prev["box"],
    "attributes": prev["attributes"], "outside": True}``. Las boxes originales
    no se modifican (no llevan la clave ``outside``, tratada como falsy por
    los consumidores vía ``.get``).
    """
    if not boxes:
        return []
    result = [boxes[0]]
    for prev, nxt in zip(boxes, boxes[1:]):
        if nxt["frame"] - prev["frame"] > max_gap_frames:
            result.append({
                "frame": prev["frame"] + 1,
                "box": prev["box"],
                "attributes": prev["attributes"],
                "outside": True,
            })
        result.append(nxt)
    return result


def thin_track(boxes: list[dict], eps_px: float = 10.0) -> list[dict]:
    """Adelgaza keyframes: conserva primero, último, cambios de atributo y
    desviaciones geométricas > eps respecto del último conservado.

    CVAT interpola linealmente entre keyframes; eps acota el error de la caja
    interpolada. Un track detectado a 10 fps queda en decenas de keyframes.

    Los marcadores ``outside=True`` de ``mark_evidence_gaps`` (huecos de
    evidencia) y el keyframe que reinicia el track inmediatamente después de
    uno se conservan SIEMPRE, sin pasar por el criterio de movimiento/cambio
    de atributo: son marcadores de contrato (cierran/abren un tramo sin
    evidencia), no keyframes de forma, y adelgazarlos rompería la garantía de
    ``mark_evidence_gaps``.
    """
    if not boxes:
        return []
    kept = [boxes[0]]
    force_next = False
    for box in boxes[1:-1]:
        last = kept[-1]
        if box.get("outside"):
            kept.append(box)
            force_next = True
            continue
        if force_next:
            kept.append(box)
            force_next = False
            continue
        moved = max(abs(a - b) for a, b in zip(box["box"], last["box"])) > eps_px
        if moved or box["attributes"] != last["attributes"]:
            kept.append(box)
    if len(boxes) > 1:
        kept.append(boxes[-1])
    return kept


def build_cvat_xml(tracks: list[dict], stop_frame: int, width: int, height: int,
                   task_name: str) -> str:
    """Serializa tracks de persona al formato 'CVAT for video 1.1'.

    Convención CVAT: un track que termina antes del final del video se cierra
    con un box outside="1" en el frame siguiente al último visible. Tracks sin
    boxes se saltean (no hay nada que anotar). Atributos con valor None
    (no evaluable) se omiten del XML en vez de serializarse como "false"
    (ver ``_emit``): la ausencia nunca debe fabricar una violación de EPP.
    Boxes marcadas con ``outside=True`` (huecos de evidencia, ver
    ``mark_evidence_gaps``) se emiten también con outside="1", además del
    cierre final que esta función fabrica cuando el track termina antes de
    ``stop_frame``.
    """
    root = ET.Element("annotations")
    ET.SubElement(root, "version").text = "1.1"
    task = ET.SubElement(ET.SubElement(root, "meta"), "task")
    ET.SubElement(task, "name").text = task_name
    ET.SubElement(task, "size").text = str(stop_frame + 1)
    original = ET.SubElement(task, "original_size")
    ET.SubElement(original, "width").text = str(width)
    ET.SubElement(original, "height").text = str(height)

    def _emit(parent, frame, box, attributes, outside):
        el = ET.SubElement(parent, "box", {
            "frame": str(frame), "keyframe": "1",
            "outside": "1" if outside else "0", "occluded": "0",
            "xtl": f"{box[0]:.2f}", "ytl": f"{box[1]:.2f}",
            "xbr": f"{box[2]:.2f}", "ybr": f"{box[3]:.2f}",
        })
        for name, value in attributes.items():
            # None = no evaluable/incierto: omitir el atributo en vez de escribir
            # "false", para no fabricar una violación de EPP a partir de un dato incierto.
            if value is None:
                continue
            attr = ET.SubElement(el, "attribute", {"name": name})
            attr.text = "true" if value else "false"

    for track in tracks:
        if not track["boxes"]:
            continue
        el = ET.SubElement(root, "track", {
            "id": str(track["track_id"]), "label": "person", "source": "semi-auto",
        })
        for b in track["boxes"]:
            _emit(el, b["frame"], b["box"], b["attributes"], outside=bool(b.get("outside")))
        last = track["boxes"][-1]
        if last["frame"] < stop_frame:
            _emit(el, last["frame"] + 1, last["box"], last["attributes"], outside=True)

    return minidom.parseString(ET.tostring(root)).toprettyxml(indent="  ")
