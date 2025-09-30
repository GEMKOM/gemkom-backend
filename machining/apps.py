from django.apps import AppConfig


class MachiningConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "machining"

    def ready(self):
        from . import signals  # noqa: F401
