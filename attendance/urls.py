from django.urls import path

from .views import (
    CheckInView,
    CheckOutView,
    TodayRecordView,
    AttendanceHistoryView,
    MonthlySummaryView,
    HRRecordListCreateView,
    HRRecordDetailView,
    HRAttendanceSummaryView,
    HRApproveOverrideView,
    HRRejectOverrideView,
    HRPendingOverridesView,
    HRSessionListCreateView,
    HRSessionDetailView,
    HRLeaveIntervalListCreateView,
    HRLeaveIntervalDetailView,
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
    path('hr/summary/', HRAttendanceSummaryView.as_view(), name='attendance-hr-summary'),

    # HR — session override approval/rejection (pk = AttendanceSession.id)
    path('hr/sessions/<int:pk>/approve/', HRApproveOverrideView.as_view(), name='attendance-hr-approve'),
    path('hr/sessions/<int:pk>/reject/', HRRejectOverrideView.as_view(), name='attendance-hr-reject'),
    path('hr/pending-overrides/', HRPendingOverridesView.as_view(), name='attendance-hr-pending'),

    # HR — session management per record
    path('hr/records/<int:record_id>/sessions/', HRSessionListCreateView.as_view(), name='attendance-hr-sessions'),
    path('hr/sessions/<int:pk>/', HRSessionDetailView.as_view(), name='attendance-hr-session-detail'),

    # HR — leave intervals
    path('hr/records/<int:record_id>/intervals/', HRLeaveIntervalListCreateView.as_view(), name='attendance-hr-intervals'),
    path('hr/intervals/<int:pk>/', HRLeaveIntervalDetailView.as_view(), name='attendance-hr-interval-detail'),

    # Debug (staff/superuser only)
    path('debug/ip/', DebugIPView.as_view(), name='attendance-debug-ip'),

    # HR — config
    path('hr/site/', AttendanceSiteView.as_view(), name='attendance-hr-site'),
    path('hr/shift-rules/', ShiftRuleListCreateView.as_view(), name='attendance-hr-shift-rules'),
    path('hr/shift-rules/<int:pk>/', ShiftRuleDetailView.as_view(), name='attendance-hr-shift-rule-detail'),
    path('hr/shift-rules/assign/', ShiftRuleAssignView.as_view(), name='attendance-hr-shift-rule-assign'),
]
