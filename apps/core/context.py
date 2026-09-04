"""Usuario responsable de la operacion en curso.

La auditoria necesita saber QUIEN provoca cada cambio, pero los modelos y las
signals no tienen acceso al `request`. Se resuelve con `ContextVar`, que a
diferencia de un thread-local funciona igual con hilos y con codigo asincrono, y
se aisla solo entre peticiones concurrentes.

Detalle importante con JWT: el middleware NO puede guardar `request.user`, porque
en ese momento todavia vale `AnonymousUser`. DRF autentica en la vista y solo
entonces reasigna `request.user`. Por eso se guarda el REQUEST y el usuario se
lee de el en el ultimo momento, cuando la auditoria lo necesita.

Fuera de una peticion HTTP (Celery, comandos de gestion) esto queda vacio y la
auditoria recurre al usuario tecnico `system` (docs/DECISIONS.md, C-04).
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover
    from apps.core.models import User

# Peticion HTTP en curso, si la hay.
_current_request: ContextVar[Any] = ContextVar("unicare_current_request", default=None)

# Usuario fijado explicitamente, que tiene prioridad sobre el de la peticion.
# Lo usa `acting_as()` para propagar el responsable a una tarea Celery.
_explicit_user: ContextVar[Any] = ContextVar("unicare_explicit_user", default=None)


def set_current_request(request: Any) -> object:
    """Registra la peticion en curso. Devuelve el token para deshacerlo."""
    return _current_request.set(request)


def reset_current_request(token: object) -> None:
    _current_request.reset(token)  # type: ignore[arg-type]


def get_current_user() -> User | None:
    """Usuario responsable de la operacion en curso, o `None`.

    `None` es un resultado legitimo: significa que la operacion no proviene de
    una peticion HTTP autenticada.
    """
    user = _explicit_user.get()
    if user is None:
        request = _current_request.get()
        user = getattr(request, "user", None) if request is not None else None

    if user is None or not getattr(user, "is_authenticated", False):
        return None
    return user


@contextmanager
def acting_as(user: User | None) -> Iterator[None]:
    """Ejecuta un bloque atribuyendo los cambios a `user`.

    Sirve para propagar el usuario que origino una carga masiva hasta la tarea
    Celery que la procesa, donde ya no hay peticion HTTP.
    """
    token = _explicit_user.set(user)
    try:
        yield
    finally:
        _explicit_user.reset(token)
