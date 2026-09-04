"""Sonda de salud del contenedor. Sin dependencias: solo la stdlib.

Sustituye a `curl` en el HEALTHCHECK de la imagen. La razon no es estetica:
`curl` era el unico motivo para instalar un paquete de sistema extra en la
imagen de runtime, y `curl -f` NO falla ante un 3xx, asi que un redirect a
HTTPS se contaba como contenedor sano. Aqui solo el 200 es exito.

Se comprueba la LIVENESS, no la readiness: si PostgreSQL se cae, el contenedor
no esta roto y reiniciarlo no arregla nada. Con `HEALTHCHECK_PATH` se puede
apuntar a `/api/v1/health/ready/` cuando quien consulta es un balanceador.

    python scripts/healthcheck.py     -> 0 sano, 1 enfermo
"""

from __future__ import annotations

import os
import sys
import urllib.error
from urllib.request import Request, urlopen

HOST = os.environ.get("HEALTHCHECK_HOST", "127.0.0.1")
PORT = os.environ.get("PORT", "8000")
PATH = os.environ.get("HEALTHCHECK_PATH", "/api/v1/health/")
TIMEOUT = float(os.environ.get("HEALTHCHECK_TIMEOUT", "5"))


def comprobar() -> int:
    url = f"http://{HOST}:{PORT}{PATH}"
    # El esquema es literal `http://`: la sonda habla con el proceso que tiene
    # al lado, dentro del contenedor. De ahi los `noqa: S310`.
    peticion = Request(url, method="GET")  # noqa: S310
    try:
        # urlopen sigue los redirects; un 3xx nunca llega aqui como exito
        # silencioso, y cualquier codigo >= 400 levanta HTTPError.
        with urlopen(peticion, timeout=TIMEOUT) as respuesta:  # noqa: S310
            if respuesta.status == 200:
                return 0
            print(f"{url} respondio {respuesta.status}", file=sys.stderr)
    except urllib.error.HTTPError as error:
        print(f"{url} respondio {error.code}", file=sys.stderr)
    except OSError as error:
        # Incluye URLError, timeouts y conexion rechazada.
        print(f"{url} no responde: {error}", file=sys.stderr)
    return 1


if __name__ == "__main__":  # pragma: no cover - se ejecuta como proceso
    sys.exit(comprobar())
