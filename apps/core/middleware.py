"""Middleware transversal de UniCare."""

from __future__ import annotations

from collections.abc import Callable

from django.http import HttpRequest, HttpResponse

from apps.core.context import reset_current_request, set_current_request


class CurrentUserMiddleware:
    """Expone la peticion en curso al resto de capas.

    Se guarda la peticion, no `request.user`: con JWT el usuario todavia no
    esta autenticado en este punto (lo hace DRF, mas tarde, dentro de la vista).
    Guardar el request permite leer el usuario ya resuelto cuando la auditoria
    lo necesite. Ver `apps.core.context`.

    El valor se limpia SIEMPRE al terminar, incluso si la vista lanza, para que
    no se filtre a la siguiente peticion atendida por el mismo hilo.
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        token = set_current_request(request)
        try:
            return self.get_response(request)
        finally:
            reset_current_request(token)
