import re
import unicodedata
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404
from rest_framework.views import APIView
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend

from core.emails import send_plain_email
from users.filters import UserFilter, WageOrderingFilter
from users.helpers import _team_manager_user_ids
from users.models import UserProfile, WageRate
from users.permissions import IsAdmin, IsHRorAuthorized
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
        qs = User.objects.filter(is_active=True).select_related('profile').order_by('username')

        if not user.is_authenticated:
            return qs.filter(profile__work_location='workshop')

        if user.is_admin:
            return qs

        if getattr(user.profile, 'work_location', None) == 'office':
            return qs

        return qs.filter(profile__work_location='workshop')


    def get_permissions(self):
        if self.action == 'list':
            return []
        return [IsAdmin()]
    
    def get_serializer_class(self):
        if self.action == 'create':
            return UserCreateSerializer
        elif self.action in ['update', 'partial_update']:
            return AdminUserUpdateSerializer
        elif self.action == 'list':
            user = self.request.user
            if not user.is_authenticated:
                return PublicUserSerializer
            if user.is_admin:
                return UserListSerializer
            if getattr(user.profile, 'work_location', None) == 'office':
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

        if user.is_admin:
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

            # build recipient list: superusers + team managers (deduped, no empty emails)
            superuser_emails = list(
                User.objects.filter(is_active=True, is_superuser=True)
                .exclude(email="")
                .values_list("email", flat=True)
            )
            manager_ids = _team_manager_user_ids(getattr(profile, "team", "") or "")
            manager_emails = list(
                User.objects.filter(id__in=manager_ids, is_active=True)
                .exclude(email="")
                .values_list("email", flat=True)
            )

            recipients = list({*superuser_emails, *manager_emails})

            if recipients:
                # compose a concise notification (Turkish)
                requested_at = timezone.localtime().strftime("%d.%m.%Y %H:%M")
                full_name = user.get_full_name() or user.username
                team = getattr(profile, "team", "") or "—"
                body = (
                    f"Parola sıfırlama talebi gönderildi.\n\n"
                    f"Kullanıcı: {full_name} (username: {user.username})\n"
                    f"Takım: {team}\n"
                    f"Tarih: {requested_at}\n\n"
                    f"Lütfen sistemden onaylayın."
                )
                subject = f"[GEMKOM] Parola sıfırlama talebi: {user.username}"

                try:
                    send_plain_email(subject=subject, body=body, to=recipients)
                except Exception as e:
                    # don't leak errors to the client; log if you have logging set up
                    # logger.exception("Failed to send reset-password notification email")
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
        profile.temp_password_set_at = timezone.now()
        profile.save(update_fields=["must_reset_password", "reset_password_request", "temp_password_set_at"])

        # (Optional) email/telegram temp password to user; or return it once:
        return Response({"temp_password": temp_password, "detail": "Temporary password set; user must change it on next login."}, status=200)
    

class WageRateListCreateView(ListCreateAPIView):
    permission_classes = [IsAuthenticated, IsHRorAuthorized]
    filter_backends = [WageOrderingFilter]  # <— built-in ordering, dynamic fields

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