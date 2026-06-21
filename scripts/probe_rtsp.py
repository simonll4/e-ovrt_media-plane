"""Probe a configured RTSP source without exposing its credentials."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from urllib.parse import urlsplit

from eovrt_media.config.loader import load_run_config
from eovrt_media.sources.rtsp_source import RtspSource


@dataclass(frozen=True)
class ProbeResult:
    endpoint: str
    frames_read: int
    width: int
    height: int
    elapsed_seconds: float


def redact_rtsp_url(url: str) -> str:
    """Return an RTSP endpoint without user info, query parameters, or fragments."""
    parsed = urlsplit(url)
    hostname = parsed.hostname or ""
    if ":" in hostname and not hostname.startswith("["):
        hostname = f"[{hostname}]"
    port = f":{parsed.port}" if parsed.port is not None else ""
    return f"{parsed.scheme}://{hostname}{port}{parsed.path}"


def probe(config_path: Path, frames: int) -> ProbeResult:
    """Read exactly ``frames`` from an RTSP source described by ``config_path``."""
    if frames < 1:
        raise ValueError("frames must be at least 1")

    config = load_run_config(config_path)
    source_config = config.source
    if source_config.type != "rtsp":
        raise ValueError("source.type must be rtsp")

    endpoint = source_config.url or source_config.path
    source = RtspSource(
        url=endpoint,
        reconnect_retries=source_config.reconnect_retries,
        reconnect_delay_ms=source_config.reconnect_delay_ms,
        max_units=frames,
    )

    started = perf_counter()
    iterator = iter(source)
    last_unit = None
    frames_read = 0
    for _ in range(frames):
        try:
            last_unit = next(iterator)
        except StopIteration:
            break
        frames_read += 1
    elapsed_seconds = perf_counter() - started

    if last_unit is None:
        raise RuntimeError(f"RTSP source returned {frames_read} of {frames} requested frames")
    if frames_read < frames:
        raise RuntimeError(f"RTSP source returned {frames_read} of {frames} requested frames")

    return ProbeResult(
        endpoint=redact_rtsp_url(endpoint),
        frames_read=frames_read,
        width=last_unit.width,
        height=last_unit.height,
        elapsed_seconds=elapsed_seconds,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe a configured RTSP source.")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--frames", type=int, required=True)
    args = parser.parse_args()

    try:
        result = probe(args.config, args.frames)
    except Exception as error:
        print(f"probe failed: {type(error).__name__}")
        return 1

    observed_fps = result.frames_read / result.elapsed_seconds if result.elapsed_seconds else float("inf")
    print(
        f"endpoint={result.endpoint} frames={result.frames_read} "
        f"resolution={result.width}x{result.height} observed_fps={observed_fps:.2f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
