from django.conf import settings
from django.db import models


class Position(models.Model):
    """
    A node in the org tree. Represents a role/title, not a person.
    Multiple users can hold the same position (e.g. two Proje Sorumlusu).
    A position with no active holders is a vacant seat — skipped during
    approval chain traversal.
    """
    title           = models.CharField(max_length=150)
    level           = models.PositiveSmallIntegerField(
        help_text="Authority level. Lower = more authority. 1=board, 2=GM, 3=dept-director, 4=manager/chief, 5=specialist, 6=staff."
    )
    parent          = models.ForeignKey(
        'self',
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='direct_reports',
        help_text="The position this one reports to.",
    )
    department_code = models.SlugField(
        max_length=50, blank=True, default='',
        help_text="Logical department grouping slug (e.g. 'machining', 'human_resources'). No FK — just a tag.",
    )
    permissions     = models.ManyToManyField(
        'users.PermissionMeta',
        blank=True,
        related_name='positions',
    )
    is_active       = models.BooleanField(default=True)

    class Meta:
        ordering = ['level', 'department_code', 'title']
        verbose_name = 'Pozisyon'
        verbose_name_plural = 'Pozisyonlar'

    def __str__(self):
        dept = self.department_code or '—'
        return f"[L{self.level}] {self.title} ({dept})"

    def ancestors(self):
        """All ancestors from direct parent to root, ordered nearest-first."""
        result, pos = [], self
        while pos.parent_id:
            pos = pos.parent
            result.append(pos)
        return result


class UserGroup(models.Model):
    """
    A named group whose membership is derived from positions.
    Anyone holding one of the linked positions is automatically a member.
    Used for notification routing and @mentions in comments.
    """
    name        = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    positions   = models.ManyToManyField(
        'organization.Position',
        blank=True,
        related_name='user_groups',
    )
    is_active   = models.BooleanField(default=True)
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']
        verbose_name = 'Kullanıcı Grubu'
        verbose_name_plural = 'Kullanıcı Grupları'

    def __str__(self):
        return self.name

    def get_members(self):
        """Return active users holding any of this group's positions."""
        from django.contrib.auth import get_user_model
        User = get_user_model()
        return User.objects.filter(
            is_active=True,
            profile__position__in=self.positions.filter(is_active=True),
        ).distinct()
