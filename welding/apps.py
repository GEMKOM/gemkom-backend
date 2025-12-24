from django.apps import AppConfig


class WeldingConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'welding'

    def ready(self):
        import welding.signals  # noqa
