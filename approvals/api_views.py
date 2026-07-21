from __future__ import annotations

from django.contrib.contenttypes.models import ContentType
from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from users.permissions import IsAdmin

from .api_serializers import (
    ApprovalPolicySerializer,
    ApprovalPolicyWriteSerializer,
    ApprovalStageSerializer,
    ApprovalStageWriteSerializer,
    WorkflowDetailSerializer,
)
from .models import ApprovalPolicy, ApprovalStage, ApprovalWorkflow


SUBJECT_TYPE_DESCRIPTIONS = [
    {"value": "vacation_request",              "label": "İzin Talebi"},
    {"value": "overtime_request",              "label": "Mesai Talebi"},
    {"value": "purchase_request",              "label": "Satınalma Talebi"},
    {"value": "purchase_request_rolling_mill", "label": "Satınalma Talebi (Haddehane)"},
    {"value": "subcontractor_statement",       "label": "Taşeron Hakedişi"},
    {"value": "qc_review",                     "label": "Kalite Kontrol İncelemesi"},
    {"value": "ncr",                           "label": "Uygunsuzluk Raporu (NCR)"},
    {"value": "sales_offer",                   "label": "Satış Teklifi"},
    {"value": "department_request",            "label": "Departman Talebi"},
    {"value": "crane_request",                 "label": "Vinç Talebi"},
]


class SubjectTypeListView(APIView):
    """
    GET /approvals/subject-types/
    Returns the list of available policy subject types with Turkish labels.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(SUBJECT_TYPE_DESCRIPTIONS)


class IsAdminOrHR(IsAuthenticated):
    def has_permission(self, request, view):
        if not super().has_permission(request, view):
            return False
        if request.user.is_superuser or request.user.is_staff:
            return True
        from users.permissions import user_has_role_perm
        return user_has_role_perm(request.user, 'manage_hr')


# ---------------------------------------------------------------------------
# ApprovalPolicy CRUD
# ---------------------------------------------------------------------------

class PolicyListCreateView(generics.ListCreateAPIView):
    """
    GET  /approvals/policies/         list all policies (with their stages)
    POST /approvals/policies/         create a policy
    """
    permission_classes = [IsAdminOrHR]

    def get_queryset(self):
        return ApprovalPolicy.objects.prefetch_related(
            "stages", "stages__approver_users"
        ).order_by("selection_priority", "id")

    def get_serializer_class(self):
        if self.request.method == "POST":
            return ApprovalPolicyWriteSerializer
        return ApprovalPolicySerializer


class PolicyDetailView(generics.RetrieveUpdateDestroyAPIView):
    """
    GET   /approvals/policies/{id}/   retrieve with stages
    PATCH /approvals/policies/{id}/   update policy metadata
    DELETE /approvals/policies/{id}/  delete policy (only if no live workflows)
    """
    permission_classes = [IsAdminOrHR]
    queryset = ApprovalPolicy.objects.prefetch_related("stages", "stages__approver_users")

    def get_serializer_class(self):
        if self.request.method in ("PUT", "PATCH"):
            return ApprovalPolicyWriteSerializer
        return ApprovalPolicySerializer

    def destroy(self, request, *args, **kwargs):
        policy = self.get_object()
        live = ApprovalWorkflow.objects.filter(
            policy=policy, is_complete=False, is_rejected=False, is_cancelled=False
        ).exists()
        if live:
            return Response(
                {"detail": "Bu politikanın aktif onay akışları var, silinemez."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return super().destroy(request, *args, **kwargs)


# ---------------------------------------------------------------------------
# ApprovalStage CRUD (nested under policy)
# ---------------------------------------------------------------------------

class StageListCreateView(generics.ListCreateAPIView):
    """
    GET  /approvals/policies/{policy_id}/stages/      list stages for a policy
    POST /approvals/policies/{policy_id}/stages/      add a stage
    """
    permission_classes = [IsAdminOrHR]

    def get_queryset(self):
        return ApprovalStage.objects.filter(
            policy_id=self.kwargs["policy_id"]
        ).prefetch_related("approver_users").order_by("order")

    def get_serializer_class(self):
        if self.request.method == "POST":
            return ApprovalStageWriteSerializer
        return ApprovalStageSerializer

    def perform_create(self, serializer):
        policy = generics.get_object_or_404(ApprovalPolicy, pk=self.kwargs["policy_id"])
        serializer.save(policy=policy)


class StageDetailView(generics.RetrieveUpdateDestroyAPIView):
    """
    GET    /approvals/stages/{id}/   retrieve a stage
    PATCH  /approvals/stages/{id}/   update a stage (change approver_users, climb_levels, etc.)
    DELETE /approvals/stages/{id}/   delete a stage
    """
    permission_classes = [IsAdminOrHR]
    queryset = ApprovalStage.objects.prefetch_related("approver_users")

    def get_serializer_class(self):
        if self.request.method in ("PUT", "PATCH"):
            return ApprovalStageWriteSerializer
        return ApprovalStageSerializer


# ---------------------------------------------------------------------------
# Live Workflow read + override
# ---------------------------------------------------------------------------

class WorkflowDetailView(generics.RetrieveAPIView):
    """
    GET /approvals/workflows/{id}/   full workflow detail with all stages and decisions
    """
    permission_classes = [IsAdminOrHR]
    queryset = ApprovalWorkflow.objects.select_related(
        "policy", "content_type"
    ).prefetch_related(
        "stage_instances", "stage_instances__decisions", "stage_instances__decisions__approver"
    )
    serializer_class = WorkflowDetailSerializer


class WorkflowsBySubjectView(APIView):
    """
    GET /approvals/workflows/?type=vacation_request&id=42
    Returns all workflows (including historical) for a given subject object.
    """
    permission_classes = [IsAdminOrHR]

    def get(self, request):
        subject_type = request.query_params.get("type")  # e.g. "vacation_request"
        subject_id = request.query_params.get("id")
        if not subject_type or not subject_id:
            return Response({"detail": "type and id query params are required."}, status=400)

        # Accept both "vacation_request" and "vacationrequest" forms
        model_name = subject_type.replace("_", "").lower()

        # Pinned app_label for models that appear in multiple apps
        APP_PINS = {
            "planningrequest": "planning",
            "purchaserequest": "procurement",
        }
        qs = ContentType.objects.filter(model=model_name)
        if model_name in APP_PINS:
            qs = qs.filter(app_label=APP_PINS[model_name])
        ct = qs.first()
        if not ct:
            return Response({"detail": f"Unknown subject type: {subject_type}"}, status=400)

        wfs = ApprovalWorkflow.objects.filter(
            content_type=ct, object_id=subject_id
        ).select_related("policy", "content_type").prefetch_related(
            "stage_instances", "stage_instances__decisions", "stage_instances__decisions__approver"
        ).order_by("-created_at")

        return Response(WorkflowDetailSerializer(wfs, many=True).data)


class WorkflowApproverOverrideView(APIView):
    """
    PATCH /approvals/workflows/{id}/stages/{order}/approvers/
    Override the approver list on a live stage instance.
    Admin-only — for correcting misconfigured chains on in-flight requests.

    Body: { "approver_user_ids": [1, 2, 3], "required_approvals": 1 }
    """
    permission_classes = [IsAdmin]

    def patch(self, request, pk, order):
        wf = generics.get_object_or_404(
            ApprovalWorkflow.objects.prefetch_related("stage_instances"),
            pk=pk,
        )
        stage = wf.stage_instances.filter(order=order).first()
        if not stage:
            return Response({"detail": "Stage not found."}, status=404)
        if stage.is_complete or stage.is_rejected:
            return Response({"detail": "This stage is already finished."}, status=400)

        new_ids = request.data.get("approver_user_ids")
        new_req = request.data.get("required_approvals")

        if new_ids is not None:
            if not isinstance(new_ids, list):
                return Response({"detail": "approver_user_ids must be a list."}, status=400)
            stage.approver_user_ids = list(dict.fromkeys(int(i) for i in new_ids))

        if new_req is not None:
            stage.required_approvals = int(new_req)

        stage.save(update_fields=["approver_user_ids", "required_approvals"])

        from .api_serializers import StageInstanceDetailSerializer
        return Response(StageInstanceDetailSerializer(stage).data)


class WorkflowCancelView(APIView):
    """
    POST /approvals/workflows/{id}/cancel/
    Admin force-cancel a live workflow (marks is_cancelled=True).
    """
    permission_classes = [IsAdmin]

    def post(self, request, pk):
        wf = generics.get_object_or_404(ApprovalWorkflow, pk=pk)
        if wf.is_complete or wf.is_rejected or wf.is_cancelled:
            return Response({"detail": "Workflow already finished."}, status=400)
        wf.is_cancelled = True
        wf.save(update_fields=["is_cancelled"])
        return Response({"detail": "Workflow cancelled."})


# ---------------------------------------------------------------------------
# Approval inbox — "what needs my decision right now"
# ---------------------------------------------------------------------------

class MyApprovalInboxView(APIView):
    """
    GET /approvals/inbox/
    Returns all live stage instances where the requesting user is an approver,
    across every approval type (vacation, overtime, procurement, planning, etc.)
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from django.db.models import F
        from .models import ApprovalStageInstance

        stages = (
            ApprovalStageInstance.objects
            .filter(
                approver_user_ids__contains=[request.user.id],
                is_complete=False,
                is_rejected=False,
                workflow__is_complete=False,
                workflow__is_rejected=False,
                workflow__is_cancelled=False,
                order=F("workflow__current_stage_order"),
            )
            .select_related("workflow", "workflow__policy", "workflow__content_type")
            .prefetch_related("decisions", "decisions__approver")
            .order_by("workflow__created_at")
        )

        results = []
        for stage in stages:
            wf = stage.workflow
            results.append({
                "workflow_id":      wf.id,
                "subject_type":     f"{wf.content_type.app_label}.{wf.content_type.model}",
                "subject_id":       wf.object_id,
                "policy_name":      wf.policy.name,
                "current_stage":    stage.order,
                "stage_name":       stage.name,
                "required_approvals": stage.required_approvals,
                "approved_count":   stage.approved_count,
                "created_at":       wf.created_at,
                "snapshot":         wf.snapshot,
            })

        return Response(results)
