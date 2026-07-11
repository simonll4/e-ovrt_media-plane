"""Lógica pura del video-gt-lab (sin GPU, sin modelos)."""
import xml.etree.ElementTree as ET
from collections import Counter

from eovrt_media.tools.preannotate_video import _bind_label, smooth_tracks, track_persons
from eovrt_media.tools.videogt import (
    nms,
    assign_ppe_to_persons,
    build_cvat_xml,
    head_region,
    infer_attributes,
    mark_evidence_gaps,
    smooth_bool,
    thin_track,
    torso_region,
)


def test_regiones_geometricas():
    person = (100.0, 0.0, 200.0, 300.0)
    assert head_region(person) == (100.0, 0.0, 200.0, 100.0)
    assert torso_region(person) == (100.0, 60.0, 200.0, 210.0)


def test_infer_attributes_asocia_por_centro():
    person = (100.0, 0.0, 200.0, 300.0)
    helmet_on_head = (130.0, 10.0, 170.0, 50.0)     # centro en tercio superior
    helmet_lejano = (400.0, 10.0, 440.0, 50.0)      # centro fuera de la persona
    vest_en_torso = (110.0, 80.0, 190.0, 180.0)
    assert infer_attributes(person, [helmet_on_head], []) == \
        {"has_helmet": True, "has_vest": False}
    assert infer_attributes(person, [helmet_lejano], [vest_en_torso]) == \
        {"has_helmet": False, "has_vest": True}


def test_assign_ppe_to_persons_no_duplica_casco_entre_dos_personas():
    # Dos personas con cajas solapadas (escenario P7 del banco) y UN solo casco,
    # puesto sobre la cabeza de A. any() por-persona (infer_attributes) marcaría
    # has_helmet=True en ambas porque el centro del casco cae en el tercio
    # superior de las dos cajas superpuestas; assign_ppe_to_persons debe asignar
    # el casco a lo sumo a una persona (la de mejor contención/distancia) para no
    # esconder la violación real de B.
    person_a = (100.0, 0.0, 200.0, 300.0)
    person_b = (110.0, 0.0, 210.0, 300.0)  # solapada con A
    helmet_sobre_a = (120.0, 10.0, 160.0, 50.0)  # centro (140, 30): más cerca de A
    attrs = assign_ppe_to_persons([person_a, person_b], [helmet_sobre_a], [])
    assert attrs[0] == {"has_helmet": True, "has_vest": False}
    assert attrs[1] == {"has_helmet": False, "has_vest": False}


def test_assign_ppe_to_persons_caso_simple_una_persona():
    person = (100.0, 0.0, 200.0, 300.0)
    helmet = (130.0, 10.0, 170.0, 50.0)
    vest = (110.0, 80.0, 190.0, 180.0)
    attrs = assign_ppe_to_persons([person], [helmet], [vest])
    assert attrs == [{"has_helmet": True, "has_vest": True}]


def test_assign_ppe_to_persons_epp_sin_persona_que_lo_contenga_no_asigna():
    person = (100.0, 0.0, 200.0, 300.0)
    helmet_lejano = (400.0, 10.0, 440.0, 50.0)
    attrs = assign_ppe_to_persons([person], [helmet_lejano], [])
    assert attrs == [{"has_helmet": False, "has_vest": False}]


def test_smooth_bool_mata_parpadeo():
    values = [True, True, False, True, True]  # False aislado = parpadeo
    assert smooth_bool(values, window=3) == [True, True, True, True, True]
    con_none = [True, None, True, False, False, False]
    smoothed = smooth_bool(con_none, window=3)
    assert smoothed[1] is None            # None pasa intacto
    assert smoothed[4] is False           # tramo real de False sobrevive


def test_thin_track_conserva_lo_esencial():
    attrs_a = {"has_helmet": True, "has_vest": True}
    attrs_b = {"has_helmet": False, "has_vest": True}
    boxes = [
        {"frame": 0, "box": (0.0, 0.0, 10.0, 10.0), "attributes": attrs_a},
        {"frame": 3, "box": (1.0, 0.0, 11.0, 10.0), "attributes": attrs_a},   # ~igual → fuera
        {"frame": 6, "box": (2.0, 0.0, 12.0, 10.0), "attributes": attrs_b},   # cambia attr → queda
        {"frame": 9, "box": (50.0, 0.0, 60.0, 10.0), "attributes": attrs_b},  # salto geom → queda
        {"frame": 12, "box": (51.0, 0.0, 61.0, 10.0), "attributes": attrs_b}, # último → queda
    ]
    thinned = thin_track(boxes, eps_px=5.0)
    assert [b["frame"] for b in thinned] == [0, 6, 9, 12]


def test_thin_track_conserva_marcadores_outside_y_reinicio():
    # Un marcador outside=True (hueco de evidencia) y el keyframe que reinicia
    # el track tras el hueco deben sobrevivir al adelgazado SIEMPRE, aunque la
    # geometría/atributos no varíen lo suficiente para disparar el criterio
    # normal de thin_track — son marcadores de contrato, no keyframes de forma.
    attrs = {"has_helmet": True, "has_vest": False}
    boxes = [
        {"frame": 0, "box": (0.0, 0.0, 10.0, 10.0), "attributes": attrs},
        {"frame": 1, "box": (0.0, 0.0, 10.0, 10.0), "attributes": attrs, "outside": True},
        {"frame": 20, "box": (0.0, 0.0, 10.0, 10.0), "attributes": attrs},  # reinicio, sin cambios
        {"frame": 40, "box": (0.0, 0.0, 10.0, 10.0), "attributes": attrs},  # último
    ]
    thinned = thin_track(boxes, eps_px=5.0)
    assert [b["frame"] for b in thinned] == [0, 1, 20, 40]
    assert thinned[1]["outside"] is True


def test_mark_evidence_gaps_inserta_marcador_en_hueco_grande():
    # Hueco de 20 frames entre las boxes en frame=0 y frame=20, con umbral 10:
    # debe insertarse un marcador outside=True justo después de la última
    # evidencia (frame=1) para que el tramo sin detección no se lea como
    # "sigue siendo True" (semántica escalón del parser hermano).
    attrs = {"has_helmet": True, "has_vest": False}
    boxes = [
        {"frame": 0, "box": (0.0, 0.0, 10.0, 10.0), "attributes": attrs},
        {"frame": 20, "box": (50.0, 0.0, 60.0, 10.0), "attributes": attrs},
    ]
    marked = mark_evidence_gaps(boxes, max_gap_frames=10)
    assert [b["frame"] for b in marked] == [0, 1, 20]
    marker = marked[1]
    assert marker["outside"] is True
    assert marker["box"] == boxes[0]["box"]
    assert marker["attributes"] == attrs


def test_mark_evidence_gaps_no_inserta_en_parpadeo_chico():
    # Hueco de 3 frames con umbral 10: parpadeo normal del detector, no se marca.
    attrs = {"has_helmet": True, "has_vest": False}
    boxes = [
        {"frame": 0, "box": (0.0, 0.0, 10.0, 10.0), "attributes": attrs},
        {"frame": 3, "box": (1.0, 0.0, 11.0, 10.0), "attributes": attrs},
    ]
    marked = mark_evidence_gaps(boxes, max_gap_frames=10)
    assert marked == boxes
    assert all(not b.get("outside") for b in marked)


def _track():
    return {"track_id": 0, "boxes": [
        {"frame": 0, "box": (10.0, 20.0, 110.0, 220.0),
         "attributes": {"has_helmet": True, "has_vest": False}},
        {"frame": 30, "box": (15.0, 20.0, 115.0, 220.0),
         "attributes": {"has_helmet": False, "has_vest": False}},
    ]}


def test_build_cvat_xml_estructura():
    xml = build_cvat_xml([_track()], stop_frame=99, width=1280, height=720,
                         task_name="lab_recorte1")
    root = ET.fromstring(xml)
    assert root.find("./meta/task/size").text == "100"
    (track,) = root.findall("track")
    assert track.get("label") == "person"
    boxes = track.findall("box")
    assert boxes[0].get("frame") == "0" and boxes[0].get("keyframe") == "1"
    attrs = {a.get("name"): a.text for a in boxes[0].findall("attribute")}
    assert attrs == {"has_helmet": "true", "has_vest": "false"}
    # cierre outside en last_frame + 1 (termina antes de stop_frame)
    assert boxes[-1].get("frame") == "31" and boxes[-1].get("outside") == "1"


def test_build_cvat_xml_sin_cierre_si_llega_al_final():
    track = _track()
    track["boxes"][-1]["frame"] = 99
    xml = build_cvat_xml([track], stop_frame=99, width=1280, height=720, task_name="t")
    boxes = ET.fromstring(xml).find("track").findall("box")
    assert boxes[-1].get("frame") == "99" and boxes[-1].get("outside") == "0"


def test_build_cvat_xml_ignora_tracks_vacios():
    track_vacio = {"track_id": 1, "boxes": []}
    xml = build_cvat_xml([track_vacio, _track()], stop_frame=99, width=1280, height=720,
                         task_name="t")
    tracks = ET.fromstring(xml).findall("track")
    assert len(tracks) == 1
    assert tracks[0].get("id") == "0"


def test_build_cvat_xml_emite_outside_para_marcador_interno():
    # Marcador interno de hueco de evidencia (no el cierre final del track):
    # debe emitirse con outside="1" para que el parser hermano lo lea como
    # "no evaluable" en vez de interpolar/sostener el último atributo.
    track = {"track_id": 0, "boxes": [
        {"frame": 0, "box": (10.0, 20.0, 110.0, 220.0),
         "attributes": {"has_helmet": True, "has_vest": False}},
        {"frame": 1, "box": (10.0, 20.0, 110.0, 220.0),
         "attributes": {"has_helmet": True, "has_vest": False}, "outside": True},
        {"frame": 20, "box": (15.0, 20.0, 115.0, 220.0),
         "attributes": {"has_helmet": False, "has_vest": False}},
    ]}
    xml = build_cvat_xml([track], stop_frame=99, width=1280, height=720, task_name="t")
    boxes = ET.fromstring(xml).find("track").findall("box")
    by_frame = {b.get("frame"): b for b in boxes}
    assert by_frame["1"].get("outside") == "1"
    assert by_frame["0"].get("outside") == "0"
    assert by_frame["20"].get("outside") == "0"
    # sigue cerrando el track al final como antes (no se rompe el cierre existente)
    assert boxes[-1].get("frame") == "21" and boxes[-1].get("outside") == "1"


def test_build_cvat_xml_omite_atributo_none():
    track = {"track_id": 0, "boxes": [
        {"frame": 0, "box": (1.0, 2.0, 3.0, 4.0),
         "attributes": {"has_helmet": None, "has_vest": True}},
    ]}
    xml = build_cvat_xml([track], stop_frame=5, width=100, height=100, task_name="t")
    box = ET.fromstring(xml).find("track").find("box")
    attrs = {a.get("name"): a.text for a in box.findall("attribute")}
    assert "has_helmet" not in attrs
    assert attrs == {"has_vest": "true"}


def _synthetic_frames():
    """Persona que se mueve en x; casco presente salvo parpadeo en frame 9."""
    frames = []
    for i in range(30):
        x = 100.0 + i * 2
        person = ((x, 50.0, x + 60.0, 250.0), 0.9)
        helmet = [] if i == 9 else [(x + 15, 55.0, x + 45, 85.0)]
        frames.append({"frame": i * 3, "persons": [person],
                       "helmets": helmet, "vests": []})
    return frames


def test_track_persons_da_un_track_estable():
    tracks = track_persons(_synthetic_frames(), frame_rate=10.0)
    assert len(tracks) == 1
    (track,) = tracks
    # ByteTrack puede tardar 1-2 frames en confirmar el track; exigir >= 28
    assert len(track["boxes"]) >= 28
    assert track["boxes"][0]["attributes"]["has_vest"] is False


def _synthetic_frames_low_score(score: float, n: int = 10):
    """Persona estática detectada con ``score`` bajo en todos los frames muestreados."""
    frames = []
    for i in range(n):
        x = 100.0 + i * 2
        person = ((x, 50.0, x + 60.0, 250.0), score)
        frames.append({"frame": i, "persons": [person], "helmets": [], "vests": []})
    return frames


def test_track_persons_umbral_efectivo_person_threshold():
    # I1: sv.ByteTrack calcula internamente det_thresh = track_activation_threshold
    # + 0.1 (umbral real de NACIMIENTO de un track, ver core.py step "Init new
    # stracks"); antes --person-threshold no se cableaba a nada y el umbral
    # efectivo de nacimiento quedaba fijo en 0.35 (default track_activation_threshold
    # 0.25 + 0.1), sin importar --person-threshold. Una persona detectada a 0.20
    # nunca generaba track (falso negativo de persona).
    #
    # Con el fix, track_persons resta el offset fijo de +0.1 al pasar
    # track_activation_threshold, de forma que el umbral de nacimiento coincide
    # con person_threshold. Con person_threshold=0.15 (nuevo default, recall) una
    # persona a score=0.20 SÍ genera track; con person_threshold=0.35 (umbral viejo
    # efectivo) la misma persona NO genera track.
    frames = _synthetic_frames_low_score(score=0.20)

    tracks_bajo = track_persons(frames, frame_rate=10.0, person_threshold=0.15)
    assert len(tracks_bajo) == 1
    assert len(tracks_bajo[0]["boxes"]) >= 1

    tracks_alto = track_persons(frames, frame_rate=10.0, person_threshold=0.35)
    assert tracks_alto == []


def test_smooth_tracks_elimina_parpadeo_de_atributo():
    tracks = track_persons(_synthetic_frames(), frame_rate=10.0)
    smoothed = smooth_tracks(tracks, window=5)
    helmet_states = [b["attributes"]["has_helmet"] for b in smoothed[0]["boxes"]]
    assert all(helmet_states)  # el parpadeo del frame 9 desaparece


def test_smooth_tracks_no_cruza_huecos_de_evidencia():
    # Reproducción del hallazgo CRITICAL: raw [F,F,F,F,F | hueco | T,T,T,T,T,T].
    # Con smooth_bool centrando la ventana por ÍNDICE DE LISTA (sin conocer el
    # salto real de frames), la última muestra False pre-hueco quedaba adyacente
    # en la lista a las primeras True post-hueco y el voto las mezclaba. El
    # marcador outside=True debe cortar la ventana: ninguna muestra de un lado
    # del hueco puede votar sobre las del otro lado.
    attrs_false = {"has_helmet": True, "has_vest": False}
    attrs_true = {"has_helmet": True, "has_vest": True}
    pre_hueco = [
        {"frame": i * 3, "box": (0.0, 0.0, 10.0, 10.0), "attributes": dict(attrs_false)}
        for i in range(5)
    ]
    marker = {
        "frame": pre_hueco[-1]["frame"] + 1, "box": pre_hueco[-1]["box"],
        "attributes": dict(attrs_false), "outside": True,
    }
    post_hueco = [
        {"frame": 300 + i * 3, "box": (0.0, 0.0, 10.0, 10.0), "attributes": dict(attrs_true)}
        for i in range(6)
    ]
    track = {"track_id": 0, "boxes": pre_hueco + [marker] + post_hueco}
    # window=21 (> longitud de la lista, 12) fuerza que TODO el track entre en
    # una sola ventana bajo la implementación sin segmentar: 6 False (5 pre +
    # marcador) contra 6 True (post) empata, y el desempate de smooth_bool
    # (sum*2 >= len) resuelve a True en cada posición — contamina el pre-hueco
    # entero. Es el discriminante más nítido del bug con estos conteos.
    (smoothed,) = smooth_tracks([track], window=21)
    boxes = smoothed["boxes"]
    pre = boxes[:5]
    post = boxes[6:]
    assert all(b["attributes"]["has_vest"] is False for b in pre)
    assert all(b["attributes"]["has_vest"] is True for b in post)


def test_smooth_tracks_ventana_funciona_dentro_del_segmento():
    # El fix no debe desactivar el suavizado dentro de un mismo segmento de
    # evidencia contigua: un False aislado entre True sigue matando el parpadeo.
    attrs_true = {"has_helmet": True, "has_vest": True}
    attrs_false = {"has_helmet": True, "has_vest": False}
    boxes = [
        {"frame": i, "box": (0.0, 0.0, 10.0, 10.0),
         "attributes": dict(attrs_false) if i == 2 else dict(attrs_true)}
        for i in range(5)
    ]
    track = {"track_id": 0, "boxes": boxes}
    (smoothed,) = smooth_tracks([track], window=3)
    assert all(b["attributes"]["has_vest"] is True for b in smoothed["boxes"])


def _synthetic_frames_con_hueco():
    """Persona estática sin chaleco (frames 0-12), hueco de evidencia, luego con
    chaleco (frames 300-315) — reproduce el escenario del auditor a nivel de
    ``track_persons`` real (no un track fabricado a mano)."""
    frames = []
    for i in range(5):
        x = 100.0 + i * 2
        person = ((x, 50.0, x + 60.0, 250.0), 0.9)
        frames.append({"frame": i * 3, "persons": [person], "helmets": [], "vests": []})
    for i in range(6):
        x = 100.0 + i * 2
        person = ((x, 50.0, x + 60.0, 250.0), 0.9)
        vest = [(x + 10.0, 100.0, x + 50.0, 200.0)]
        frames.append({"frame": 300 + i * 3, "persons": [person], "helmets": [], "vests": vest})
    return frames


def test_pipeline_orden_mark_antes_de_smooth_no_cruza_hueco():
    # Integración del orden nuevo (track_persons -> mark_evidence_gaps ->
    # smooth_tracks -> thin_track), sin pasar por main() (requiere GDINO real).
    # Es el discriminante exacto que reportó el auditor: con el orden viejo
    # (smooth antes de mark) esto fallaba.
    frames = _synthetic_frames_con_hueco()
    tracks = track_persons(frames, frame_rate=10.0)
    assert len(tracks) == 1
    gapped = [
        {"track_id": t["track_id"], "boxes": mark_evidence_gaps(t["boxes"], max_gap_frames=10)}
        for t in tracks
    ]
    # window=21 (> longitud de la lista): mismo discriminante que
    # test_smooth_tracks_no_cruza_huecos_de_evidencia, ahora sobre boxes reales
    # de track_persons en vez de una lista armada a mano.
    smoothed = smooth_tracks(gapped, window=21)
    thinned = thin_track(smoothed[0]["boxes"], eps_px=10.0)
    pre_hueco = [b for b in thinned if not b.get("outside") and b["frame"] < 20]
    assert pre_hueco, "debe sobrevivir al menos una box pre-hueco al thin_track"
    assert all(b["attributes"]["has_vest"] is False for b in pre_hueco)


def test_track_persons_no_duplica_casco_en_multitud():
    # I4 a nivel de orquestación: dos personas con cajas solapadas y estáticas,
    # un solo casco puesto sobre la cabeza de A en todos los frames. Con any()
    # por-persona ambas quedarían has_helmet=True; con la asignación 1:1
    # (assign_ppe_to_persons) solo A debe quedar con casco.
    frames = []
    for i in range(10):
        person_a = ((100.0, 0.0, 200.0, 300.0), 0.9)
        person_b = ((110.0, 0.0, 210.0, 300.0), 0.9)  # solapada con A
        helmet_sobre_a = (120.0, 10.0, 160.0, 50.0)
        frames.append({
            "frame": i, "persons": [person_a, person_b],
            "helmets": [helmet_sobre_a], "vests": [],
        })
    tracks = track_persons(frames, frame_rate=10.0, person_threshold=0.15)
    assert len(tracks) == 2
    helmet_states = {
        track["track_id"]: {b["attributes"]["has_helmet"] for b in track["boxes"]}
        for track in tracks
    }
    # Cada track debe ser consistentemente con o sin casco (nunca ambos con True).
    with_helmet = [tid for tid, states in helmet_states.items() if True in states]
    assert len(with_helmet) == 1
    without_helmet = [tid for tid, states in helmet_states.items() if states == {False}]
    assert len(without_helmet) == 1


def test_bind_label_matchea_las_tres_clases():
    assert _bind_label("person") == "person"
    assert _bind_label("a person wearing gear") == "person"
    assert _bind_label("helmet") == "helmet"
    assert _bind_label("safety vest") == "vest"


def test_bind_label_span_parcial_safety_es_chaleco():
    # GDINO trocea el prompt y devuelve 'safety' suelto en vez de 'safety vest'
    # (medido: 105 spans en el clip de obra real). Si eso NO matchea vest, el
    # chaleco se pierde, el voto por mayoría consolida has_vest=False y se
    # FABRICA una infracción CR-02 sobre alguien que sí lo llevaba puesto.
    assert _bind_label("safety") == "vest"
    assert _bind_label("safety ") == "vest"


def test_bind_label_span_no_matcheado_no_devuelve_clase():
    # Span que no contiene ninguna substring conocida: debe devolver None para
    # que el llamador lo cuente y advierta, en vez de descartarlo sin señal
    # (Task 10 review, IMPORTANT 1).
    assert _bind_label("excavator") is None
    assert _bind_label("") is None


def test_bind_label_cuenta_spans_no_matcheados_con_counter():
    """Reproduce el patrón de conteo usado en _make_detector.detect: un Counter
    acumula los spans no matcheados; los matcheados no lo tocan."""
    # 'safety' NO va acá: es un span parcial de 'safety vest' y matchea vest
    # (ver test_bind_label_span_parcial_safety_es_chaleco). Los no matcheados
    # son spans de objetos ajenos al prompt.
    labels = ["person", "excavator", "helmet", "excavator"]
    unmatched: Counter[str] = Counter()
    matched = []
    for label in labels:
        category = _bind_label(label)
        if category is None:
            unmatched[label] += 1
        else:
            matched.append(category)
    assert matched == ["person", "helmet"]
    assert unmatched == Counter({"excavator": 2})


def test_nms_suprime_duplicados_de_la_misma_persona():
    # GDINO emite varias cajas casi identicas para el mismo operario. Con el
    # umbral de recall (0.15) esto daba ~6 cajas por persona: no es recall, es
    # ruido que el anotador tiene que borrar a mano en CVAT.
    duplicados = [
        ((100.0, 50.0, 160.0, 250.0), 0.90),
        ((102.0, 52.0, 158.0, 248.0), 0.40),  # misma persona, IoU alto -> fuera
        ((104.0, 48.0, 162.0, 252.0), 0.20),  # misma persona -> fuera
    ]
    (survivor,) = nms(duplicados, iou_threshold=0.5)
    assert survivor[1] == 0.90  # sobrevive la de mayor score


def test_nms_conserva_personas_distintas():
    # Dos operarios separados no deben fusionarse: NMS no puede costar recall
    # de personas distintas (seria la direccion peligrosa: perder un sujeto).
    dos_personas = [
        ((100.0, 50.0, 160.0, 250.0), 0.90),
        ((300.0, 50.0, 360.0, 250.0), 0.85),  # bien separada
        ((150.0, 50.0, 210.0, 250.0), 0.80),  # adyacente, solapa poco
    ]
    assert len(nms(dos_personas, iou_threshold=0.5)) == 3
