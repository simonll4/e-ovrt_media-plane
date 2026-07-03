"""Ejecutar una campaña de debug del media plane.

Uso: `python -m eovrt_media.tools.debug_run --source bench-val [...]`

Nota: esta utilidad depende de `eovrt_media.debugging.session.run_debug_session`, que a
su vez orquesta `eovrt_media.runtime.two_node_local` (banco two-node nativo en
localhost). Ver docs/superpowers/sdd/task-17-report.md para el detalle de por qué ese
módulo se conserva en esta migración en vez de eliminarse.
"""

from __future__ import annotations

from pathlib import Path

from rich.console import Console

console = Console()


def debug_run(
    source: str,
    video: Path | None = None,
    rtsp_url: str | None = None,
    model_ref: str = "yoloe/yoloe-26s",
    device: str = "cuda:0",
    codecs: str = "raw,jpeg",
    payload_format: str = "uint8_rgb",
    max_units: int | None = None,
    session_id: str | None = None,
    debug: bool = True,
    skip_probe: bool = False,
) -> None:
    """Ejecutar campaña de debug del media plane."""
    from eovrt_media.debugging.session import DebugRunOptions, run_debug_session

    codec_list = [item.strip() for item in codecs.split(",") if item.strip()]
    if not codec_list:
        console.print("[red]✗ Debe indicar al menos un codec.[/red]")
        raise SystemExit(1)
    try:
        result = run_debug_session(
            DebugRunOptions(
                source=source,
                video=video,
                rtsp_url=rtsp_url,
                model_ref=model_ref,
                device=device,
                codecs=codec_list,
                payload_format=payload_format,
                max_units=max_units,
                session_id=session_id,
                debug=debug,
                skip_probe=skip_probe,
            )
        )
    except Exception as error:
        console.print(f"[red]✗ Debug session falló:[/red] {error}")
        raise SystemExit(1)
    console.print("\n[bold cyan]Debug session[/bold cyan]")
    console.print(f"  Session: {result.session_dir}")
    console.print(f"  Report JSON: {result.report_json}")
    console.print(f"  Report MD:   {result.report_markdown}")
    console.print(f"  Runs:        {len(result.runs)}")


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(prog="eovrt-debug-run")
    parser.add_argument("--source", required=True, help="bench-val, bench-test, demo, video, ezviz.")
    parser.add_argument("--video", type=Path, default=None, help="Archivo de video para --source video.")
    parser.add_argument("--rtsp-url", default=None, help="URL RTSP para --source ezviz.")
    parser.add_argument("--model-ref", default="yoloe/yoloe-26s")
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--codecs", default="raw,jpeg", help="Lista separada por comas.")
    parser.add_argument("--payload-format", default="uint8_rgb")
    parser.add_argument("--max-units", type=int, default=None)
    parser.add_argument("--session-id", default=None)
    parser.add_argument("--debug", dest="debug", action="store_true", default=True)
    parser.add_argument("--no-debug", dest="debug", action="store_false")
    parser.add_argument("--skip-probe", action="store_true", default=False)
    args = parser.parse_args()
    debug_run(
        source=args.source,
        video=args.video,
        rtsp_url=args.rtsp_url,
        model_ref=args.model_ref,
        device=args.device,
        codecs=args.codecs,
        payload_format=args.payload_format,
        max_units=args.max_units,
        session_id=args.session_id,
        debug=args.debug,
        skip_probe=args.skip_probe,
    )


if __name__ == "__main__":
    main()
