import logging

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.db import transaction
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

logger = logging.getLogger(__name__)

from .models import BugReport, BugReportAttachment, BugReportMessage
from .serializers import (
    BugReportCreateSerializer,
    BugReportDetailSerializer,
    BugReportListSerializer,
    BugReportReplySerializer,
)
from .tasks import enqueue_agent_process


class BugReportViewSet(ModelViewSet):
    permission_classes = [IsAuthenticated]
    http_method_names  = ['get', 'post', 'patch', 'delete']

    def get_queryset(self):
        qs = BugReport.objects.select_related('reported_by').prefetch_related('messages', 'attachments')
        # Staff see all; regular users see only their own
        if not self.request.user.is_staff:
            qs = qs.filter(reported_by=self.request.user)
        return qs

    def get_serializer_class(self):
        if self.action == 'create':
            return BugReportCreateSerializer
        if self.action in ('retrieve', 'messages'):
            return BugReportDetailSerializer
        return BugReportListSerializer

    def create(self, request, *args, **kwargs):
        serializer = BugReportCreateSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            bug_report = serializer.save()
            BugReportMessage.objects.create(
                bug_report=bug_report,
                sender_type=BugReportMessage.SENDER_USER,
                sender=request.user,
                content=f"{bug_report.description}\n\nSteps to reproduce:\n{bug_report.steps}".strip(),
            )
            transaction.on_commit(lambda: enqueue_agent_process(bug_report.pk))
        return Response(BugReportDetailSerializer(bug_report).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    def reply(self, request, pk=None):
        bug_report = self.get_object()
        if bug_report.status == BugReport.STATUS_CLOSED:
            return Response({'detail': 'Bug report is closed.'}, status=status.HTTP_400_BAD_REQUEST)

        serializer = BugReportReplySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        with transaction.atomic():
            BugReportMessage.objects.create(
                bug_report=bug_report,
                sender_type=BugReportMessage.SENDER_USER,
                sender=request.user,
                content=serializer.validated_data['content'],
            )
            if bug_report.status == BugReport.STATUS_WAITING:
                bug_report.status = BugReport.STATUS_OPEN
                bug_report.save(update_fields=['status', 'updated_at'])
            transaction.on_commit(lambda: enqueue_agent_process(bug_report.pk))

        return Response(BugReportDetailSerializer(bug_report).data)

    @action(detail=True, methods=['post'])
    def upload_attachment(self, request, pk=None):
        bug_report = self.get_object()
        file = request.FILES.get('file')
        if not file:
            return Response({'detail': 'No file provided.'}, status=status.HTTP_400_BAD_REQUEST)
        attachment = BugReportAttachment.objects.create(
            bug_report=bug_report,
            file=file,
            uploaded_by=request.user,
        )
        return Response({'id': attachment.pk, 'file': attachment.file.url}, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    def close(self, request, pk=None):
        if not request.user.is_staff:
            return Response({'detail': 'Not allowed.'}, status=status.HTTP_403_FORBIDDEN)
        bug_report = self.get_object()
        bug_report.close()
        return Response(BugReportDetailSerializer(bug_report).data)


@method_decorator(csrf_exempt, name='dispatch')
class AgentProcessTaskView(View):
    """Internal Cloud Tasks callback — processes bug report with the AI agent."""

    def post(self, request, bug_report_id: int):
        secret = request.headers.get('X-Task-Secret', '')
        if secret != settings.QUEUE_SECRET:
            raise PermissionDenied

        from .agent import process_bug_report
        try:
            process_bug_report(bug_report_id)
        except Exception:
            logger.exception('AgentProcessTaskView failed for bug report %s', bug_report_id)
            return HttpResponse(status=500)

        return HttpResponse(status=200)
