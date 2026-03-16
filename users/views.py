import re
import unicodedata
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404
from rest_framework.views import APIView
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend

from notifications.service import bulk_notify, render_notification
from notifications.models import Notification
from machines.serializers import SimpleUserSerializer
from users.filters import UserFilter, WageOrderingFilter
from users.helpers import _team_manager_user_ids
from users.models import UserProfile, WageRate
from users.permissions import IsAdmin, IsHRorAuthorized, user_has_role_perm, _legacy_team_check
from users.apps import CUSTOM_PERMISSIONS
from users.constants import GROUP_DISPLAY_NAMES
from .serializers import AdminUserUpdateSerializer, CurrentUserUpdateSerializer, PasswordResetSerializer, PublicUserSerializer, UserCreateSerializer, UserListSerializer, UserPasswordResetSerializer, UserWageOverviewSerializer, WageRateSerializer, WageRateSlimSerializer
from rest_framework.permissions import IsAuthenticated, IsAdminUser
from rest_framework.viewsets import ModelViewSet

from django.db.models import Count
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.filters import OrderingFilter
from rest_framework import permissions, throttling
from django.contrib.auth.password_validation import validate_password
from django.utils import timezone
from rest_framework import generics
from django.db.models import Q, Max, OuterRef, Subquery, Case, When, BooleanField
from rest_framework.generics import ListCreateAPIView, RetrieveUpdateDestroyAPIView, ListAPIView

class UserViewSet(ModelViewSet):
    queryset = User.objects.all().select_related('profile').order_by('username')
    serializer_class = UserListSerializer
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_class = UserFilter

    ordering_fields = [
        'username', 'first_name', 'last_name', 'email',
        'profile__team', 'profile__work_location', 'profile__occupation', 'profile__must_reset_password',
    ]
    # default ordering if ?ordering=… is not provided
    ordering = ['username']

    def get_queryset(self):
        user = self.request.user
        qs = User.objects.select_related('profile').order_by('username')

        if not user.is_authenticated:
            return qs.filter(is_active=True, profile__work_location='workshop')

        if user.is_staff or user.is_superuser:
            return qs

        return qs.filter(is_active=True, profile__work_location='workshop')


    def get_permissions(self):
        if self.action == 'list':
            return []
        return [IsAdmin()]
    
    def get_serializer_class(self):
        if self.request.query_params.get("for_dropdown") == "true":
            return SimpleUserSerializer
        if self.action == 'create':
            return UserCreateSerializer
        elif self.action in ['update', 'partial_update']:
            return AdminUserUpdateSerializer
        elif self.action == 'list':
            user = self.request.user
            if not user.is_authenticated:
                return PublicUserSerializer
            if user.is_staff or user.is_superuser:
                return UserListSerializer
            return PublicUserSerializer
        return UserListSerializer
    
    @action(detail=False, methods=['get'], url_path='summary')
    def summary(self, request):
        qs = (UserProfile.objects
              .values('work_location')
              .annotate(count=Count('id'))
              .order_by('work_location'))

        # map code -> label
        loc_field = UserProfile._meta.get_field('work_location')
        loc_map = dict(loc_field.choices)

        data = [
            {'work_location': row['work_location'],
             'work_location_label': loc_map.get(row['work_location']),
             'count': row['count']}
            for row in qs
        ]
        return Response(data)


class CurrentUserView(APIView):
    permission_classes = [IsAuthenticated]
    def get(self, request):
        serializer = UserListSerializer(request.user)
        return Response(serializer.data)
    
    def put(self, request):
        user = request.user

        if user.is_staff or user.is_superuser:
            serializer_class = AdminUserUpdateSerializer
        else:
            serializer_class = CurrentUserUpdateSerializer

        serializer = serializer_class(user, data=request.data, partial=True, context={'request': request})
        
        if serializer.is_valid():
            serializer.save()
            return Response({"message": "User updated successfully."})
        
        return Response(serializer.errors, status=400)   

class ForcedPasswordResetView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if not request.user.profile.must_reset_password:
            return Response({"detail": "Password reset not required."}, status=403)

        serializer = PasswordResetSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save(user=request.user)
            return Response({"detail": "Password updated successfully."}, status=200)
        return Response(serializer.errors, status=400)
    
class TeamChoicesView(APIView):
    def get(self, request):
        return Response([
            {"value": k, "label": v} for k, v in UserProfile.TEAM_CHOICES
        ])
    
class OccupationChoicesView(APIView):
    permission_classes = [IsAuthenticated, IsAdmin]  # Optional

    def get(self, request):
        return Response([
            {"value": k, "label": v} for k, v in UserProfile.OCCUPATION_CHOICES
        ])
    
class AdminBulkCreateUsers(APIView):
    permission_classes = [IsAdminUser]  # Only superusers or staff with is_staff=True

    def post(self, request):
        names = request.data.get("names")
        team = request.data.get("team")

        if not names or not isinstance(names, list):
            return Response({"error": "'names' must be a list of full names."}, status=400)
        if not team or not isinstance(team, str):
            return Response({"error": "'team' must be a string."}, status=400)

        def normalize_name(name):
            normalized = unicodedata.normalize("NFD", name)
            ascii_str = re.sub(r"[\u0300-\u036f]", "", normalized)
            return re.sub(r"[^a-zA-Z0-9]", "", ascii_str).lower()

        created_users = []
        skipped_users = []

        for full_name in names:
            username = normalize_name(full_name)
            if User.objects.filter(username=username).exists():
                skipped_users.append(username)
                continue

            serializer = UserCreateSerializer(data={"username": username, "team": team})
            if serializer.is_valid():
                serializer.save()
            created_users.append(username)

        return Response({
            "created": created_users,
            "skipped": skipped_users,
            "total_created": len(created_users),
            "message": "Users seeded successfully."
        }, status=201)
    

class PasswordResetRequestThrottle(throttling.AnonRateThrottle):
    rate = "10/hour"

class PasswordResetRequestView(APIView):
    permission_classes = [permissions.AllowAny]
    throttle_classes = [PasswordResetRequestThrottle]

    def post(self, request):
        username = (request.data.get("username") or "").strip()
        # Do not leak existence
        try:
            user = User.objects.select_related("profile").get(username=username)
            profile = user.profile
            
            if profile.reset_password_request:
                return Response(
                    {"detail": "If the account exists, the request was recorded."},
                    status=200
                )
            
            profile.reset_password_request = True
            profile.save(update_fields=["reset_password_request"])
            # (Optional) notify admins via email/telegram here

            # build recipient list: superusers + team managers (deduped)
            manager_ids = _team_manager_user_ids(getattr(profile, "team", "") or "")
            recipient_ids = set(
                list(User.objects.filter(is_active=True, is_superuser=True).values_list("id", flat=True))
                + list(User.objects.filter(id__in=manager_ids, is_active=True).values_list("id", flat=True))
            )
            recipients = User.objects.filter(id__in=recipient_ids, is_active=True)

            if recipients.exists():
                requested_at = timezone.localtime().strftime("%d.%m.%Y %H:%M")
                full_name = user.get_full_name() or user.username
                team = getattr(profile, "team", "") or "—"
                ctx = {
                    'username':     user.username,
                    'full_name':    full_name,
                    'team':         team,
                    'requested_at': requested_at,
                }
                title, body, link = render_notification(Notification.PASSWORD_RESET, ctx)
                try:
                    bulk_notify(
                        users=recipients,
                        notification_type=Notification.PASSWORD_RESET,
                        title=title,
                        body=body,
                        source_type='user',
                        source_id=user.id,
                    )
                except Exception:
                    pass
        except User.DoesNotExist:
            pass
        return Response({"detail": "If the account exists, the request was recorded."}, status=200)
    
class AdminListResetRequestsView(generics.ListAPIView):
    permission_classes = [permissions.IsAdminUser]
    serializer_class = UserPasswordResetSerializer  # or a lightweight serializer
    def get_queryset(self):
        return User.objects.filter(profile__reset_password_request=True).select_related("profile")
    

class AdminResetPasswordView(APIView):
    permission_classes = [permissions.IsAdminUser]

    def post(self, request, user_id):
        temp_password = request.data.get("temp_password")  # or generate
        if not temp_password:
            from secrets import token_urlsafe
            temp_password = token_urlsafe(8)

        try:
            validate_password(temp_password)  # enforces validators
        except ValidationError as e:
            return Response({"detail": e.messages}, status=400)

        user = get_object_or_404(User.objects.select_related("profile"), pk=user_id)
        user.set_password(temp_password)
        user.save(update_fields=["password"])

        profile = user.profile
        profile.must_reset_password = True
        profile.reset_password_request = False
        profile.save(update_fields=["must_reset_password", "reset_password_request"])

        # (Optional) email/telegram temp password to user; or return it once:
        return Response({"temp_password": temp_password, "detail": "Temporary password set; user must change it on next login."}, status=200)
    

class WageRateListCreateView(ListCreateAPIView):
    permission_classes = [IsAuthenticated, IsHRorAuthorized]
    filter_backends = [WageOrderingFilter]  # <— built-in ordering, dynamic fields
    ordering_fields = ['effective_from', 'created_at', 'id']  # allowed fields
    ordering = ['-effective_from', '-id']  # default if ?ordering= not provided

    def get_serializer_class(self):
        mode = (self.request.query_params.get("mode") or "overview").lower()
        return WageRateSerializer if mode == "records" and self.request.method == "GET" else (
            WageRateSerializer if self.request.method == "POST" else UserWageOverviewSerializer
        )

    def get_queryset(self):
        mode = (self.request.query_params.get("mode") or "overview").lower()

        if self.request.method == "POST":
            return WageRate.objects.none()

        # overview mode: users with annotated current wage
        today = timezone.localdate()
        latest = (
            WageRate.objects
            .filter(user=OuterRef("pk"), effective_from__lte=today)
            .order_by("-effective_from")
        )

        qs = (
            User.objects.select_related("profile")
            .annotate(
                current_wage_id=Subquery(latest.values("id")[:1]),
                current_effective_from=Subquery(latest.values("effective_from")[:1]),
                current_currency=Subquery(latest.values("currency")[:1]),
                current_base_monthly=Subquery(latest.values("base_monthly")[:1]),
                current_after_hours_multiplier=Subquery(latest.values("after_hours_multiplier")[:1]),
                current_sunday_multiplier=Subquery(latest.values("sunday_multiplier")[:1]),
                has_wage=Case(When(current_wage_id__isnull=False, then=True), default=False, output_field=BooleanField()),
            )
        )

        # active filter (default: true)
        active_param = self.request.query_params.get("active", "true").lower()
        if active_param in ("true", "1", "yes"):
            qs = qs.filter(is_active=True)
        elif active_param in ("false", "0", "no"):
            qs = qs.filter(is_active=False)

        # optional filters
        team = (self.request.query_params.get("team") or "").strip()
        if team:
            qs = qs.filter(profile__team=team)

        search = (self.request.query_params.get("search") or "").strip()
        if search:
            qs = qs.filter(
                Q(username__icontains=search) |
                Q(first_name__icontains=search) |
                Q(last_name__icontains=search)
            )

        work_location = (self.request.query_params.get("work_location") or "").lower()
        if work_location in {"office", "workshop"}:
            qs = qs.filter(profile__work_location=work_location)

        return qs


class WageRateDetailView(RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated, IsHRorAuthorized]
    serializer_class = WageRateSerializer
    queryset = WageRate.objects.select_related("user", "user__profile").all()

    def perform_update(self, serializer):
        serializer.save(updated_by=self.request.user)


class UserWageRateListView(ListAPIView):
    """
    GET /users/<user_id>/wages/
    Query params:
      - as_of=YYYY-MM-DD    (default: today)
      - current=true        (only latest as of date)
      - include_future=true|false  (default: true)
      - ordering=...        (uses WageOrderingFilter)
    """
    permission_classes = [IsAuthenticated, IsHRorAuthorized]
    serializer_class = WageRateSlimSerializer

    def get_queryset(self):
        user_obj = get_object_or_404(User, pk=self.kwargs["user_id"])
        qs = WageRate.objects.select_related("user", "user__profile").filter(user=user_obj)

        # as_of date
        as_of_param = (self.request.query_params.get("as_of") or "").strip()
        if as_of_param:
            try:
                as_of_date = timezone.datetime.strptime(as_of_param, "%Y-%m-%d").date()
            except ValueError:
                as_of_date = timezone.localdate()
        else:
            as_of_date = timezone.localdate()

        # include_future
        include_future = (self.request.query_params.get("include_future") or "true").lower() == "true"
        if not include_future:
            qs = qs.filter(effective_from__lte=as_of_date)

        # current=true → only the latest as of date
        if (self.request.query_params.get("current") or "").lower() == "true":
            latest = (
                WageRate.objects
                .filter(user=user_obj, effective_from__lte=as_of_date)
                .order_by("-effective_from")
            )
            qs = qs.filter(id__in=Subquery(latest.values("id")[:1]))

        return qs


# ---------------------------------------------------------------------------
# Permission discovery endpoint
# ---------------------------------------------------------------------------

_PERMISSION_CODENAMES = [codename for codename, _ in CUSTOM_PERMISSIONS]


class UserPermissionsView(APIView):
    """
    GET /users/me/permissions/

    Returns a flat dict of {codename: bool} for every custom permission
    codename. The frontend uses this to show/hide pages and actions.

    Django caches all permissions after the first has_perm() call, so the
    entire dict is resolved in a single DB query per request.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        if user.is_superuser:
            return Response({c: True for c in _PERMISSION_CODENAMES})
        return Response({c: user_has_role_perm(user, c) for c in _PERMISSION_CODENAMES})


class GroupListView(APIView):
    """
    GET /users/groups/

    Returns all role groups with their Turkish display names and member counts.
    Useful for frontend filters, dropdowns, and mention pickers.

    Response:
      [
        {"name": "planning_team", "display_name": "Planlama Ekibi", "member_count": 5},
        ...
      ]
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from django.contrib.auth.models import Group
        groups = (
            Group.objects
            .filter(name__in=GROUP_DISPLAY_NAMES)
            .prefetch_related('user_set')
            .order_by('name')
        )
        data = [
            {
                'name': g.name,
                'display_name': GROUP_DISPLAY_NAMES[g.name],
                'member_count': g.user_set.count(),
            }
            for g in groups
        ]
        return Response(data)


# ---------------------------------------------------------------------------
# Centralized permissions management API
# ---------------------------------------------------------------------------

class UserPermissionDetailView(APIView):
    """
    GET /users/<user_id>/permissions/

    Returns the complete permission state for a single user:
      - groups they belong to (name + Turkish display name)
      - per-codename effective permission (bool) resolved via user_has_role_perm
      - explicit UserPermissionOverride records for this user

    Only accessible by admins / superusers.
    """
    permission_classes = [IsAuthenticated, IsAdmin]

    def get(self, request, user_id):
        from django.contrib.auth.models import Group

        target = get_object_or_404(
            User.objects.select_related('profile').prefetch_related('groups', 'permissions', 'permission_overrides'),
            pk=user_id,
        )

        # Groups
        group_names = sorted(g.name for g in target.groups.all())
        groups_data = [
            {'name': g, 'display_name': GROUP_DISPLAY_NAMES.get(g, g)}
            for g in group_names
        ]

        # Build group→perms map for this user's groups only
        group_perms_detail: dict[str, set[str]] = {}
        for g in (
            Group.objects.filter(name__in=group_names).prefetch_related('permissions')
        ):
            group_perms_detail[g.name] = {p.codename for p in g.permissions.all()}

        overrides_map = {o.codename: o for o in target.permission_overrides.all()}
        codename_set = set(_PERMISSION_CODENAMES)
        prof = getattr(target, 'profile', None)

        effective = {}
        for c in _PERMISSION_CODENAMES:
            if target.is_superuser:
                effective[c] = {'value': True, 'source': 'superuser', 'source_detail': ''}
            elif c in overrides_map:
                o = overrides_map[c]
                src = 'override_grant' if o.granted else 'override_deny'
                effective[c] = {'value': o.granted, 'source': src, 'source_detail': o.reason}
            else:
                granting_groups = [
                    gn for gn, codes in group_perms_detail.items() if c in codes
                ]
                if granting_groups:
                    effective[c] = {
                        'value': True,
                        'source': 'group',
                        'source_detail': ', '.join(sorted(granting_groups)),
                    }
                elif prof and _legacy_team_check(target, c):
                    effective[c] = {'value': True, 'source': 'legacy', 'source_detail': f'team={prof.team}'}
                else:
                    effective[c] = {'value': False, 'source': 'none', 'source_detail': ''}

        overrides_data = [
            {
                'codename': o.codename,
                'granted': o.granted,
                'reason': o.reason,
                'created_at': o.created_at,
                'created_by': o.created_by_id,
            }
            for o in overrides_map.values()
        ]

        return Response({
            'user': {
                'id': target.pk,
                'username': target.username,
                'full_name': target.get_full_name(),
                'is_superuser': target.is_superuser,
            },
            'groups': groups_data,
            'effective_permissions': effective,
            'overrides': overrides_data,
        })


class UserGroupMembershipView(APIView):
    """
    POST   /users/<user_id>/groups/<group_name>/  → add user to group
    DELETE /users/<user_id>/groups/<group_name>/  → remove user from group

    Only accessible by admins / superusers.
    """
    permission_classes = [IsAuthenticated, IsAdmin]

    def post(self, request, user_id, group_name):
        from django.contrib.auth.models import Group

        if group_name not in GROUP_DISPLAY_NAMES:
            return Response({'detail': 'Unknown group.'}, status=400)

        target = get_object_or_404(User, pk=user_id)
        group = get_object_or_404(Group, name=group_name)
        target.groups.add(group)
        return Response({'detail': f'User added to {GROUP_DISPLAY_NAMES[group_name]}.'})

    def delete(self, request, user_id, group_name):
        from django.contrib.auth.models import Group

        if group_name not in GROUP_DISPLAY_NAMES:
            return Response({'detail': 'Unknown group.'}, status=400)

        target = get_object_or_404(User, pk=user_id)
        group = get_object_or_404(Group, name=group_name)
        target.groups.remove(group)
        return Response({'detail': f'User removed from {GROUP_DISPLAY_NAMES[group_name]}.'})


class UserPermissionOverrideView(APIView):
    """
    POST   /users/<user_id>/permission-overrides/
      Body: {"codename": "...", "granted": true/false, "reason": "..."}
      Creates or updates a UserPermissionOverride for this user.

    DELETE /users/<user_id>/permission-overrides/<codename>/
      Removes the override (reverts to group-based resolution).

    Only accessible by admins / superusers.
    """
    permission_classes = [IsAuthenticated, IsAdmin]

    def post(self, request, user_id):
        from users.models import UserPermissionOverride

        target = get_object_or_404(User, pk=user_id)
        codename = (request.data.get('codename') or '').strip()
        granted = request.data.get('granted')
        reason = (request.data.get('reason') or '').strip()

        if codename not in _PERMISSION_CODENAMES:
            return Response({'detail': f'Unknown codename: {codename}'}, status=400)
        if granted is None:
            return Response({'detail': '"granted" (true/false) is required.'}, status=400)

        override, created = UserPermissionOverride.objects.update_or_create(
            user=target,
            codename=codename,
            defaults={
                'granted': bool(granted),
                'reason': reason,
                'created_by': request.user,
            },
        )
        action_word = 'Created' if created else 'Updated'
        return Response({
            'detail': f'{action_word} override.',
            'codename': override.codename,
            'granted': override.granted,
            'reason': override.reason,
        }, status=201 if created else 200)

    def delete(self, request, user_id, codename):
        from users.models import UserPermissionOverride

        target = get_object_or_404(User, pk=user_id)
        deleted, _ = UserPermissionOverride.objects.filter(user=target, codename=codename).delete()
        if deleted:
            return Response({'detail': 'Override removed.'})
        return Response({'detail': 'No override found for this codename.'}, status=404)


class UserPermissionsMatrixView(APIView):
    """
    GET /users/permissions/matrix/

    Returns a compact matrix of all active office users × all permission codenames.
    Useful for the ERP-style access management table.

    Response:
      {
        "codenames": ["access_machining", ...],
        "users": [
          {
            "id": 1,
            "username": "ahmet",
            "full_name": "Ahmet Yılmaz",
            "groups": ["planning_team"],
            "permissions": {"access_machining": false, "access_planning_write": true, ...}
          },
          ...
        ]
      }

    Query params:
      - active=true/false  (default: true)
      - search=<str>       (username / first / last name)
      - group=<group_name> (filter to users in a specific group)
    """
    permission_classes = [IsAuthenticated, IsAdmin]

    def get(self, request):
        from django.contrib.auth.models import Group, Permission

        qs = (
            User.objects
            .select_related('profile')
            .prefetch_related('groups', 'permission_overrides')
            .order_by('username')
        )

        # Filters
        active_param = request.query_params.get('active', 'true').lower()
        if active_param in ('true', '1', 'yes'):
            qs = qs.filter(is_active=True)
        elif active_param in ('false', '0', 'no'):
            qs = qs.filter(is_active=False)

        search = (request.query_params.get('search') or '').strip()
        if search:
            qs = qs.filter(
                Q(username__icontains=search) |
                Q(first_name__icontains=search) |
                Q(last_name__icontains=search)
            )

        group_filter = (request.query_params.get('group') or '').strip()
        if group_filter:
            qs = qs.filter(groups__name=group_filter)

        # Build group_name → set(codenames) map in ONE query upfront.
        # This avoids triggering has_perm() (which hits DB per user) in the loop.
        group_perms: dict[str, set[str]] = {}
        for gp in (
            Group.objects
            .filter(name__in=GROUP_DISPLAY_NAMES)
            .prefetch_related('permissions')
        ):
            group_perms[gp.name] = {p.codename for p in gp.permissions.all()}

        codename_set = set(_PERMISSION_CODENAMES)

        def _resolve(u) -> dict:
            if u.is_superuser:
                return {c: {'value': True, 'source': 'superuser', 'source_detail': ''} for c in _PERMISSION_CODENAMES}

            overrides = {o.codename: o for o in u.permission_overrides.all()}

            # group_name → codenames granted by that group
            granted_by_group: dict[str, set[str]] = {}
            for g in u.groups.all():
                for c in group_perms.get(g.name, set()) & codename_set:
                    granted_by_group.setdefault(c, set()).add(g.name)

            result = {}
            prof = getattr(u, 'profile', None)
            for c in _PERMISSION_CODENAMES:
                if c in overrides:
                    o = overrides[c]
                    src = 'override_grant' if o.granted else 'override_deny'
                    result[c] = {'value': o.granted, 'source': src, 'source_detail': o.reason}
                elif c in granted_by_group:
                    groups_str = ', '.join(sorted(granted_by_group[c]))
                    result[c] = {'value': True, 'source': 'group', 'source_detail': groups_str}
                elif prof and _legacy_team_check(u, c):
                    result[c] = {'value': True, 'source': 'legacy', 'source_detail': f'team={prof.team}'}
                else:
                    result[c] = {'value': False, 'source': 'none', 'source_detail': ''}
            return result

        users_data = []
        for u in qs:
            group_names = [g.name for g in u.groups.all() if g.name in GROUP_DISPLAY_NAMES]
            users_data.append({
                'id': u.pk,
                'username': u.username,
                'full_name': u.get_full_name(),
                'is_superuser': u.is_superuser,
                'groups': group_names,
                'permissions': _resolve(u),
            })

        return Response({
            'codenames': _PERMISSION_CODENAMES,
            'users': users_data,
        })