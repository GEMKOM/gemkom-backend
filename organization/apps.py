from django.apps import AppConfig


class OrganizationConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'organization'
    verbose_name = 'Organizasyon'

    def ready(self):
        import organization.signals  # noqa: F401
