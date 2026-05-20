from django.apps import AppConfig


class BugReportsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'bug_reports'

    def ready(self):
        import sys
        # Skip DB access during migrate/makemigrations commands
        if any(cmd in sys.argv for cmd in ('migrate', 'makemigrations', 'sqlmigrate', 'showmigrations')):
            return
        # Reset any reports that got stuck in_progress from a previous crashed run
        try:
            from .models import BugReport
            stuck = BugReport.objects.filter(status=BugReport.STATUS_IN_PROGRESS)
            count = stuck.update(status=BugReport.STATUS_OPEN)
            if count:
                import logging
                logging.getLogger(__name__).warning(
                    'Reset %d stuck in_progress bug report(s) on startup', count
                )
        except Exception:
            pass
