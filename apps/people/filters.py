"""Filtros de busqueda de pacientes.

`age_min` y `age_max` se traducen a rangos sobre `date_of_birth`: la edad se
deriva en la consulta, sin anadir ninguna columna al DER.
"""

from __future__ import annotations

from datetime import date

import django_filters
from django.db.models import Q, QuerySet

from apps.people.models import Patient


def restar_anios(fecha: date, anios: int) -> date:
    """Resta anos a una fecha, contemplando el 29 de febrero."""
    try:
        return fecha.replace(year=fecha.year - anios)
    except ValueError:
        return fecha.replace(year=fecha.year - anios, day=28)


class PatientFilterSet(django_filters.FilterSet):
    search = django_filters.CharFilter(
        method="filtrar_por_nombre",
        label="Busca en nombres y apellidos",
    )
    identification_number = django_filters.CharFilter(lookup_expr="exact")
    age_min = django_filters.NumberFilter(method="filtrar_edad_minima")
    age_max = django_filters.NumberFilter(method="filtrar_edad_maxima")
    primary_pathology = django_filters.NumberFilter(
        method="filtrar_patologia_principal"
    )

    class Meta:
        model = Patient
        fields = ["is_active"]

    def filtrar_por_nombre(
        self, queryset: QuerySet[Patient], name: str, value: str
    ) -> QuerySet[Patient]:
        """Busca el termino en el nombre o en el apellido, sin distinguir mayusculas.

        No hace falta descartar aqui los valores en blanco: el `CharField` de
        django-filter ya aplica `strip` y omite el filtro si queda vacio.
        """
        termino = value.strip()
        return queryset.filter(
            Q(first_name__icontains=termino) | Q(last_name__icontains=termino)
        )

    def filtrar_edad_minima(
        self, queryset: QuerySet[Patient], name: str, value: int
    ) -> QuerySet[Patient]:
        """Tiene al menos N anos: nacio como muy tarde hace N anos."""
        return queryset.filter(
            date_of_birth__lte=restar_anios(date.today(), int(value))
        )

    def filtrar_edad_maxima(
        self, queryset: QuerySet[Patient], name: str, value: int
    ) -> QuerySet[Patient]:
        """Tiene como mucho N anos: aun no ha cumplido N+1.

        La comparacion es estricta para que quien cumple N+1 hoy quede fuera.
        """
        return queryset.filter(
            date_of_birth__gt=restar_anios(date.today(), int(value) + 1)
        )

    def filtrar_patologia_principal(
        self, queryset: QuerySet[Patient], name: str, value: int
    ) -> QuerySet[Patient]:
        """Filtra por la patologia marcada como principal en PATIENT_PATHOLOGY."""
        return queryset.filter(
            pathologies__pathology_id=value, pathologies__is_primary=True
        )
