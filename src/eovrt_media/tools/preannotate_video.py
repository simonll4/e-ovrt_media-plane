"""Pre-anotación de video para el video-gt-lab (GT del clip bench, spec 43).

GDINO-base (más fuerte que el tiny evaluado — anti-circularidad) + ByteTrack
sobre las cajas de persona + inicialización de has_helmet/has_vest por
asociación espacial. Emite CVAT for video 1.1 listo para corrección humana.

Uso: python -m eovrt_media.tools.preannotate_video clip.mp4 --out clip.xml \
         [--sample-fps 10] [--device cuda] [--preview]
"""
from __future__ import annotations

import argparse
import warnings
from collections import Counter
from pathlib import Path

from rich.console import Console

from eovrt_media.tools.videogt import (
    assign_ppe_to_persons,
    build_cvat_xml,
    nms,
    smooth_bool,
    thin_track,
)

console = Console()

MODEL_ID = "IDEA-Research/grounding-dino-base"
PROMPT = "person. helmet. safety vest."


def track_persons(
    frame_dets: list[dict], frame_rate: float, person_threshold: float = 0.15
) -> list[dict]:
    """ByteTrack sobre cajas de persona; atributos por asociación espacial 1:1 por frame.

    ``person_threshold`` es el umbral REAL de nacimiento de un track (recall de
    persona). ``sv.ByteTrack.__init__`` (supervision 0.29.1,
    ``tracker/byte_tracker/core.py``) fija internamente
    ``det_thresh = track_activation_threshold + 0.1`` — ese ``det_thresh``, no
    ``track_activation_threshold``, es el que se chequea en el paso "Init new
    stracks" de ``update_with_tensors`` (``if track.score < self.det_thresh:
    continue``) para decidir si una detección sin match funda un track nuevo.
    Con los defaults de supervision (``track_activation_threshold=0.25``) el
    nacimiento efectivo queda en 0.35 sin importar qué umbral de persona use el
    llamador. Para que ``person_threshold`` sea el umbral de nacimiento real,
    restamos ese offset fijo de +0.1 al pasar ``track_activation_threshold``
    (clamped a 0.0). Mapeo: ``person_threshold`` → kwarg
    ``track_activation_threshold=max(0.0, person_threshold - 0.1)``; también se
    fija ``minimum_consecutive_frames=1`` para que el track quede confirmado
    desde el primer frame que supera el umbral (recall, no hay margen para
    esperar confirmación).
    """
    import numpy as np
    import supervision as sv

    with warnings.catch_warnings():
        # sv.ByteTrack está deprecado desde supervision 0.28 (a favor del paquete
        # `trackers`, no instalado) pero sigue funcional hasta 0.30; silenciamos
        # el FutureWarning de instanciación en vez de sumar una dependencia nueva.
        warnings.simplefilter("ignore", FutureWarning)
        activation_threshold = max(0.0, person_threshold - 0.1)
        tracker = sv.ByteTrack(
            frame_rate=frame_rate,
            track_activation_threshold=activation_threshold,
            minimum_consecutive_frames=1,
        )
    tracks: dict[int, list[dict]] = {}
    for fd in frame_dets:
        persons = fd["persons"]
        # Asignación 1:1 EPP→persona a nivel frame (I4): se calcula ANTES del
        # tracking, sobre el orden original de `persons`, y se transporta a
        # través de sv.Detections en el campo `class_id` (libre — ByteTrack no
        # lo lee) porque el filtrado/reordenamiento interno de ByteTrack
        # preserva la alineación entre xyxy/confidence/class_id.
        attrs_by_person = assign_ppe_to_persons(
            [box for box, _ in persons], fd["helmets"], fd["vests"]
        )
        detections = sv.Detections(
            xyxy=np.array([b for b, _ in persons], dtype=float).reshape(-1, 4),
            confidence=np.array([s for _, s in persons], dtype=float),
            class_id=np.arange(len(persons), dtype=int),
        )
        detections = tracker.update_with_detections(detections)
        for box, tid, person_idx in zip(
            detections.xyxy, detections.tracker_id, detections.class_id
        ):
            box = tuple(float(v) for v in box)
            tracks.setdefault(int(tid), []).append({
                "frame": fd["frame"],
                "box": box,
                "attributes": attrs_by_person[int(person_idx)],
            })
    return [{"track_id": tid, "boxes": boxes} for tid, boxes in sorted(tracks.items())]


def smooth_tracks(tracks: list[dict], window: int = 11) -> list[dict]:
    """Suaviza los atributos de cada track (voto por mayoría, ventana centrada)."""
    out = []
    for track in tracks:
        boxes = [dict(b) for b in track["boxes"]]
        for attr in ("has_helmet", "has_vest"):
            smoothed = smooth_bool([b["attributes"][attr] for b in boxes], window)
            for b, value in zip(boxes, smoothed):
                b["attributes"] = {**b["attributes"], attr: value}
        out.append({"track_id": track["track_id"], "boxes": boxes})
    return out


def _bind_label(label: str) -> str | None:
    """Clasifica el *texto* de un span de GDINO en 'person'/'helmet'/'vest'/None.

    Solo mira el texto (nunca el score) — es el análogo en miniatura de
    ``grounding_dino_adapter._bind_span`` pero contra las 3 clases fijas del prompt
    de este CLI en vez de un ``PromptPlan`` arbitrario con fuzzy matching. Devuelve
    ``None`` cuando el span no contiene ninguna de las substrings conocidas: ese
    caso es un binding fallido y el llamador (``_make_detector.detect``) debe
    contarlo y reportarlo, nunca descartarlo en silencio (ver nota en el adaptador
    de producción, que además loguea con ``logger.warning`` cada span no resuelto).

    **``safety`` cuenta como chaleco.** GDINO trocea el prompt y devuelve spans
    parciales: de ``"safety vest"`` emite a veces solo ``"safety"`` (medido: 105
    spans en el clip de obra real). Descartarlos pierde el chaleco y consolida un
    ``has_vest=False`` falso — es decir, **fabrica una infracción CR-02**, la
    dirección de error que este pipeline no puede permitirse. No hay ambigüedad:
    ``safety`` solo aparece en el prompt como parte de ``safety vest``.
    """
    label = label.strip().lower()
    if "person" in label:
        return "person"
    if "helmet" in label:
        return "helmet"
    if "vest" in label or "safety" in label:
        return "vest"
    return None


def _make_detector(
    device: str, person_threshold: float, ppe_threshold: float, nms_iou: float = 0.5
):
    """Detector GDINO-base → {'persons': [(Box, score)], 'helmets': [...], 'vests': [...]}.

    Invocación de processor/model/post_process alineada con el adaptador existente
    (``models/grounding_dino_adapter.py``): misma API de transformers instalada
    (``AutoProcessor`` + ``AutoModelForZeroShotObjectDetection`` +
    ``post_process_grounded_object_detection``), mismo criterio para leer
    ``text_labels`` sin disparar el FutureWarning de la clave ``labels``
    deprecada. Se simplifica el binding de labels contra el prompt (sin
    ``PromptPlan``/``by_text``) porque el prompt es fijo y las 3 clases son
    prefijos inequívocos de los spans devueltos por GDINO — ver ``_bind_label``.

    **``text_threshold`` va atado al umbral de clase más bajo, no fijo.** GDINO
    arma el label de cada caja con los tokens cuyo score supera ``text_threshold``;
    si ninguno lo supera, la caja sale con label **vacío** y el binding la descarta.
    Con un ``text_threshold`` fijo (0.25) y ``person_threshold=0.15``, TODA persona
    que puntúe entre 0.15 y 0.25 salía sin label y se perdía — es decir, la política
    de recall quedaba anulada justo para los operarios lejanos que motivan el umbral
    bajo (medido: 20 → 16 personas por frame en el clip de obra real). Atarlo a
    ``min(person, ppe)`` hace que el umbral de recall sea real. No relaja el EPP:
    una caja de casco/chaleco débil recibe label pero después la filtra
    ``score >= ppe_threshold``.

    Devuelve ``(detect, unmatched_spans)``: ``detect`` es la función de inferencia
    por frame y ``unmatched_spans`` es un ``collections.Counter`` (texto de span →
    cantidad de veces que apareció sin matchear ninguna clase) que el llamador
    (``main``) lee al terminar la corrida para advertir sobre binding perdido —
    ver IMPORTANT 1 del review de la Task 10.
    """
    import torch
    from transformers import AutoModelForZeroShotObjectDetection, AutoProcessor

    processor = AutoProcessor.from_pretrained(MODEL_ID)
    model = AutoModelForZeroShotObjectDetection.from_pretrained(MODEL_ID).to(device)
    model.eval()

    unmatched_spans: Counter[str] = Counter()
    score_threshold = min(person_threshold, ppe_threshold)

    def detect(image_pil):
        inputs = processor(images=image_pil, text=PROMPT, return_tensors="pt").to(device)
        with torch.no_grad():
            outputs = model(**inputs)
        with warnings.catch_warnings():
            # Ver nota en grounding_dino_adapter.py: 'labels' está deprecada a
            # favor de 'text_labels'; el filtro es por categoría porque el
            # FutureWarning no se atribuye de forma consistente al módulo.
            warnings.simplefilter("ignore", FutureWarning)
            (result,) = processor.post_process_grounded_object_detection(
                outputs, inputs.input_ids,
                threshold=score_threshold,
                text_threshold=score_threshold,
                # target_sizes espera (height, width) por imagen; image_pil.size
                # es (width, height) → se invierte.
                target_sizes=[image_pil.size[::-1]],
            )
        raw_labels = result["text_labels"] if "text_labels" in result else result.get("labels", [])
        if hasattr(raw_labels, "tolist"):
            raw_labels = raw_labels.tolist()

        persons, helmets, vests = [], [], []
        for box, score, label in zip(result["boxes"], result["scores"], raw_labels):
            box = tuple(float(v) for v in box.tolist())
            score = float(score)
            label = str(label)
            category = _bind_label(label)
            if category is None:
                unmatched_spans[label.strip().lower()] += 1
                continue
            if category == "person" and score >= person_threshold:
                persons.append((box, score))
            elif category == "helmet" and score >= ppe_threshold:
                helmets.append((box, score))
            elif category == "vest" and score >= ppe_threshold:
                vests.append((box, score))
        # NMS por clase: GDINO no lo aplica y emite duplicados de la misma caja.
        # El EPP se devuelve sin score (la asociación 1:1 no lo usa).
        return {
            "persons": nms(persons, nms_iou),
            "helmets": [box for box, _ in nms(helmets, nms_iou)],
            "vests": [box for box, _ in nms(vests, nms_iou)],
        }

    return detect, unmatched_spans


def _write_preview(video_path: Path, tracks: list[dict], out_path: Path) -> None:
    """MP4 con overlay (caja + id + estado EPP) para inspección pre-CVAT.

    ``tracks[i]["boxes"]`` solo trae entradas en los frames muestreados
    (múltiplos de ``step``); antes se dibujaba únicamente en esos frames y la
    caja "parpadeaba" en los 2 de cada 3 frames intermedios (a sample_fps).
    Para sostener la última anotación conocida entre muestras, se mantiene un
    puntero por track que avanza monótonamente con ``frame_idx`` (las boxes de
    cada track ya están ordenadas por frame ascendente) y se reusa la última
    caja con ``frame <= frame_idx``.

    OpenCV en este entorno no puede codificar H.264 (su build de FFMPEG solo
    trae ``h264_v4l2m2m``, que necesita un device que WSL no expone), así que
    escribe ``mp4v`` (MPEG-4 Part 2) — que los reproductores embebidos en
    editores/navegadores (Chromium) NO reproducen. Por eso se transcodifica a
    H.264 con ffmpeg al final; si ffmpeg no está, se conserva el ``mp4v`` y se
    avisa, en vez de fallar (el preview es un artefacto de inspección, no del GT).
    """
    import cv2

    cap = cv2.VideoCapture(str(video_path))
    fps = cap.get(cv2.CAP_PROP_FPS)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    raw_path = out_path.with_suffix(".mp4v.mp4")
    writer = cv2.VideoWriter(str(raw_path), cv2.VideoWriter_fourcc(*"mp4v"),
                             fps, (width, height))
    pointers = {track["track_id"]: 0 for track in tracks}
    frame_idx = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        for track in tracks:
            boxes = track["boxes"]
            if not boxes:
                continue
            tid = track["track_id"]
            idx = pointers[tid]
            while idx + 1 < len(boxes) and boxes[idx + 1]["frame"] <= frame_idx:
                idx += 1
            pointers[tid] = idx
            b = boxes[idx]
            if b["frame"] > frame_idx:
                continue  # el track todavía no empezó en este frame
            x1, y1, x2, y2 = (int(v) for v in b["box"])
            ok_ppe = b["attributes"]["has_helmet"] and b["attributes"]["has_vest"]
            color = (0, 200, 0) if ok_ppe else (0, 0, 255)
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
            text = (f"#{tid} casco:{'si' if b['attributes']['has_helmet'] else 'NO'} "
                    f"chaleco:{'si' if b['attributes']['has_vest'] else 'NO'}")
            cv2.putText(frame, text, (x1, max(15, y1 - 6)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)
        writer.write(frame)
        frame_idx += 1
    cap.release()
    writer.release()
    _transcode_to_h264(raw_path, out_path)


def _transcode_to_h264(raw_path: Path, out_path: Path) -> None:
    """Transcodifica el preview mp4v a H.264 con ffmpeg; conserva mp4v si falla.

    Deja el resultado en ``out_path`` (H.264, reproducible en editores/navegadores)
    y borra el intermedio. Si ffmpeg no está disponible o falla, mueve el mp4v a
    ``out_path`` y avisa — nunca aborta la corrida por un problema del preview.
    """
    import shutil
    import subprocess

    if shutil.which("ffmpeg") is None:
        raw_path.replace(out_path)
        console.print("[yellow]aviso:[/yellow] ffmpeg no encontrado — el preview "
                      f"queda en mp4v ({out_path.name}); algunos reproductores "
                      "(VS Code) no lo abren.")
        return
    result = subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(raw_path),
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "23", "-preset", "fast",
         str(out_path)],
        capture_output=True, text=True,
    )
    if result.returncode == 0:
        raw_path.unlink(missing_ok=True)
    else:
        raw_path.replace(out_path)
        console.print(f"[yellow]aviso:[/yellow] ffmpeg falló al transcodificar el "
                      f"preview ({result.stderr.strip()[:200]}); queda en mp4v.")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video", type=Path, help="clip CFR preparado (etapa 0)")
    parser.add_argument("--out", type=Path, required=True, help="XML de salida")
    parser.add_argument("--sample-fps", type=float, default=10.0)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--person-threshold", type=float, default=0.15)
    parser.add_argument("--ppe-threshold", type=float, default=0.35)
    parser.add_argument("--smooth-window", type=int, default=11)
    parser.add_argument("--thin-eps-px", type=float, default=10.0)
    parser.add_argument("--nms-iou", type=float, default=0.5,
                        help="IoU de NMS por clase; suprime cajas duplicadas del mismo objeto")
    parser.add_argument("--preview", action="store_true")
    args = parser.parse_args(argv)

    import cv2
    from PIL import Image

    cap = cv2.VideoCapture(str(args.video))
    if not cap.isOpened():
        console.print(f"[bold red]Error:[/bold red] no se pudo abrir el video "
                      f"'{args.video}' (no existe, no es legible, o el codec no está "
                      f"soportado).")
        raise SystemExit(1)
    fps = cap.get(cv2.CAP_PROP_FPS)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    n_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    step = max(1, round(fps / args.sample_fps))
    console.print(f"[cyan]{args.video.name}[/cyan]: {width}x{height} @ {fps:.0f} fps, "
                  f"{n_frames} frames — muestreo cada {step} frames")

    detect, unmatched_spans = _make_detector(
        args.device, args.person_threshold, args.ppe_threshold, args.nms_iou
    )
    frame_dets = []
    frame_idx = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if frame_idx % step == 0:
            image = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
            frame_dets.append({"frame": frame_idx, **detect(image)})
        frame_idx += 1
    cap.release()

    tracks = track_persons(
        frame_dets, frame_rate=args.sample_fps, person_threshold=args.person_threshold
    )
    tracks = smooth_tracks(tracks, window=args.smooth_window)
    if args.preview:
        preview_path = args.out.with_suffix(".preview.mp4")
        _write_preview(args.video, tracks, preview_path)
        console.print(f"[dim]preview:[/dim] {preview_path}")
    thinned = [{"track_id": t["track_id"], "boxes": thin_track(t["boxes"], args.thin_eps_px)}
               for t in tracks]

    xml = build_cvat_xml(thinned, stop_frame=n_frames - 1, width=width,
                         height=height, task_name=args.video.stem)
    args.out.write_text(xml)
    total_kf = sum(len(t["boxes"]) for t in thinned)
    console.print(f"[green]✓[/green] {args.out} — {len(thinned)} track(s), "
                  f"{total_kf} keyframes")

    if unmatched_spans:
        total_unmatched = sum(unmatched_spans.values())
        top = ", ".join(f"'{text}' x{n}" for text, n in unmatched_spans.most_common(5))
        console.print(
            f"[bold yellow]ADVERTENCIA:[/bold yellow] se descartaron {total_unmatched} "
            f"span(s) de GDINO que no matchearon ninguna clase (person/helmet/vest). "
            f"Textos más frecuentes: {top}"
        )
        console.print(
            "[bold red]Si entre esos spans hay términos de casco/chaleco, el voto por "
            "mayoría puede haber consolidado has_helmet/has_vest=False de forma "
            "incorrecta (falla del detector, no ausencia real de EPP). NO usar este XML "
            "como pre-anotación sin revisar el binding de labels primero.[/bold red]"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
