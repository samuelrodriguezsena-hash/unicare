from __future__ import annotations

from django.apps import AppConfig


class PeopleConfig(AppConfig):
    name = "apps.people"
    label = "people"
    verbose_name = "People"
