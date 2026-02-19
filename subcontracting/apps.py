from django.apps import AppConfig


class SubcontractingConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'subcontracting'
    verbose_name = 'Taşeronluk'

    def ready(self):
        import subcontracting.signals  # noqa
