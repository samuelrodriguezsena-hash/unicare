"""Tests de la carga masiva (FASE 12).

Requiere PostgreSQL: se verifica lo que queda persistido y que una fila
invalida no arrastre a las demas.
"""

from __future__ import annotations

import io
from datetime import date, datetime

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from apps.core.models import AuditLog, User
from apps.massive_load import tasks
from apps.massive_load.choices import ImportBatchRowStatus, ImportBatchStatus
from apps.massive_load.models import ImportBatch, ImportBatchRow
from apps.massive_load.parsers import ImportParseError, parse_csv, parse_xlsx
from apps.massive_load.services.import_batches import (
    ImportService,
    RowError,
    parse_booleano,
    parse_fecha,
)
from apps.people.models import Pathology, Patient, PatientPathology
from tests.db import saltar_si_no_hay_postgresql

saltar_si_no_hay_postgresql()

pytestmark = pytest.mark.django_db

LOTES = "/api/v1/import-batches/"

CABECERA = "identification_number,first_name,last_name,pathology,date_of_birth\n"
FILA_ANA = "1000000001,Ana,Gomez,Carcinoma ductal,1980-05-14\n"
FILA_LUIS = "1000000002,Luis,Perez,Melanoma,1975-03-02\n"


@pytest.fixture
def clinico() -> User:
    return User.objects.create_user(username="dra.rojas", password="x" * 14)


@pytest.fixture
def client(clinico: User) -> APIClient:
    api = APIClient()
    api.force_authenticate(user=clinico)
    return api


def csv_archivo(contenido: str, nombre: str = "pacientes.csv") -> SimpleUploadedFile:
    return SimpleUploadedFile(nombre, contenido.encode("utf-8"), "text/csv")


def xlsx_archivo(filas: list[list], nombre: str = "pacientes.xlsx"):
    from openpyxl import Workbook

    libro = Workbook()
    hoja = libro.active
    for fila in filas:
        hoja.append(fila)
    buffer = io.BytesIO()
    libro.save(buffer)
    return SimpleUploadedFile(
        nombre,
        buffer.getvalue(),
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


def importar(client: APIClient, archivo) -> dict:
    return client.post(LOTES, {"file": archivo}, format="multipart").json()


class TestParseoCsv:
    def test_lee_las_filas(self) -> None:
        filas = parse_csv((CABECERA + FILA_ANA + FILA_LUIS).encode())
        assert len(filas) == 2
        assert filas[0]["first_name"] == "Ana"

    def test_normaliza_las_cabeceras(self) -> None:
        crudo = (
            "Identification_Number, First Name ,last_name,pathology\n1,Ana,Gomez,X\n"
        )
        filas = parse_csv(crudo.encode())
        assert filas[0]["first_name"] == "Ana"

    def test_descarta_el_bom_de_excel(self) -> None:
        contenido = "﻿" + CABECERA + FILA_ANA
        filas = parse_csv(contenido.encode("utf-8"))
        assert filas[0]["identification_number"] == "1000000001"

    def test_ignora_columnas_desconocidas(self) -> None:
        crudo = (
            "identification_number,first_name,last_name,pathology,columna_rara\n"
            "1,Ana,Gomez,X,basura\n"
        )
        assert "columna_rara" not in parse_csv(crudo.encode())[0]

    def test_falla_si_faltan_columnas_obligatorias(self) -> None:
        with pytest.raises(ImportParseError) as exc:
            parse_csv(b"identification_number,first_name\n1,Ana\n")
        assert "last_name" in str(exc.value)

    def test_falla_si_no_es_utf8(self) -> None:
        with pytest.raises(ImportParseError):
            parse_csv((CABECERA + FILA_ANA).encode("utf-16"))

    def test_falla_si_esta_vacio(self) -> None:
        with pytest.raises(ImportParseError):
            parse_csv(b"")


class TestParseoXlsx:
    def test_lee_las_filas(self) -> None:
        archivo = xlsx_archivo(
            [
                ["identification_number", "first_name", "last_name", "pathology"],
                ["1000000001", "Ana", "Gomez", "Carcinoma ductal"],
            ]
        )
        filas = parse_xlsx(archivo.read())
        assert filas[0]["last_name"] == "Gomez"

    def test_ignora_las_filas_vacias_del_final(self) -> None:
        archivo = xlsx_archivo(
            [
                ["identification_number", "first_name", "last_name", "pathology"],
                ["1", "Ana", "Gomez", "X"],
                [None, None, None, None],
            ]
        )
        assert len(parse_xlsx(archivo.read())) == 1

    def test_falla_si_faltan_columnas(self) -> None:
        archivo = xlsx_archivo([["identification_number"], ["1"]])
        with pytest.raises(ImportParseError):
            parse_xlsx(archivo.read())

    def test_falla_si_no_es_un_xlsx(self) -> None:
        with pytest.raises(ImportParseError):
            parse_xlsx(b"esto no es un xlsx")


class TestConversiones:
    @pytest.mark.parametrize(
        ("valor", "esperado"),
        [
            ("1980-05-14", date(1980, 5, 14)),
            ("14/05/1980", date(1980, 5, 14)),
            ("14-05-1980", date(1980, 5, 14)),
            (None, None),
        ],
    )
    def test_formatos_de_fecha_admitidos(self, valor, esperado) -> None:
        assert parse_fecha(valor, "date_of_birth") == esperado

    def test_una_fecha_invalida_da_el_motivo_exacto(self) -> None:
        with pytest.raises(RowError) as exc:
            parse_fecha("no-es-fecha", "date_of_birth")
        assert "Formato de fecha incorrecto" in str(exc.value)

    @pytest.mark.parametrize("valor", ["1", "true", "SI", "sí", "x"])
    def test_booleanos_verdaderos(self, valor: str) -> None:
        assert parse_booleano(valor) is True

    @pytest.mark.parametrize("valor", ["0", "no", ""])
    def test_booleanos_falsos(self, valor: str) -> None:
        assert parse_booleano(valor) is False


class TestSubida:
    def test_acepta_csv_y_encola(self, client: APIClient) -> None:
        respuesta = client.post(
            LOTES, {"file": csv_archivo(CABECERA + FILA_ANA)}, format="multipart"
        )

        assert respuesta.status_code == 202
        cuerpo = respuesta.json()
        assert cuerpo["source_file_name"] == "pacientes.csv"
        assert cuerpo["source_file_type"] == ".csv"
        assert cuerpo["total_rows"] == 1

    def test_acepta_xlsx(self, client: APIClient) -> None:
        archivo = xlsx_archivo(
            [
                ["identification_number", "first_name", "last_name", "pathology"],
                ["1000000001", "Ana", "Gomez", "Carcinoma ductal"],
            ]
        )
        respuesta = client.post(LOTES, {"file": archivo}, format="multipart")

        assert respuesta.status_code == 202
        assert respuesta.json()["source_file_type"] == ".xlsx"

    @pytest.mark.parametrize("nombre", ["datos.xls", "datos.txt", "datos"])
    def test_rechaza_otras_extensiones(self, client: APIClient, nombre: str) -> None:
        respuesta = client.post(
            LOTES, {"file": csv_archivo(CABECERA, nombre)}, format="multipart"
        )
        assert respuesta.status_code == 400

    def test_rechaza_un_archivo_sin_las_columnas_obligatorias(
        self, client: APIClient
    ) -> None:
        # El archivo entero es inservible: no hay nada que importar.
        respuesta = client.post(
            LOTES,
            {"file": csv_archivo("identification_number\n1\n")},
            format="multipart",
        )
        assert respuesta.status_code == 400
        assert ImportBatch.objects.count() == 0

    def test_rechaza_un_archivo_sin_filas(self, client: APIClient) -> None:
        respuesta = client.post(
            LOTES, {"file": csv_archivo(CABECERA)}, format="multipart"
        )
        assert respuesta.status_code == 400

    def test_persiste_una_fila_por_linea(self, client: APIClient) -> None:
        # DEC-32: el DER no tiene donde guardar el archivo; las filas SON el
        # estado intermedio.
        lote = importar(client, csv_archivo(CABECERA + FILA_ANA + FILA_LUIS))

        registros = ImportBatchRow.objects.filter(
            import_batch_id=lote["import_batch_id"]
        ).order_by("row_number")
        assert [r.row_number for r in registros] == [1, 2]
        assert registros[0].patient_name_snapshot == "Ana Gomez"
        assert registros[0].pathology_name_snapshot == "Carcinoma ductal"

    def test_un_anonimo_no_puede_importar(self) -> None:
        respuesta = APIClient().post(
            LOTES, {"file": csv_archivo(CABECERA + FILA_ANA)}, format="multipart"
        )
        assert respuesta.status_code == 401


class TestProcesamiento:
    def test_crea_los_pacientes_nuevos(self, client: APIClient) -> None:
        importar(client, csv_archivo(CABECERA + FILA_ANA + FILA_LUIS))

        assert Patient.objects.count() == 2
        assert Patient.objects.filter(identification_number="1000000001").exists()

    def test_asocia_la_patologia(self, client: APIClient) -> None:
        importar(client, csv_archivo(CABECERA + FILA_ANA))

        paciente = Patient.objects.get(identification_number="1000000001")
        assert paciente.pathologies.first().pathology.name == "Carcinoma ductal"

    def test_reutiliza_un_paciente_existente(self, client: APIClient) -> None:
        Patient.objects.create(
            identification_number="1000000001", first_name="Ana", last_name="Gomez"
        )
        fila = "1000000001,Ana,Gomez,Melanoma,\n"
        importar(client, csv_archivo(CABECERA + fila))

        assert Patient.objects.count() == 1
        assert Patient.objects.get().pathologies.count() == 1

    def test_no_duplica_una_patologia_ya_asociada(self, client: APIClient) -> None:
        # Reimportar el mismo archivo no debe fallar ni duplicar.
        importar(client, csv_archivo(CABECERA + FILA_ANA))
        lote = importar(client, csv_archivo(CABECERA + FILA_ANA))

        assert PatientPathology.objects.count() == 1
        assert ImportBatch.objects.get(pk=lote["import_batch_id"]).success_count == 1

    def test_reutiliza_una_patologia_existente(self, client: APIClient) -> None:
        Pathology.objects.create(name="Carcinoma ductal")
        importar(client, csv_archivo(CABECERA + FILA_ANA))

        assert Pathology.objects.filter(name="Carcinoma ductal").count() == 1

    def test_guarda_la_fecha_de_nacimiento(self, client: APIClient) -> None:
        importar(client, csv_archivo(CABECERA + FILA_ANA))

        paciente = Patient.objects.get(identification_number="1000000001")
        assert paciente.date_of_birth == date(1980, 5, 14)

    def test_marca_el_lote_como_completado(self, client: APIClient) -> None:
        lote = importar(client, csv_archivo(CABECERA + FILA_ANA + FILA_LUIS))

        registro = ImportBatch.objects.get(pk=lote["import_batch_id"])
        assert registro.status == ImportBatchStatus.COMPLETED
        assert registro.total_rows == 2
        assert registro.success_count == 2
        assert registro.failure_count == 0
        assert registro.processed_at is not None


class TestFilasInvalidas:
    def test_una_fila_invalida_no_detiene_la_carga(self, client: APIClient) -> None:
        """Requisito explicito de la documentacion."""
        mala = ",,,,\n"
        lote = importar(client, csv_archivo(CABECERA + FILA_ANA + mala + FILA_LUIS))

        registro = ImportBatch.objects.get(pk=lote["import_batch_id"])
        assert registro.status == ImportBatchStatus.COMPLETED_WITH_ERRORS
        assert registro.success_count == 2
        assert registro.failure_count == 1
        # Los pacientes de las filas buenas SI se crearon.
        assert Patient.objects.count() == 2

    def test_registra_el_motivo_de_cada_error(self, client: APIClient) -> None:
        sin_fecha_valida = "1000000003,Eva,Nieto,Melanoma,no-es-fecha\n"
        lote = importar(client, csv_archivo(CABECERA + sin_fecha_valida))

        fila = ImportBatchRow.objects.get(import_batch_id=lote["import_batch_id"])
        assert fila.status == ImportBatchRowStatus.ERROR
        assert "Formato de fecha incorrecto" in fila.error_message

    def test_identificacion_invalida(self, client: APIClient) -> None:
        mala = "10 00 01,Eva,Nieto,Melanoma,\n"
        lote = importar(client, csv_archivo(CABECERA + mala))

        fila = ImportBatchRow.objects.get(import_batch_id=lote["import_batch_id"])
        assert fila.status == ImportBatchRowStatus.ERROR
        assert "identificacion" in fila.error_message

    def test_falta_la_patologia(self, client: APIClient) -> None:
        sin_patologia = "1000000004,Eva,Nieto,,\n"
        lote = importar(client, csv_archivo(CABECERA + sin_patologia))

        fila = ImportBatchRow.objects.get(import_batch_id=lote["import_batch_id"])
        assert "pathology" in fila.error_message

    def test_faltan_nombres(self, client: APIClient) -> None:
        sin_nombre = "1000000005,,Nieto,Melanoma,\n"
        lote = importar(client, csv_archivo(CABECERA + sin_nombre))

        fila = ImportBatchRow.objects.get(import_batch_id=lote["import_batch_id"])
        assert "first_name" in fila.error_message

    def test_una_fila_fallida_no_deja_datos_a_medias(self, client: APIClient) -> None:
        """Cada fila va en su propia transaccion."""
        # El paciente es valido pero la fecha de diagnostico no: la fila entera
        # debe revertirse, sin dejar el paciente creado.
        cabecera = CABECERA.rstrip("\n") + ",diagnosis_date\n"
        fila = "1000000006,Eva,Nieto,Melanoma,1990-01-01,fecha-mala\n"
        importar(client, csv_archivo(cabecera + fila))

        assert not Patient.objects.filter(identification_number="1000000006").exists()


class TestPatologiaPrincipal:
    def test_marca_la_principal(self, client: APIClient) -> None:
        cabecera = "identification_number,first_name,last_name,pathology,is_primary\n"
        fila = "1000000001,Ana,Gomez,Carcinoma ductal,si\n"
        importar(client, csv_archivo(cabecera + fila))

        assert PatientPathology.objects.get().is_primary is True

    def test_una_segunda_principal_se_asocia_como_secundaria(
        self, client: APIClient
    ) -> None:
        """El DER solo admite una principal por paciente.

        Se asocia igual, pero como secundaria: perder la fila entera por esto
        seria peor que registrar la patologia sin marcarla.
        """
        cabecera = "identification_number,first_name,last_name,pathology,is_primary\n"
        filas = (
            "1000000001,Ana,Gomez,Carcinoma ductal,si\n"
            "1000000001,Ana,Gomez,Melanoma,si\n"
        )
        lote = importar(client, csv_archivo(cabecera + filas))

        assert ImportBatch.objects.get(pk=lote["import_batch_id"]).failure_count == 0
        principales = PatientPathology.objects.filter(is_primary=True)
        assert principales.count() == 1
        assert PatientPathology.objects.count() == 2


class TestConsultaYReporte:
    def test_lista_los_lotes(self, client: APIClient) -> None:
        importar(client, csv_archivo(CABECERA + FILA_ANA))
        assert client.get(LOTES).json()["count"] == 1

    def test_detalle_con_contadores(self, client: APIClient) -> None:
        lote = importar(client, csv_archivo(CABECERA + FILA_ANA))
        cuerpo = client.get(f"{LOTES}{lote['import_batch_id']}/").json()

        assert cuerpo["total_rows"] == 1
        assert cuerpo["success_count"] == 1
        assert cuerpo["failure_count"] == 0

    def test_lista_las_filas(self, client: APIClient) -> None:
        lote = importar(client, csv_archivo(CABECERA + FILA_ANA + FILA_LUIS))
        cuerpo = client.get(f"{LOTES}{lote['import_batch_id']}/rows/").json()

        assert cuerpo["count"] == 2
        assert cuerpo["results"][0]["row_number"] == 1

    def test_filtra_las_filas_por_estado(self, client: APIClient) -> None:
        mala = ",,,,\n"
        lote = importar(client, csv_archivo(CABECERA + FILA_ANA + mala))

        con_error = client.get(
            f"{LOTES}{lote['import_batch_id']}/rows/", {"status": "ERROR"}
        ).json()
        assert con_error["count"] == 1

    def test_reporte_csv(self, client: APIClient) -> None:
        mala = "10 00 01,Eva,Nieto,Melanoma,\n"
        lote = importar(client, csv_archivo(CABECERA + FILA_ANA + mala))

        respuesta = client.get(f"{LOTES}{lote['import_batch_id']}/report/")
        assert respuesta.status_code == 200
        assert respuesta["Content-Type"] == "text/csv"

        lineas = b"".join(respuesta.streaming_content).decode().strip().splitlines()
        assert lineas[0].startswith("row_number,identification_number")
        assert len(lineas) == 3
        assert "ERROR" in lineas[2]

    def test_el_reporte_permite_saber_el_motivo_de_cada_error(
        self, client: APIClient
    ) -> None:
        mala = "1000000003,Eva,Nieto,Melanoma,no-es-fecha\n"
        lote = importar(client, csv_archivo(CABECERA + mala))

        contenido = b"".join(
            client.get(f"{LOTES}{lote['import_batch_id']}/report/").streaming_content
        ).decode()
        assert "Formato de fecha incorrecto" in contenido

    def test_un_anonimo_no_puede_consultar(self, client: APIClient) -> None:
        lote = importar(client, csv_archivo(CABECERA + FILA_ANA))
        assert (
            APIClient().get(f"{LOTES}{lote['import_batch_id']}/report/").status_code
            == 401
        )


class TestTareaCelery:
    def test_tolera_un_lote_inexistente(self) -> None:
        assert tasks.process_import_batch(999999, []) == {
            "total": 0,
            "success": 0,
            "failure": 0,
        }

    def test_marca_el_lote_fallido_ante_un_error_global(
        self, client: APIClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        lote = ImportBatch.objects.create(
            source_file_name="x.csv", source_file_type=".csv", total_rows=0
        )

        def explota(*args: object, **kwargs: object) -> None:
            raise RuntimeError("fallo global")

        monkeypatch.setattr(ImportService, "process", explota)

        with pytest.raises(RuntimeError):
            tasks.process_import_batch(lote.pk, [])

        lote.refresh_from_db()
        assert lote.status == ImportBatchStatus.FAILED

    def test_esta_registrada_para_el_worker(self) -> None:
        from config import celery_app

        celery_app.loader.import_default_modules()
        assert "apps.massive_load.tasks.process_import_batch" in celery_app.tasks


class TestAuditoria:
    def test_los_pacientes_creados_se_atribuyen_a_quien_importo(
        self, client: APIClient, clinico: User
    ) -> None:
        """C-04: `acting_as` propaga el usuario hasta la tarea."""
        importar(client, csv_archivo(CABECERA + FILA_ANA))

        paciente = Patient.objects.get(identification_number="1000000001")
        registro = AuditLog.objects.get(
            entity_type="patient", entity_id=paciente.pk, action="CREATE"
        )
        assert registro.user_id == clinico.pk
        assert paciente.created_by_id == clinico.pk

    def test_el_lote_queda_auditado(self, client: APIClient) -> None:
        lote = importar(client, csv_archivo(CABECERA + FILA_ANA))

        assert AuditLog.objects.filter(
            entity_type="import_batch",
            entity_id=lote["import_batch_id"],
            action="CREATE",
        ).exists()


class TestFechasDesdeXlsx:
    """openpyxl devuelve objetos `datetime`, no cadenas.

    Es el caso real de una importacion XLSX con una columna de fecha, y no lo
    cubren los tests de CSV.
    """

    def test_acepta_un_datetime_de_excel(self, client: APIClient) -> None:
        archivo = xlsx_archivo(
            [
                [
                    "identification_number",
                    "first_name",
                    "last_name",
                    "pathology",
                    "date_of_birth",
                ],
                [
                    "1000000001",
                    "Ana",
                    "Gomez",
                    "Carcinoma ductal",
                    datetime(1980, 5, 14),
                ],
            ]
        )
        importar(client, archivo)

        paciente = Patient.objects.get(identification_number="1000000001")
        assert paciente.date_of_birth == date(1980, 5, 14)

    def test_el_parser_normaliza_las_celdas_de_fecha_a_iso(self) -> None:
        from apps.massive_load.parsers import _limpiar

        # `str()` daria "1980-05-14 00:00:00", que ninguna mascara admite.
        assert _limpiar(datetime(1980, 5, 14, 10, 30)) == "1980-05-14"
        assert _limpiar(date(1980, 5, 14)) == "1980-05-14"


class TestLimites:
    def test_el_csv_tiene_tope_de_filas(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Un archivo enorme no debe agotar la memoria del worker.
        monkeypatch.setattr("apps.massive_load.parsers.MAX_FILAS", 2)
        crudo = CABECERA + FILA_ANA + FILA_LUIS + FILA_ANA

        with pytest.raises(ImportParseError) as exc:
            parse_csv(crudo.encode())
        assert "maximo" in str(exc.value)

    def test_el_xlsx_tiene_tope_de_filas(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("apps.massive_load.parsers.MAX_FILAS", 1)
        archivo = xlsx_archivo(
            [
                ["identification_number", "first_name", "last_name", "pathology"],
                ["1", "Ana", "Gomez", "X"],
                ["2", "Luis", "Perez", "Y"],
            ]
        )
        with pytest.raises(ImportParseError):
            parse_xlsx(archivo.read())

    def test_un_xlsx_sin_ninguna_fila_falla(self) -> None:
        archivo = xlsx_archivo([])
        with pytest.raises(ImportParseError):
            parse_xlsx(archivo.read())


class TestErroresDeBaseDeDatos:
    def test_un_fallo_de_base_marca_la_fila_sin_tumbar_el_lote(
        self, client: APIClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from django.db import DatabaseError

        original = ImportService._attach_pathology
        llamadas = {"n": 0}

        def a_veces_falla(paciente, datos):
            llamadas["n"] += 1
            if llamadas["n"] == 1:
                raise DatabaseError("deadlock")
            return original(paciente, datos)

        monkeypatch.setattr(
            ImportService, "_attach_pathology", staticmethod(a_veces_falla)
        )

        lote = importar(client, csv_archivo(CABECERA + FILA_ANA + FILA_LUIS))

        registro = ImportBatch.objects.get(pk=lote["import_batch_id"])
        assert registro.failure_count == 1
        assert registro.success_count == 1
        assert "deadlock" in ImportBatchRow.objects.get(row_number=1).error_message


class TestCasosDefensivos:
    def test_una_celda_vacia_se_normaliza_a_nulo(self) -> None:
        from apps.massive_load.parsers import _limpiar

        assert _limpiar(None) is None
        assert _limpiar("   ") is None

    def test_una_fila_sin_registro_persistido_se_omite(self, client: APIClient) -> None:
        """Defensa por si `filas` y `IMPORT_BATCH_ROW` se desincronizaran."""
        lote = ImportBatch.objects.create(
            source_file_name="x.csv", source_file_type=".csv", total_rows=0
        )
        filas = [
            {
                "identification_number": "1000000009",
                "first_name": "Ana",
                "last_name": "Gomez",
                "pathology": "Melanoma",
            }
        ]

        # El lote no tiene ninguna fila persistida: no debe reventar.
        resultado = ImportService().process(lote, filas)

        assert resultado.success_count == 0
        assert resultado.failure_count == 0
