"""Inventario del DER en forma legible por maquina.

Transcripcion de `docs/DER.png`, tabla por tabla. Es la version
ejecutable de docs/DER_ANALYSIS.md seccion 2 y sirve de contrato verificable:
`tests/test_der_contract.py` compara los modelos Django contra este inventario.

Formato de `columns`: {nombre_de_columna_fisica: admite_null}

Las UNICAS desviaciones respecto al diagrama son las dos columnas anadidas a
`user` (`password`, `last_login`), autorizadas en docs/DECISIONS.md seccion 3 y
marcadas abajo como DELTA.
"""

from __future__ import annotations

from typing import TypedDict


class TableSpec(TypedDict):
    model: str
    pk: str
    columns: dict[str, bool]
    unique: list[str]
    unique_together: list[tuple[str, ...]]
    foreign_keys: dict[str, str]


DER: dict[str, TableSpec] = {
    "user": {
        "model": "core.User",
        "pk": "user_id",
        "columns": {
            "user_id": False,
            "username": True,
            "email": True,
            "is_active": False,
            "created_at": False,
            "updated_at": False,
            "password": False,  # DELTA autorizado (C-02)
            "last_login": True,  # DELTA autorizado (C-02)
        },
        "unique": ["username", "email"],
        "unique_together": [],
        "foreign_keys": {},
    },
    "audit_log": {
        "model": "core.AuditLog",
        "pk": "audit_id",
        "columns": {
            "audit_id": False,
            "user_id": False,
            "entity_type": False,
            "entity_id": False,
            "action": True,
            "old_values": True,
            "new_values": True,
            "created_at": False,
        },
        "unique": [],
        "unique_together": [],
        "foreign_keys": {"user_id": "user"},
    },
    "patient": {
        "model": "people.Patient",
        "pk": "patient_id",
        "columns": {
            "patient_id": False,
            "identification_number": True,
            "first_name": False,
            "last_name": False,
            "date_of_birth": True,
            "phone": True,
            "email": True,
            "address": True,
            "is_active": False,
            "created_at": False,
            "updated_at": False,
            "created_by": True,
            "updated_by": True,
        },
        "unique": ["identification_number"],
        "unique_together": [],
        "foreign_keys": {"created_by": "user", "updated_by": "user"},
    },
    "pathology": {
        "model": "people.Pathology",
        "pk": "pathology_id",
        "columns": {
            "pathology_id": False,
            "name": False,
            "description": True,
            "created_at": False,
            "updated_at": False,
            "created_by": True,
            "updated_by": True,
        },
        "unique": ["name"],
        "unique_together": [],
        "foreign_keys": {"created_by": "user", "updated_by": "user"},
    },
    "patient_pathology": {
        "model": "people.PatientPathology",
        "pk": "patient_pathology_id",
        "columns": {
            "patient_pathology_id": False,
            "patient_id": False,
            "pathology_id": False,
            "is_primary": True,
            "diagnosis_date": True,
            "notes": True,
            "created_at": False,
            "updated_at": False,
            "created_by": True,
            "updated_by": True,
        },
        "unique": [],
        # `uq_patient_pathology`, declarada explicitamente en el DER.
        "unique_together": [("patient_id", "pathology_id")],
        "foreign_keys": {
            "patient_id": "patient",
            "pathology_id": "pathology",
            "created_by": "user",
            "updated_by": "user",
        },
    },
    "clinical_history": {
        "model": "people.ClinicalHistory",
        "pk": "clinical_history_id",
        "columns": {
            "clinical_history_id": False,
            "patient_id": False,
            "last_ai_summary": True,
            "last_ai_summary_at": True,
            "created_at": False,
            "updated_at": False,
            "created_by": True,
            "updated_by": True,
        },
        # `bigint UNIQUE NOT NULL`: es lo que fuerza el 1:1 con PATIENT.
        "unique": ["patient_id"],
        "unique_together": [],
        "foreign_keys": {
            "patient_id": "patient",
            "created_by": "user",
            "updated_by": "user",
        },
    },
    "clinical_history_entry": {
        "model": "people.ClinicalHistoryEntry",
        "pk": "clinical_history_entry_id",
        "columns": {
            "clinical_history_entry_id": False,
            "clinical_history_id": False,
            "entry_type": True,
            "entry_date": False,
            "description": False,
            "created_at": False,
            "updated_at": False,
            "created_by": True,
            "updated_by": True,
        },
        "unique": [],
        "unique_together": [],
        "foreign_keys": {
            "clinical_history_id": "clinical_history",
            "created_by": "user",
            "updated_by": "user",
        },
    },
    "note": {
        "model": "people.Note",
        "pk": "note_id",
        "columns": {
            "note_id": False,
            "clinical_history_id": False,
            "text": False,
            "created_at": False,
            "updated_at": False,
            "created_by": True,
            "updated_by": True,
        },
        "unique": [],
        "unique_together": [],
        "foreign_keys": {
            "clinical_history_id": "clinical_history",
            "created_by": "user",
            "updated_by": "user",
        },
    },
    "treatment_plan": {
        "model": "medications.TreatmentPlan",
        "pk": "treatment_plan_id",
        "columns": {
            "treatment_plan_id": False,
            "patient_id": False,
            "pathology_id": True,  # A-05: FK nullable
            "name": False,
            "start_date": False,
            "end_date": True,
            "status": True,
            "clinical_note": True,
            "created_at": False,
            "updated_at": False,
            "created_by": True,
            "updated_by": True,
        },
        "unique": [],
        "unique_together": [],
        "foreign_keys": {
            "patient_id": "patient",
            "pathology_id": "pathology",
            "created_by": "user",
            "updated_by": "user",
        },
    },
    "treatment_plan_medication": {
        "model": "medications.TreatmentPlanMedication",
        "pk": "treatment_plan_medication_id",
        "columns": {
            "treatment_plan_medication_id": False,
            "treatment_plan_id": False,
            "external_medication_id": False,
            "medication_name_snapshot": True,
            "medication_family_snapshot": True,
            "dose": True,
            "frequency": True,
            "duration": True,
            "route": True,
            "instructions": True,
            "validation_status": True,
            "warning_flag": True,
            "created_at": False,
            "updated_at": False,
            "created_by": True,
            "updated_by": True,
        },
        "unique": [],
        "unique_together": [],
        "foreign_keys": {
            "treatment_plan_id": "treatment_plan",
            "created_by": "user",
            "updated_by": "user",
        },
    },
    "appointment": {
        "model": "appointments.Appointment",
        "pk": "appointment_id",
        "columns": {
            "appointment_id": False,
            "patient_id": False,
            "scheduled_at": False,
            "status": True,
            "reason": True,
            "priority": True,
            "priority_suggested_by_ai": True,
            "priority_final": True,
            "created_at": False,
            "updated_at": False,
            "created_by": True,
            "updated_by": True,
        },
        "unique": [],
        "unique_together": [],
        "foreign_keys": {
            "patient_id": "patient",
            "created_by": "user",
            "updated_by": "user",
        },
    },
    "appointment_reminder": {
        "model": "appointments.AppointmentReminder",
        "pk": "reminder_id",
        # D-02: sin created_at/updated_at/created_by/updated_by. El DER no se
        # los define y no se le anaden.
        "columns": {
            "reminder_id": False,
            "appointment_id": False,
            "channel": True,
            "scheduled_at": False,
            "sent_at": True,
            "status": True,
            "failure_reason": True,
        },
        "unique": [],
        "unique_together": [],
        "foreign_keys": {"appointment_id": "appointment"},
    },
    "import_batch": {
        "model": "massive_load.ImportBatch",
        "pk": "import_batch_id",
        "columns": {
            "import_batch_id": False,
            "source_file_name": False,
            "source_file_type": True,
            "processed_at": True,
            "total_rows": True,
            "success_count": True,
            "failure_count": True,
            "status": True,
            "created_at": False,
            "updated_at": False,
            "created_by": True,
            "updated_by": True,
        },
        "unique": [],
        "unique_together": [],
        "foreign_keys": {"created_by": "user", "updated_by": "user"},
    },
    "import_batch_row": {
        "model": "massive_load.ImportBatchRow",
        "pk": "import_batch_row_id",
        # D-04: el DER NO define FK al PATIENT creado o encontrado.
        "columns": {
            "import_batch_row_id": False,
            "import_batch_id": False,
            "row_number": False,
            "identification_number": True,
            "patient_name_snapshot": True,
            "pathology_name_snapshot": True,
            "status": True,
            "error_message": True,
            "created_at": False,
            "updated_at": False,
            "created_by": True,
            "updated_by": True,
        },
        "unique": [],
        "unique_together": [],
        "foreign_keys": {
            "import_batch_id": "import_batch",
            "created_by": "user",
            "updated_by": "user",
        },
    },
}

# Longitud declarada por el DER para cada columna de texto.
#
#   int   -> el DER escribe `varchar(N)`
#   None  -> el DER escribe `varchar` SIN longitud, o `text`. Se implementa como
#            `TextField` (DEC-01): no se inventa un limite que el contrato no
#            declara.
#
# Las columnas `enum(...)` valen ENUM_MAX_LENGTH: el DER no les da longitud, y
# 30 es el detalle de implementacion de DEC-10 (CharField + CheckConstraint).
ENUM_MAX_LENGTH = 30

COLUMN_MAX_LENGTHS: dict[str, dict[str, int | None]] = {
    "user": {"username": None, "email": None, "password": 128},
    "audit_log": {"entity_type": 100, "action": ENUM_MAX_LENGTH},
    "patient": {
        "identification_number": None,
        "first_name": 100,
        "last_name": 100,
        "phone": 30,
        "email": 255,
        "address": 255,
    },
    "pathology": {"name": 255, "description": None},
    "patient_pathology": {"notes": None},
    "clinical_history": {"last_ai_summary": None},
    "clinical_history_entry": {
        "entry_type": ENUM_MAX_LENGTH,
        "description": None,
    },
    "note": {"text": None},
    "treatment_plan": {
        "name": 255,
        "status": ENUM_MAX_LENGTH,
        "clinical_note": None,
    },
    "treatment_plan_medication": {
        "external_medication_id": 100,
        "medication_name_snapshot": None,
        "medication_family_snapshot": None,
        "dose": 100,
        "frequency": 100,
        "duration": 100,
        "route": 100,
        "instructions": None,
        # varchar(30) explicito en el DER, NO enum.
        "validation_status": 30,
    },
    "appointment": {
        "status": ENUM_MAX_LENGTH,
        "reason": None,
        "priority": ENUM_MAX_LENGTH,
        # varchar(30) explicitos en el DER.
        "priority_suggested_by_ai": 30,
        "priority_final": 30,
    },
    "appointment_reminder": {
        "channel": ENUM_MAX_LENGTH,
        "status": ENUM_MAX_LENGTH,
        "failure_reason": None,
    },
    "import_batch": {
        "source_file_name": 255,
        "source_file_type": 50,
        "status": ENUM_MAX_LENGTH,
    },
    "import_batch_row": {
        "identification_number": 50,
        "patient_name_snapshot": 255,
        "pathology_name_snapshot": 255,
        "status": ENUM_MAX_LENGTH,
        "error_message": None,
    },
}


# Tablas a las que el DER SI dota de los cuatro campos de auditoria.
TABLES_WITH_AUDITOR = {
    "patient",
    "pathology",
    "patient_pathology",
    "clinical_history",
    "clinical_history_entry",
    "note",
    "treatment_plan",
    "treatment_plan_medication",
    "appointment",
    "import_batch",
    "import_batch_row",
}

# Tablas que NO llevan campos de auditoria (D-02).
TABLES_WITHOUT_AUDITOR = {"user", "audit_log", "appointment_reminder"}
