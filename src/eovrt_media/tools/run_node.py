"""Entrypoint two-node: arranca Nodo A (edge) o Nodo B (GPU) desde una run config.

Uso: `python -m eovrt_media.tools.run_node --role {a|b} --config <run.yaml>`

Reemplazo delgado del CLI eliminado en Fase 1 (Task 17): carga la RunConfig y
despacha a run_node_a/run_node_b. Pensado como ENTRYPOINT de los contenedores de
infra/twonode/ — reporta por exit code (0 ok, 1 falla) + stderr.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _run_a(config) -> None:
    from eovrt_media.runtime.two_node import run_node_a

    run_node_a(config)


def _run_b(config) -> None:
    from eovrt_media.runtime.two_node import run_node_b

    run_node_b(config)


_RUNNERS = {"a": _run_a, "b": _run_b}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="eovrt-run-node",
        description="Arranca un nodo del split two-node (a=edge, b=GPU).",
    )
    parser.add_argument("--role", choices=["a", "b"], required=True)
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args(argv)

    from eovrt_media.config.loader import load_run_config

    try:
        config = load_run_config(args.config)
        _RUNNERS[args.role](config)
    except Exception as error:  # exit code + stderr para el contenedor
        print(f"eovrt-run-node[{args.role}]: {error}", file=sys.stderr)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
