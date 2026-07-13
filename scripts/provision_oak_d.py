#!/usr/bin/env python3
"""Provisiona la red de una OAK-D Pro PoE: pasa de IP estática de fábrica a DHCP.

POR QUÉ EXISTE
--------------
Las OAK PoE vienen de fábrica con **IP estática link-local** (169.254.1.222). Colgadas
de un router siguen ahí, mientras el host vive en otra subred (p.ej. 192.168.1.0/24):
no hay ruta entre ambas, y la cámara resulta invisible al ping, al ARP y al discovery.
No es un fallo de alimentación ni de DHCP: es la config grabada en su flash.
Este script la reescribe en modo DHCP, de una vez y para siempre.

DÓNDE SE CORRE  (importante)
---------------------------
**Desde Windows, NO desde WSL.** El bootloader se alcanza por discovery UDP broadcast,
y el NAT de WSL2 no lo deja pasar ("Specified device not found"). En cambio, el uso
normal de la cámara (lo que hace `OakDSource`) es TCP unicast contra su IP, y desde
WSL funciona perfecto. O sea: se provisiona desde Windows, se usa desde WSL.

NO MEZCLAR VERSIONES DEL SDK
----------------------------
Usar depthai v3 y v2 contra la misma cámara la deja en estado inconsistente y crashea
al bootear ("Device likely crashed", json.exception.type_error.302). Este script pide
la **misma major que el media-plane (v2)**, y aborta si encuentra otra.

USO
---
    # En Windows, con un venv que tenga 'depthai>=2.24,<3':
    python scripts/provision_oak_d.py --ip 192.168.1.50 --gateway 192.168.1.1

Después: power-cycle del PoE. La cámara pide DHCP y toma la IP. Conviene además hacer
una **reserva DHCP por MAC** en el router para que no cambie nunca.
"""
from __future__ import annotations

import argparse
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--ip", default="192.168.1.50",
                        help="IP preferida/fallback que se le pide al DHCP (default: 192.168.1.50)")
    parser.add_argument("--mask", default="255.255.255.0")
    parser.add_argument("--gateway", default="192.168.1.1")
    parser.add_argument("--static", action="store_true",
                        help="Grabar IP estática en vez de DHCP (no recomendado: no es portable)")
    args = parser.parse_args()

    try:
        import depthai as dai
    except ImportError:
        print("Falta el SDK: pip install 'depthai>=2.24,<3'", file=sys.stderr)
        return 1

    if not dai.__version__.startswith("2."):
        print(f"depthai {dai.__version__}: se requiere la major 2.x, la misma que usa el "
              f"media-plane. Mezclar v3 y v2 contra la misma cámara la hace crashear.",
              file=sys.stderr)
        return 1

    found, info = dai.DeviceBootloader.getFirstAvailableDevice()
    if not found:
        print("No se encontró ninguna OAK. Verificá que tenga alimentación PoE 802.3af "
              "y que estés corriendo esto desde Windows (no desde WSL).", file=sys.stderr)
        return 1

    print(f"Cámara: {info.getMxId()} @ {info.name} (estado: {info.state})")
    bl = dai.DeviceBootloader(info)
    print(f"Bootloader: {bl.getVersion()}")

    conf = dai.DeviceBootloader.Config()
    if args.static:
        conf.setStaticIPv4(args.ip, args.mask, args.gateway)
    else:
        conf.setDynamicIPv4(args.ip, args.mask, args.gateway)

    ok, err = bl.flashConfig(conf)
    if not ok:
        print(f"Falló el grabado: {err}", file=sys.stderr)
        bl.close()
        return 1

    verif = bl.readConfig()
    modo = "estática" if verif.isStaticIPV4() else "DHCP"
    print(f"Grabado OK -> modo {modo} | ip {verif.getIPv4()} | mask {verif.getIPv4Mask()} "
          f"| gw {verif.getIPv4Gateway()}")
    bl.close()

    print("\nAhora: power-cycle del PoE. Después verificá con:")
    print(f"    ping {args.ip}")
    print("Y hacé una reserva DHCP por MAC en el router para fijarla.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
