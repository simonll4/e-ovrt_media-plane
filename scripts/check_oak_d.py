"""Verifica conectividad con la OAK-D antes de cualquier test de hardware.

Uso: python scripts/check_oak_d.py [ip]   (default: 192.168.1.50 o EOVRT_OAK_D_HW_URL)
Sale con 0 si conecta; 1 con diagnóstico si no.
"""
from __future__ import annotations

import os
import sys


def main() -> int:
    ip = sys.argv[1] if len(sys.argv) > 1 else os.environ.get(
        "EOVRT_OAK_D_HW_URL", "192.168.1.50"
    )
    try:
        import depthai as dai
    except ImportError:
        print("FALTA depthai: pip install -e '.[edge]'")
        return 1
    try:
        # Pipeline vacío: solo handshake XLink por IP fija (nunca autodiscovery).
        with dai.Device(dai.Pipeline(), dai.DeviceInfo(ip)) as dev:
            cams = dev.getConnectedCameras()
            temp = dev.getChipTemperature().average
            print(f"OK: OAK-D en {ip} — cámaras: {cams}, chip: {temp:.1f}°C")
            return 0
    except Exception as exc:
        print(
            f"SIN CONEXIÓN con la OAK-D en {ip}: {exc}\n"
            "Checklist: ¿PoE con power? ¿IP correcta (reserva DHCP)? "
            "¿WSL puede alcanzar la LAN? Ver docs/contexto/oak-d-integration.md."
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
