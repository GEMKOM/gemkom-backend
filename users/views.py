import re
import unicodedata
from django.contrib.auth.models import User
from rest_framework_simplejwt.tokens import RefreshToken
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404
from rest_framework.views import APIView
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend

from notifications.service import bulk_notify, render_notification
from notifications.models import Notification
from machines.serializers import SimpleUserSerializer
from users.filters import UserFilter, WageOrderingFilter
from users.models import UserProfile, WageRate
from users.permissions import IsAdmin, IsAdminOrHR, IsHRorAuthorized, user_has_role_perm
from .serializers import (
    AdminUserUpdateSerializer, CurrentUserUpdateSerializer, PasswordResetSerializer,
    PublicUserSerializer, UserCreateSerializer, UserListSerializer,
    UserPasswordResetSerializer, UserWageOverviewSerializer,
    WageRateSerializer, WageRateSlimSerializer,
)
from rest_framework.permissions import IsAuthenticated, IsAdminUser
from rest_framework.viewsets import ModelViewSet
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
    serializer_class = UserListSerializer
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_class = UserFilter
    ordering_fields = [
        'username', 'first_name', 'last_name', 'email', 'profile__must_reset_password',
        'profile__position__title', 'profile__position__level', 'profile__position__department_code',
    ]
    ordering = ['username']

    def get_queryset(self):
        user = self.request.user
        qs = User.objects.select_related(
            'profile',
            'profile__position',
            'profile__position__parent',
        ).order_by('username')

        if not user.is_authenticated:
            return qs.none()
        if user.is_staff or user.is_superuser or user_has_role_perm(user, 'office_access'):
            return qs
        if user_has_role_perm(user, 'workshop_access'):
            return qs.filter(is_active=True)
        return qs.none()

    def get_permissions(self):
        if self.action == 'list':
            return []
        if self.action in ('create', 'update', 'partial_update'):
            return [IsAdminOrHR()]
        return [IsAdmin()]

    def get_serializer_class(self):
        if self.request.query_params.get("for_dropdown") == "true":
            return SimpleUserSerializer
        if self.action == 'create':
            return UserCreateSerializer
        if self.action in ['update', 'partial_update']:
            return AdminUserUpdateSerializer
        if self.action == 'list':
            user = self.request.user
            if not user.is_authenticated:
                return PublicUserSerializer
            if user_has_role_perm(user, 'office_access') or user.is_staff or user.is_superuser:
                return UserListSerializer
            return PublicUserSerializer
        return UserListSerializer

    @action(detail=False, methods=['get'], url_path='summary')
    def summary(self, request):
        total = User.objects.filter(is_active=True).count()
        office_count = User.objects.filter(
            is_active=True,
            user_permissions__codename='office_access',
        ).distinct().count()
        workshop_count = User.objects.filter(
            is_active=True,
            user_permissions__codename='workshop_access',
        ).distinct().count()
        return Response({'total': total, 'office': office_count, 'workshop': workshop_count})


class CurrentUserView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = User.objects.select_related(
            'profile', 'profile__position',
        ).get(pk=request.user.pk)
        return Response(UserListSerializer(user).data)

    def put(self, request):
        user = request.user
        serializer_class = AdminUserUpdateSerializer if (user.is_staff or user.is_superuser) else CurrentUserUpdateSerializer
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


class AdminBulkCreateUsers(APIView):
    permission_classes = [IsAdminUser]

    def post(self, request):
        names = request.data.get("names")
        position_id = request.data.get("position")

        if not names or not isinstance(names, list):
            return Response({"error": "'names' must be a list of full names."}, status=400)

        def normalize_name(name):
            normalized = unicodedata.normalize("NFD", name)
            ascii_str = re.sub(r"[̀-ͯ]", "", normalized)
            return re.sub(r"[^a-zA-Z0-9]", "", ascii_str).lower()

        created_users, skipped_users = [], []

        for full_name in names:
            username = normalize_name(full_name)
            if User.objects.filter(username=username).exists():
                skipped_users.append(username)
                continue
            payload = {"username": username}
            if position_id:
                payload["position"] = position_id
            serializer = UserCreateSerializer(data=payload)
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
        try:
            user = User.objects.select_related(
                "profile", "profile__position",
            ).get(username=username)
            profile = user.profile

            if profile.reset_password_request:
                return Response({"detail": "If the account exists, the request was recorded."}, status=200)

            profile.reset_password_request = True
            profile.save(update_fields=["reset_password_request"])

            # Notify superusers + the user's manager (walk 1 level up the chain)
            recipient_ids = set(
                User.objects.filter(is_active=True, is_superuser=True).values_list("id", flat=True)
            )
            if profile.position_id:
                from organization.services import resolve_chain_approvers
                chain_ids = resolve_chain_approvers(profile.position, climb=1)
                recipient_ids.update(chain_ids)

            recipients = User.objects.filter(id__in=recipient_ids, is_active=True)
            if recipients.exists():
                requested_at = timezone.localtime().strftime("%d.%m.%Y %H:%M")
                full_name = user.get_full_name() or user.username
                ctx = {
                    'username': user.username,
                    'full_name': full_name,
                    'requested_at': requested_at,
                }
                title, body, link = render_notification(Notification.PASSWORD_RESET, ctx)
                try:
                    bulk_notify(
                        users=recipients,
                        notification_type=Notification.PASSWORD_RESET,
                        title=title, body=body,
                        source_type='user', source_id=user.id,
                    )
                except Exception:
                    pass
        except User.DoesNotExist:
            pass
        return Response({"detail": "If the account exists, the request was recorded."}, status=200)


class AdminListResetRequestsView(generics.ListAPIView):
    permission_classes = [permissions.IsAdminUser]
    serializer_class = UserPasswordResetSerializer

    def get_queryset(self):
        return User.objects.filter(
            profile__reset_password_request=True
        ).select_related("profile", "profile__position")


class AdminResetPasswordView(APIView):
    permission_classes = [permissions.IsAdminUser]

    def post(self, request, user_id):
        temp_password = request.data.get("temp_password")
        if not temp_password:
            from secrets import token_urlsafe
            temp_password = token_urlsafe(8)

        try:
            validate_password(temp_password)
        except ValidationError as e:
            return Response({"detail": e.messages}, status=400)

        user = get_object_or_404(User.objects.select_related("profile"), pk=user_id)
        user.set_password(temp_password)
        user.save(update_fields=["password"])

        profile = user.profile
        profile.must_reset_password = True
        profile.reset_password_request = False
        profile.save(update_fields=["must_reset_password", "reset_password_request"])

        return Response({
            "temp_password": temp_password,
            "detail": "Temporary password set; user must change it on next login."
        }, status=200)


# ---------------------------------------------------------------------------
# Wage rate views
# ---------------------------------------------------------------------------

class WageRateListCreateView(ListCreateAPIView):
    permission_classes = [IsAuthenticated, IsHRorAuthorized]
    filter_backends = [WageOrderingFilter]
    ordering_fields = ['effective_from', 'created_at', 'id']
    ordering = ['-effective_from', '-id']

    def get_serializer_class(self):
        mode = (self.request.query_params.get("mode") or "overview").lower()
        return WageRateSerializer if (mode == "records" and self.request.method == "GET") or self.request.method == "POST" else UserWageOverviewSerializer

    def get_queryset(self):
        if self.request.method == "POST":
            return WageRate.objects.none()

        today = timezone.localdate()
        latest = (
            WageRate.objects
            .filter(user=OuterRef("pk"), effective_from__lte=today)
            .order_by("-effective_from")
        )
        qs = (
            User.objects
            .select_related("profile", "profile__position")
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

        active_param = self.request.query_params.get("active", "true").lower()
        if active_param in ("true", "1", "yes"):
            qs = qs.filter(is_active=True)
        elif active_param in ("false", "0", "no"):
            qs = qs.filter(is_active=False)

        search = (self.request.query_params.get("search") or "").strip()
        if search:
            qs = qs.filter(
                Q(username__icontains=search) |
                Q(first_name__icontains=search) |
                Q(last_name__icontains=search)
            )

        portal = (self.request.query_params.get("portal") or "").lower()
        if portal == "office":
            qs = qs.filter(
                Q(permission_overrides__codename="office_access", permission_overrides__granted=True) |
                Q(user_permissions__codename="office_access")
            ).distinct()
        elif portal == "workshop":
            qs = qs.filter(
                Q(permission_overrides__codename="workshop_access", permission_overrides__granted=True) |
                Q(user_permissions__codename="workshop_access")
            ).distinct()

        return qs


class WageRateDetailView(RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated, IsHRorAuthorized]
    serializer_class = WageRateSerializer
    queryset = WageRate.objects.select_related("user", "user__profile").all()

    def perform_update(self, serializer):
        serializer.save(updated_by=self.request.user)


class UserWageRateListView(ListAPIView):
    permission_classes = [IsAuthenticated, IsHRorAuthorized]
    serializer_class = WageRateSlimSerializer

    def get_queryset(self):
        user_obj = get_object_or_404(User, pk=self.kwargs["user_id"])
        qs = WageRate.objects.select_related("user", "user__profile").filter(user=user_obj)

        as_of_param = (self.request.query_params.get("as_of") or "").strip()
        as_of_date = timezone.localdate()
        if as_of_param:
            try:
                as_of_date = timezone.datetime.strptime(as_of_param, "%Y-%m-%d").date()
            except ValueError:
                pass

        include_future = (self.request.query_params.get("include_future") or "true").lower() == "true"
        if not include_future:
            qs = qs.filter(effective_from__lte=as_of_date)

        if (self.request.query_params.get("current") or "").lower() == "true":
            latest = (
                WageRate.objects
                .filter(user=user_obj, effective_from__lte=as_of_date)
                .order_by("-effective_from")
            )
            qs = qs.filter(id__in=Subquery(latest.values("id")[:1]))

        return qs


# ---------------------------------------------------------------------------
# Permission management views
# ---------------------------------------------------------------------------

def _get_custom_permissions():
    from users.models import PermissionMeta
    rows = list(PermissionMeta.objects.order_by('codename').values_list('codename', 'name'))
    return [c for c, _ in rows], {c: n for c, n in rows}


class UserPermissionsView(APIView):
    """GET /users/me/permissions/ — effective permissions for current user."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        codenames, names = _get_custom_permissions()
        if user.is_superuser:
            return Response({c: {'granted': True, 'name': names[c]} for c in codenames})
        return Response({c: {'granted': user_has_role_perm(user, c), 'name': names[c]} for c in codenames})


class UserPermissionDetailView(APIView):
    """GET /users/<user_id>/permissions/ — full permission state for one user."""
    permission_classes = [IsAuthenticated, IsAdmin]

    def get(self, request, user_id):
        target = get_object_or_404(
            User.objects.select_related('profile', 'profile__position')
            .prefetch_related('permission_overrides', 'user_permissions'),
            pk=user_id,
        )

        direct_perms: set[str] = {p.codename for p in target.user_permissions.all()}
        overrides_map = {o.codename: o for o in target.permission_overrides.all()}

        codenames, _ = _get_custom_permissions()
        effective = {}
        for c in codenames:
            if target.is_superuser:
                effective[c] = {'value': True, 'source': 'superuser', 'source_detail': ''}
            elif c in overrides_map:
                o = overrides_map[c]
                src = 'override_grant' if o.granted else 'override_deny'
                effective[c] = {'value': o.granted, 'source': src, 'source_detail': o.reason}
            elif c in direct_perms:
                effective[c] = {'value': True, 'source': 'position', 'source_detail': ''}
            else:
                effective[c] = {'value': False, 'source': 'none', 'source_detail': ''}

        overrides_data = [
            {
                'codename': o.codename, 'granted': o.granted,
                'reason': o.reason, 'created_at': o.created_at,
                'created_by': o.created_by_id,
            }
            for o in overrides_map.values()
        ]

        profile = getattr(target, 'profile', None)
        position_info = None
        if profile and profile.position_id:
            pos = profile.position
            position_info = {
                'id': pos.id,
                'title': pos.title,
                'level': pos.level,
                'department_code': pos.department_code or None,
            }

        return Response({
            'user': {
                'id': target.pk,
                'username': target.username,
                'full_name': target.get_full_name(),
                'is_superuser': target.is_superuser,
            },
            'position': position_info,
            'effective_permissions': effective,
            'overrides': overrides_data,
        })


class UserPermissionOverrideView(APIView):
    """Manage explicit per-user permission overrides."""
    permission_classes = [IsAuthenticated, IsAdmin]

    def put(self, request, user_id):
        from users.models import UserPermissionOverride
        target = get_object_or_404(User, pk=user_id)
        items = request.data
        if not isinstance(items, list):
            return Response({'detail': 'Expected a list of override objects.'}, status=400)

        codenames, _ = _get_custom_permissions()
        for i, item in enumerate(items):
            codename = (item.get('codename') or '').strip()
            granted = item.get('granted')
            if codename not in codenames:
                return Response({'detail': f'Item {i}: unknown codename "{codename}".'}, status=400)
            if granted is None:
                return Response({'detail': f'Item {i}: "granted" is required.'}, status=400)

        incoming = {item['codename'].strip(): item for item in items}
        UserPermissionOverride.objects.filter(user=target).exclude(codename__in=incoming.keys()).delete()
        for codename, item in incoming.items():
            UserPermissionOverride.objects.update_or_create(
                user=target, codename=codename,
                defaults={
                    'granted': bool(item['granted']),
                    'reason': (item.get('reason') or '').strip(),
                    'created_by': request.user,
                },
            )

        result = list(
            UserPermissionOverride.objects.filter(user=target)
            .values('codename', 'granted', 'reason').order_by('codename')
        )
        return Response({'detail': 'Overrides updated.', 'overrides': result})

    def post(self, request, user_id):
        from users.models import UserPermissionOverride
        target = get_object_or_404(User, pk=user_id)
        codename = (request.data.get('codename') or '').strip()
        granted = request.data.get('granted')
        reason = (request.data.get('reason') or '').strip()

        codenames, _ = _get_custom_permissions()
        if codename not in codenames:
            return Response({'detail': f'Unknown codename: {codename}'}, status=400)
        if granted is None:
            return Response({'detail': '"granted" (true/false) is required.'}, status=400)

        override, created = UserPermissionOverride.objects.update_or_create(
            user=target, codename=codename,
            defaults={'granted': bool(granted), 'reason': reason, 'created_by': request.user},
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


class PermissionListView(APIView):
    """GET /users/permissions/ — all custom permissions with who holds them."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from django.contrib.auth.models import Permission
        from django.contrib.contenttypes.models import ContentType
        from users.models import UserProfile, UserPermissionOverride, PermissionMeta

        ct = ContentType.objects.get_for_model(UserProfile)
        perms = (
            Permission.objects
            .filter(content_type=ct)
            .prefetch_related('user_set')
            .order_by('codename')
        )

        section_map = dict(PermissionMeta.objects.values_list('codename', 'section'))

        overrides = UserPermissionOverride.objects.select_related('user').all()
        override_map: dict[str, dict] = {}
        for o in overrides:
            override_map.setdefault(o.codename, {})[o.user_id] = {
                'id': o.user.id, 'username': o.user.username,
                'full_name': o.user.get_full_name(), 'granted': o.granted,
            }

        data = []
        for perm in perms:
            direct_users = [
                {
                    'id': u.id, 'username': u.username,
                    'full_name': u.get_full_name(),
                    'source': 'position', 'source_detail': None,
                }
                for u in perm.user_set.all()
            ]
            data.append({
                'codename': perm.codename,
                'name': perm.name,
                'section': section_map.get(perm.codename),
                'users': direct_users,
                'overrides': list(override_map.get(perm.codename, {}).values()),
            })

        return Response(data)


class UserPermissionsMatrixView(APIView):
    """GET /users/permissions/matrix/ — users × permissions matrix."""
    permission_classes = [IsAuthenticated, IsAdmin]

    def get(self, request):
        qs = (
            User.objects
            .select_related('profile', 'profile__position')
            .prefetch_related('permission_overrides', 'user_permissions')
            .order_by('username')
        )

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

        dept_filter = (request.query_params.get('department') or '').strip()
        if dept_filter:
            qs = qs.filter(profile__position__department_code=dept_filter)

        perm_codenames, _ = _get_custom_permissions()

        def _resolve(u) -> dict:
            if u.is_superuser:
                return {c: {'value': True, 'source': 'superuser', 'source_detail': ''} for c in perm_codenames}

            overrides = {o.codename: o for o in u.permission_overrides.all()}
            direct_perms: set[str] = {p.codename for p in u.user_permissions.all()}

            result = {}
            for c in perm_codenames:
                if c in overrides:
                    o = overrides[c]
                    src = 'override_grant' if o.granted else 'override_deny'
                    result[c] = {'value': o.granted, 'source': src, 'source_detail': o.reason}
                elif c in direct_perms:
                    result[c] = {'value': True, 'source': 'position', 'source_detail': ''}
                else:
                    result[c] = {'value': False, 'source': 'none', 'source_detail': ''}
            return result

        users_data = []
        for u in qs:
            prof = getattr(u, 'profile', None)
            pos = prof.position if prof and prof.position_id else None
            users_data.append({
                'id': u.pk,
                'username': u.username,
                'full_name': u.get_full_name(),
                'is_superuser': u.is_superuser,
                'position_title': pos.title if pos else None,
                'department_code': pos.department_code or None if pos else None,
                'permissions': _resolve(u),
            })

        return Response({'codenames': perm_codenames, 'users': users_data})


class ImpersonateUserView(APIView):
    """POST /users/impersonate/ — superuser-only: get JWT tokens for any user."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if not request.user.is_superuser:
            return Response({'detail': 'Superuser access required.'}, status=403)

        user_id = request.data.get('user_id')
        if not user_id:
            return Response({'detail': '"user_id" is required.'}, status=400)

        target = get_object_or_404(User, pk=user_id)
        refresh = RefreshToken.for_user(target)
        return Response({
            'refresh': str(refresh),
            'access': str(refresh.access_token),
            'user_id': target.pk,
            'username': target.username,
        })
