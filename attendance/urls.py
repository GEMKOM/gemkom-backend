from django.urls import path

from .views import (
    CheckInView,
    CheckOutView,
    TodayRecordView,
    AttendanceHistoryView,
    MonthlySummaryView,
    HRRecordListCreateView,
    HRRecordDetailView,
    HRApproveOverrideView,
    HRRejectOverrideView,
    HRPendingOverridesView,
    AttendanceSiteView,
    ShiftRuleListCreateView,
    ShiftRuleDetailView,
    ShiftRuleAssignView,
    DebugIPView,
)

urlpatterns = [
    # Employee self-service
    path('check-in/', CheckInView.as_view(), name='attendance-check-in'),
    path('check-out/', CheckOutView.as_view(), name='attendance-check-out'),
    path('today/', TodayRecordView.as_view(), name='attendance-today'),
    path('history/', AttendanceHistoryView.as_view(), name='attendance-history'),
    path('monthly-summary/', MonthlySummaryView.as_view(), name='attendance-monthly-summary'),

    # HR — records
    path('hr/records/', HRRecordListCreateView.as_view(), name='attendance-hr-records'),
    path('hr/records/<int:pk>/', HRRecordDetailView.as_view(), name='attendance-hr-record-detail'),
    path('hr/records/<int:pk>/approve-override/', HRApproveOverrideView.as_view(), name='attendance-hr-approve'),
    path('hr/records/<int:pk>/reject-override/', HRRejectOverrideView.as_view(), name='attendance-hr-reject'),
    path('hr/pending-overrides/', HRPendingOverridesView.as_view(), name='attendance-hr-pending'),

    # Debug (DEBUG=True only)
    path('debug/ip/', DebugIPView.as_view(), name='attendance-debug-ip'),

    # HR — config
    path('hr/site/', AttendanceSiteView.as_view(), name='attendance-hr-site'),
    path('hr/shift-rules/', ShiftRuleListCreateView.as_view(), name='attendance-hr-shift-rules'),
    path('hr/shift-rules/<int:pk>/', ShiftRuleDetailView.as_view(), name='attendance-hr-shift-rule-detail'),
    path('hr/shift-rules/assign/', ShiftRuleAssignView.as_view(), name='attendance-hr-shift-rule-assign'),
]
