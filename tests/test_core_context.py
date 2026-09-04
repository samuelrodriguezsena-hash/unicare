"""Tests del contexto de usuario y su middleware.

No necesitan base de datos: se trabaja con instancias no persistidas.
"""

from __future__ import annotations

from django.http import HttpResponse
from django.test import RequestFactory

from apps.core.context import acting_as, get_current_user, set_current_request
from apps.core.middleware import CurrentUserMiddleware
from apps.core.models import User


class TestUsuarioActual:
    def test_sin_contexto_no_hay_usuario(self) -> None:
        assert get_current_user() is None

    def test_acting_as_fija_y_restaura(self) -> None:
        usuario = User(user_id=1, username="dra.rojas")
        with acting_as(usuario):
            assert get_current_user() is usuario
        assert get_current_user() is None

    def test_acting_as_restaura_aunque_haya_excepcion(self) -> None:
        try:
            with acting_as(User(user_id=1, username="x")):
                raise RuntimeError("fallo de negocio")
        except RuntimeError:
            pass
        assert get_current_user() is None

    def test_un_anonimo_no_cuenta_como_usuario(self) -> None:
        from django.contrib.auth.models import AnonymousUser

        request = RequestFactory().get("/")
        request.user = AnonymousUser()
        set_current_request(request)
        assert get_current_user() is None


class TestCurrentUserMiddleware:
    def test_expone_el_usuario_asignado_despues_por_drf(self) -> None:
        """El fallo que este middleware evita.

        Con JWT, en el momento en que corre el middleware `request.user` todavia
        es anonimo: DRF autentica dentro de la vista y solo entonces reasigna
        `request.user`. Por eso se guarda el REQUEST, no el usuario.
        """
        usuario = User(user_id=7, username="dr.silva")
        visto = {}

        def vista(request) -> HttpResponse:
            # Simula lo que hace DRF al autenticar dentro de la vista.
            request.user = usuario
            visto["usuario"] = get_current_user()
            return HttpResponse()

        request = RequestFactory().get("/")
        request.user = None
        CurrentUserMiddleware(vista)(request)

        assert visto["usuario"] is usuario

    def test_limpia_el_contexto_al_terminar(self) -> None:
        def vista(request) -> HttpResponse:
            request.user = User(user_id=7, username="dr.silva")
            return HttpResponse()

        request = RequestFactory().get("/")
        CurrentUserMiddleware(vista)(request)

        assert get_current_user() is None

    def test_limpia_el_contexto_aunque_la_vista_falle(self) -> None:
        def vista(request) -> HttpResponse:
            request.user = User(user_id=7, username="dr.silva")
            raise RuntimeError("500")

        request = RequestFactory().get("/")
        try:
            CurrentUserMiddleware(vista)(request)
        except RuntimeError:
            pass

        # Si no se limpiara, la siguiente peticion del mismo hilo heredaria el
        # usuario y la auditoria atribuiria cambios a quien no los hizo.
        assert get_current_user() is None

    def test_el_usuario_explicito_tiene_prioridad_sobre_la_peticion(self) -> None:
        de_la_peticion = User(user_id=1, username="peticion")
        explicito = User(user_id=2, username="explicito")

        def vista(request) -> HttpResponse:
            request.user = de_la_peticion
            with acting_as(explicito):
                assert get_current_user() is explicito
            return HttpResponse()

        CurrentUserMiddleware(vista)(RequestFactory().get("/"))
