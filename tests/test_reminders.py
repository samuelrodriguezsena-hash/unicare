"""Tests de recordatorios y tareas Celery (FASE 11).

Ningun envio real: el backend de notificaciones se sustituye por un doble.
Requiere PostgreSQL.

Nota sobre `on_commit`: los tests corren dentro de una transaccion que se
revierte, asi que las tareas encoladas con `transaction.on_commit` NO se
ejecutan salvo que se capturen con `django_capture_on_commit_callbacks`. Es
justamente lo que garantiza que el resto de la suite no genere recordatorios
sin querer.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from django.conf import settings
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.appointments import tasks
from apps.appointments.choices import ReminderChannel, ReminderStatus
from apps.appointments.models import Appointment, AppointmentReminder
from apps.appointments.services.reminders import ReminderService
from apps.core.models import User
from apps.core.services.notifications import (
    LoggingNotificationBackend,
    Notification,
    NotificationError,
    NotificationService,
)
from apps.people.models import Patient
from tests.db import saltar_si_no_hay_postgresql

saltar_si_no_hay_postgresql()

pytestmark = pytest.mark.django_db

CITAS = "/api/v1/appointments/"


class BackendFalso:
    """Doble del proveedor: registra los envios o falla a voluntad."""

    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.enviados: list[Notification] = []

    def send(self, notification: Notification) -> None:
        if self.error is not None:
            raise self.error
        self.enviados.append(notification)


@pytest.fixture
def paciente() -> Patient:
    return Patient.objects.create(
        identification_number="1098765432",
        first_name="Ana",
        last_name="Gomez",
        email="ana@example.com",
        phone="3001234567",
    )


@pytest.fixture
def cita(paciente: Patient) -> Appointment:
    return Appointment.objects.create(
        patient=paciente,
        scheduled_at=timezone.now() + timedelta(days=5),
        reason="Control post-quimioterapia",
    )


def servicio(backend: BackendFalso | None = None) -> ReminderService:
    return ReminderService(NotificationService(backend or BackendFalso()))


class TestProgramacion:
    def test_crea_un_recordatorio_por_cada_offset(self, cita: Appointment) -> None:
        creados = servicio().schedule(cita)

        assert len(creados) == 2
        momentos = sorted(r.scheduled_at for r in creados)
        assert momentos[0] == cita.scheduled_at - timedelta(hours=48)
        assert momentos[1] == cita.scheduled_at - timedelta(hours=24)

    def test_los_offsets_son_los_de_la_documentacion(self) -> None:
        assert ReminderService.offsets() == [48, 24]

    def test_los_offsets_son_configurables(self, cita: Appointment) -> None:
        with override_settings(REMINDER_OFFSETS_HOURS=[72, 48, 24, 2]):
            assert len(servicio().schedule(cita)) == 4

    def test_nacen_pendientes(self, cita: Appointment) -> None:
        for recordatorio in servicio().schedule(cita):
            assert recordatorio.status == ReminderStatus.PENDING
            assert recordatorio.sent_at is None

    def test_omite_los_avisos_cuyo_momento_ya_paso(self, paciente: Patient) -> None:
        # Cita dentro de 30 horas: el aviso de -48h ya no tiene sentido.
        cita = Appointment.objects.create(
            patient=paciente, scheduled_at=timezone.now() + timedelta(hours=30)
        )
        creados = servicio().schedule(cita)

        assert len(creados) == 1
        assert creados[0].scheduled_at == cita.scheduled_at - timedelta(hours=24)

    def test_no_programa_nada_para_una_cita_inminente(self, paciente: Patient) -> None:
        cita = Appointment.objects.create(
            patient=paciente, scheduled_at=timezone.now() + timedelta(hours=1)
        )
        assert servicio().schedule(cita) == []

    def test_es_idempotente(self, cita: Appointment) -> None:
        # El DER no declara UNIQUE(appointment, scheduled_at): lo garantiza el
        # servicio.
        servicio().schedule(cita)
        assert servicio().schedule(cita) == []
        assert cita.reminders.count() == 2


class TestEleccionDeCanal:
    def test_prefiere_email(self, cita: Appointment) -> None:
        assert ReminderService.choose_channel(cita) == ReminderChannel.EMAIL

    def test_usa_sms_si_no_hay_email(self, cita: Appointment) -> None:
        cita.patient.email = None
        assert ReminderService.choose_channel(cita) == ReminderChannel.SMS

    def test_sin_contacto_no_hay_canal(self, cita: Appointment) -> None:
        cita.patient.email = None
        cita.patient.phone = None
        assert ReminderService.choose_channel(cita) is None

    def test_sin_contacto_no_se_programan_recordatorios(
        self, cita: Appointment
    ) -> None:
        # Programar algo que no se puede entregar solo genera fallos.
        cita.patient.email = None
        cita.patient.phone = None
        cita.patient.save()

        assert servicio().schedule(cita) == []


class TestReprogramacion:
    def test_descarta_los_pendientes(self, cita: Appointment) -> None:
        servicio().schedule(cita)
        assert ReminderService.clear_pending(cita) == 2
        assert cita.reminders.count() == 0

    def test_conserva_los_ya_enviados(self, cita: Appointment) -> None:
        recordatorios = servicio().schedule(cita)
        enviado = recordatorios[0]
        enviado.status = ReminderStatus.SENT
        enviado.sent_at = timezone.now()
        enviado.save()

        ReminderService.clear_pending(cita)

        # Lo que el paciente ya recibio es historia y no se borra.
        assert list(cita.reminders.values_list("pk", flat=True)) == [enviado.pk]

    def test_rehace_los_avisos_con_la_nueva_fecha(self, cita: Appointment) -> None:
        servicio().schedule(cita)
        cita.scheduled_at = cita.scheduled_at + timedelta(days=10)
        cita.save()

        nuevos = servicio().reschedule(cita)

        assert len(nuevos) == 2
        assert all(r.scheduled_at > timezone.now() + timedelta(days=10) for r in nuevos)


class TestEnvio:
    def test_marca_enviado(self, cita: Appointment) -> None:
        backend = BackendFalso()
        recordatorio = servicio(backend).schedule(cita)[0]

        servicio(backend).send(recordatorio, is_last_attempt=False)

        recordatorio.refresh_from_db()
        assert recordatorio.status == ReminderStatus.SENT
        assert recordatorio.sent_at is not None
        assert recordatorio.failure_reason is None

    def test_un_fallo_no_marca_fallido_si_quedan_reintentos(
        self, cita: Appointment
    ) -> None:
        recordatorio = servicio().schedule(cita)[0]
        fallando = servicio(BackendFalso(NotificationError("proveedor caido")))

        with pytest.raises(NotificationError):
            fallando.send(recordatorio, is_last_attempt=False)

        recordatorio.refresh_from_db()
        # Aun se va a reintentar: darlo por perdido ahora seria prematuro.
        assert recordatorio.status == ReminderStatus.PENDING
        assert recordatorio.failure_reason is None

    def test_en_el_ultimo_intento_marca_fallido_con_el_motivo(
        self, cita: Appointment
    ) -> None:
        recordatorio = servicio().schedule(cita)[0]
        fallando = servicio(BackendFalso(NotificationError("proveedor caido")))

        with pytest.raises(NotificationError):
            fallando.send(recordatorio, is_last_attempt=True)

        recordatorio.refresh_from_db()
        assert recordatorio.status == ReminderStatus.FAILED
        assert "proveedor caido" in recordatorio.failure_reason
        assert recordatorio.sent_at is None

    def test_no_reenvia_uno_ya_enviado(self, cita: Appointment) -> None:
        backend = BackendFalso()
        recordatorio = servicio(backend).schedule(cita)[0]
        servicio(backend).send(recordatorio, is_last_attempt=False)

        servicio(backend).send(recordatorio, is_last_attempt=False)

        assert len(backend.enviados) == 1


class TestContenidoDelMensaje:
    def test_va_al_contacto_del_canal(self, cita: Appointment) -> None:
        recordatorio = servicio().schedule(cita)[0]
        mensaje = ReminderService.build_notification(recordatorio)

        assert mensaje.channel == ReminderChannel.EMAIL
        assert mensaje.recipient == "ana@example.com"

    def test_usa_el_telefono_en_sms(self, cita: Appointment) -> None:
        cita.patient.email = None
        cita.patient.save()
        recordatorio = servicio().schedule(cita)[0]

        mensaje = ReminderService.build_notification(recordatorio)
        assert mensaje.recipient == "3001234567"

    def test_no_revela_informacion_clinica(self, cita: Appointment) -> None:
        """Un recordatorio viaja por un canal no seguro."""
        recordatorio = servicio().schedule(cita)[0]
        mensaje = ReminderService.build_notification(recordatorio)

        assert "Control post-quimioterapia" not in mensaje.body
        assert "1098765432" not in mensaje.body
        assert "Ana" in mensaje.body


class TestSeleccionDeVencidos:
    def test_solo_los_pendientes_cuyo_momento_llego(self, cita: Appointment) -> None:
        vencido, futuro = servicio().schedule(cita)
        AppointmentReminder.objects.filter(pk=vencido.pk).update(
            scheduled_at=timezone.now() - timedelta(minutes=5)
        )

        # El otro sigue en el futuro y no debe seleccionarse.
        assert futuro.scheduled_at > timezone.now()
        assert ReminderService.due() == [vencido.pk]

    def test_ignora_los_ya_enviados(self, cita: Appointment) -> None:
        recordatorio = servicio().schedule(cita)[0]
        AppointmentReminder.objects.filter(pk=recordatorio.pk).update(
            scheduled_at=timezone.now() - timedelta(minutes=5),
            status=ReminderStatus.SENT,
        )

        assert ReminderService.due() == []

    def test_ignora_los_fallidos_definitivamente(self, cita: Appointment) -> None:
        recordatorio = servicio().schedule(cita)[0]
        AppointmentReminder.objects.filter(pk=recordatorio.pk).update(
            scheduled_at=timezone.now() - timedelta(minutes=5),
            status=ReminderStatus.FAILED,
        )

        assert ReminderService.due() == []


class TestTareasCelery:
    def test_dispatch_encola_solo_los_vencidos(
        self, cita: Appointment, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        recordatorio = servicio().schedule(cita)[0]
        AppointmentReminder.objects.filter(pk=recordatorio.pk).update(
            scheduled_at=timezone.now() - timedelta(minutes=1)
        )

        encolados: list[int] = []
        monkeypatch.setattr(
            tasks.send_reminder, "delay", lambda pk: encolados.append(pk)
        )

        assert tasks.dispatch_due_reminders() == 1
        assert encolados == [recordatorio.pk]

    def test_dispatch_no_envia_por_si_mismo(
        self, cita: Appointment, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Un proveedor lento no debe bloquear el resto del lote."""
        recordatorio = servicio().schedule(cita)[0]
        AppointmentReminder.objects.filter(pk=recordatorio.pk).update(
            scheduled_at=timezone.now() - timedelta(minutes=1)
        )
        monkeypatch.setattr(tasks.send_reminder, "delay", lambda pk: None)

        tasks.dispatch_due_reminders()

        recordatorio.refresh_from_db()
        assert recordatorio.status == ReminderStatus.PENDING

    def test_send_reminder_envia(self, cita: Appointment) -> None:
        recordatorio = servicio().schedule(cita)[0]

        assert tasks.send_reminder(recordatorio.pk) == "sent"

        recordatorio.refresh_from_db()
        assert recordatorio.status == ReminderStatus.SENT

    def test_send_reminder_tolera_que_ya_no_exista(self) -> None:
        # Pudo borrarse al reprogramar entre el encolado y el envio.
        assert tasks.send_reminder(999999) == "missing"

    def test_schedule_task(self, cita: Appointment) -> None:
        assert tasks.schedule_reminders_for_appointment(cita.pk) == 2

    def test_schedule_task_tolera_una_cita_inexistente(self) -> None:
        assert tasks.schedule_reminders_for_appointment(999999) == 0

    def test_reschedule_task(self, cita: Appointment) -> None:
        servicio().schedule(cita)
        Appointment.objects.filter(pk=cita.pk).update(
            scheduled_at=timezone.now() + timedelta(days=20)
        )

        assert tasks.reschedule_reminders_for_appointment(cita.pk) == 2
        assert cita.reminders.count() == 2

    def test_reschedule_task_tolera_una_cita_inexistente(self) -> None:
        assert tasks.reschedule_reminders_for_appointment(999999) == 0


class TestConfiguracionDeReintentos:
    """C-05: los reintentos son de Celery, no columnas del DER."""

    def test_send_reminder_reintenta_ante_fallo_del_proveedor(self) -> None:
        assert NotificationError in tasks.send_reminder.autoretry_for
        assert tasks.send_reminder.max_retries == 3

    def test_usa_backoff_exponencial(self) -> None:
        assert tasks.send_reminder.retry_backoff is True

    def test_el_der_no_persiste_el_numero_de_intentos(self) -> None:
        columnas = {f.column for f in AppointmentReminder._meta.concrete_fields}
        assert "retry_count" not in columnas
        assert "attempts" not in columnas
        # Lo que si existe para registrar el resultado final.
        assert {"status", "sent_at", "failure_reason"} <= columnas


class TestPlanificador:
    def test_el_despacho_esta_registrado_en_beat(self) -> None:
        entrada = settings.CELERY_BEAT_SCHEDULE["dispatch-due-reminders"]
        assert entrada["task"] == "apps.appointments.tasks.dispatch_due_reminders"

    def test_la_tarea_planificada_existe_de_verdad(self) -> None:
        # En la FASE 2 esto se dejo vacio precisamente para no encolar una
        # tarea que ningun worker supiera ejecutar.
        from config import celery_app

        for entrada in settings.CELERY_BEAT_SCHEDULE.values():
            assert entrada["task"] in celery_app.tasks

    def test_el_worker_descubre_las_tareas_al_arrancar(self) -> None:
        """Comprobacion en un proceso LIMPIO.

        Dentro de esta suite el registro esta poblado porque el propio modulo
        de test importa `apps.appointments.tasks`. Eso enmascararia un fallo de
        autodescubrimiento: el worker de produccion no importa nada a mano.
        Por eso se arranca un interprete aparte que solo hace lo que hace el
        worker: `loader.import_default_modules()`.
        """
        import subprocess
        import sys

        guion = (
            "import django; django.setup();"
            "from config import celery_app;"
            "celery_app.loader.import_default_modules();"
            "print(*sorted(t for t in celery_app.tasks if t.startswith('apps.')))"
        )
        salida = subprocess.run(  # noqa: S603 - guion literal, sin entrada externa
            [sys.executable, "-c", guion],
            capture_output=True,
            text=True,
            check=True,
            timeout=120,
        )
        descubiertas = salida.stdout.split()

        for entrada in settings.CELERY_BEAT_SCHEDULE.values():
            assert entrada["task"] in descubiertas
        assert "apps.appointments.tasks.send_reminder" in descubiertas

    def test_no_se_uso_django_celery_beat(self) -> None:
        # DEC-11: crearia tablas fuera del DER.
        assert "django_celery_beat" not in settings.INSTALLED_APPS


class TestBackendDeNotificaciones:
    def test_el_backend_por_defecto_no_envia_nada(self) -> None:
        assert (
            settings.NOTIFICATION_BACKEND
            == "apps.core.services.notifications.LoggingNotificationBackend"
        )

    def test_se_resuelve_desde_la_configuracion(self) -> None:
        assert isinstance(NotificationService().backend, LoggingNotificationBackend)

    def test_el_dominio_no_conoce_ningun_proveedor(self) -> None:
        """Integrar email o SMS no debe requerir tocar `appointments`."""
        from pathlib import Path

        fuente = Path("apps/appointments").rglob("*.py")
        for fichero in fuente:
            texto = fichero.read_text(encoding="utf-8")
            for proveedor in ("smtplib", "twilio", "sendgrid", "boto3"):
                assert proveedor not in texto

    def test_el_backend_por_defecto_es_intercambiable(self) -> None:
        backend = BackendFalso()
        NotificationService(backend).send(
            Notification(channel="EMAIL", recipient="x@y.z", subject="s", body="b")
        )
        assert len(backend.enviados) == 1


class TestIntegracionConLaAgenda:
    def test_agendar_una_cita_programa_sus_recordatorios(
        self, paciente: Patient, django_capture_on_commit_callbacks: Any
    ) -> None:
        cliente = APIClient()
        cliente.force_authenticate(
            user=User.objects.create_user(username="dra.rojas", password="x" * 14)
        )

        with django_capture_on_commit_callbacks(execute=True):
            respuesta = cliente.post(
                CITAS,
                {
                    "patient": paciente.pk,
                    "scheduled_at": (timezone.now() + timedelta(days=5)).isoformat(),
                },
                format="json",
            )

        assert respuesta.status_code == 201
        assert AppointmentReminder.objects.count() == 2

    def test_reprogramar_rehace_los_recordatorios(
        self, paciente: Patient, django_capture_on_commit_callbacks: Any
    ) -> None:
        cliente = APIClient()
        cliente.force_authenticate(
            user=User.objects.create_user(username="dra.rojas", password="x" * 14)
        )
        with django_capture_on_commit_callbacks(execute=True):
            cita = cliente.post(
                CITAS,
                {
                    "patient": paciente.pk,
                    "scheduled_at": (timezone.now() + timedelta(days=5)).isoformat(),
                },
                format="json",
            ).json()

        antiguos = set(AppointmentReminder.objects.values_list("pk", flat=True))

        with django_capture_on_commit_callbacks(execute=True):
            cliente.patch(
                f"{CITAS}{cita['appointment_id']}/",
                {"scheduled_at": (timezone.now() + timedelta(days=20)).isoformat()},
                format="json",
            )

        nuevos = set(AppointmentReminder.objects.values_list("pk", flat=True))
        assert nuevos.isdisjoint(antiguos)
        assert len(nuevos) == 2

    def test_los_recordatorios_aparecen_en_el_endpoint_de_la_cita(
        self, paciente: Patient, django_capture_on_commit_callbacks: Any
    ) -> None:
        cliente = APIClient()
        cliente.force_authenticate(
            user=User.objects.create_user(username="dra.rojas", password="x" * 14)
        )
        with django_capture_on_commit_callbacks(execute=True):
            cita = cliente.post(
                CITAS,
                {
                    "patient": paciente.pk,
                    "scheduled_at": (timezone.now() + timedelta(days=5)).isoformat(),
                },
                format="json",
            ).json()

        recordatorios = cliente.get(
            f"{CITAS}{cita['appointment_id']}/reminders/"
        ).json()

        assert len(recordatorios) == 2
        assert recordatorios[0]["status"] == ReminderStatus.PENDING
        assert recordatorios[0]["channel"] == ReminderChannel.EMAIL
