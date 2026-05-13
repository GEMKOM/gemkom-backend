from django.urls import path

from .api_views import (
    MyApprovalInboxView,
    PolicyDetailView,
    PolicyListCreateView,
    StageDetailView,
    StageListCreateView,
    SubjectTypeListView,
    WorkflowApproverOverrideView,
    WorkflowCancelView,
    WorkflowDetailView,
    WorkflowsBySubjectView,
)

urlpatterns = [
    # Policies
    path("policies/", PolicyListCreateView.as_view(), name="approval-policy-list"),
    path("policies/<int:pk>/", PolicyDetailView.as_view(), name="approval-policy-detail"),

    # Stages (nested under policy for creation, flat for edit/delete)
    path("policies/<int:policy_id>/stages/", StageListCreateView.as_view(), name="approval-stage-list"),
    path("stages/<int:pk>/", StageDetailView.as_view(), name="approval-stage-detail"),

    # Live workflows
    path("workflows/", WorkflowsBySubjectView.as_view(), name="approval-workflow-by-subject"),
    path("workflows/<int:pk>/", WorkflowDetailView.as_view(), name="approval-workflow-detail"),
    path("workflows/<int:pk>/stages/<int:order>/approvers/", WorkflowApproverOverrideView.as_view(), name="approval-stage-approver-override"),
    path("workflows/<int:pk>/cancel/", WorkflowCancelView.as_view(), name="approval-workflow-cancel"),

    # Subject types
    path("subject-types/", SubjectTypeListView.as_view(), name="approval-subject-types"),

    # Inbox
    path("inbox/", MyApprovalInboxView.as_view(), name="approval-inbox"),
]
