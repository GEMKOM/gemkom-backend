from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import OrderingFilter, SearchFilter
from procurement.filters import PurchaseRequestFilter, ItemFilter
from rest_framework.views import APIView
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework import status, permissions

from procurement.permissions import IsFinanceAuthorized, IsFinanceOrPlanningAuthorized
from .models import (
    PaymentSchedule, PaymentTerms, PurchaseOrder, PurchaseOrderLine, PurchaseRequestDraft,
    Supplier, Item, PurchaseRequest, PurchaseRequestItem, SupplierOffer, ItemOffer
)
from .serializers import (
    PaymentTermsSerializer, PurchaseRequestDraftDetailSerializer, PurchaseRequestDraftListSerializer,
    SupplierSerializer, ItemSerializer, PurchaseRequestSerializer, PurchaseRequestCreateSerializer,
    PurchaseRequestItemSerializer, SupplierOfferSerializer, ItemOfferSerializer
)
from django.db.models import Exists, OuterRef, F, Q
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework import status, permissions

from django.contrib.contenttypes.models import ContentType
from django.db.models import OuterRef, Subquery, Exists
from approvals.models import ApprovalWorkflow, ApprovalStageInstance, ApprovalDecision

from procurement.approval_service import create_pos_from_recommended, submit_purchase_request, decide
from .services import cancel_purchase_request, compute_vat_carry_map, recompute_payment_schedule_due_dates

from django.db.models import Count, Prefetch
from .models import PurchaseOrder
from .serializers import (
    PurchaseOrderListSerializer,
    PurchaseOrderDetailSerializer,
)
from rest_framework.exceptions import ValidationError, PermissionDenied
from django.db import transaction
from decimal import Decimal

from django.db.models import Q, OuterRef, Exists, Value, IntegerField
from django.db.models import Min, F, Case, When
from django.db.models.functions import Coalesce, TruncDate
from django.db.models import Prefetch

from django.db.models import Count, Min, OuterRef, Subquery, Value
from django.db.models.functions import Coalesce
from decimal import Decimal
from django.contrib.auth import get_user_model
from .reports.common import bool_param

class PaymentTermsViewSet(viewsets.ModelViewSet):
    """
    - LIST/RETRIEVE: all active=True terms.
    - CREATE: allowed only for custom terms (is_custom enforced).
    - UPDATE: disabled.
    - DELETE: instead of deleting, set active=False (soft delete).
    """
    serializer_class = PaymentTermsSerializer
    permission_classes = [IsFinanceAuthorized]
    filter_backends = [SearchFilter, OrderingFilter]
    search_fields = ["name", "code", "active", "is_custom"]
    ordering_fields = ["name", "updated_at"]
    ordering = ["name"]

    def get_queryset(self):
        # Only active ones are shown in dropdowns etc.
        return PaymentTerms.objects.filter(active=True).order_by("name")

    def perform_create(self, serializer):
        # Force is_custom=True for created terms
        if not serializer.validated_data.get("is_custom", False):
            raise ValidationError("Only custom payment terms can be created (is_custom must be true).")
        serializer.save(is_custom=True, active=True)

    def update(self, request, *args, **kwargs):
        # Disable updates completely
        raise ValidationError("Updates to payment terms are not allowed.")

    def partial_update(self, request, *args, **kwargs):
        # Disable partial updates too
        raise ValidationError("Updates to payment terms are not allowed.")

    def perform_destroy(self, instance):
        if not instance.is_custom:
            raise PermissionDenied("Standard (non-custom) payment terms cannot be deleted.")
        # Soft delete: mark inactive instead of deleting
        instance.active = False
        instance.save()

class SupplierViewSet(viewsets.ModelViewSet):
    queryset = Supplier.objects.filter(is_active=True)
    serializer_class = SupplierSerializer
    filter_backends = [SearchFilter, OrderingFilter]
    permission_classes = [IsFinanceAuthorized]
    search_fields = ["name", "contact_person", "email", "default_payment_terms"]
    ordering_fields = ["id", "name", "updated_at"]
    
    def get_queryset(self):
        queryset = Supplier.objects.filter(is_active=True)
        name = self.request.query_params.get('name', None)
        if name:
            queryset = queryset.filter(name__icontains=name)
        return queryset

class ItemViewSet(viewsets.ModelViewSet):
    queryset = Item.objects.all()
    serializer_class = ItemSerializer
    permission_classes = [IsFinanceOrPlanningAuthorized]

    filter_backends = [DjangoFilterBackend, OrderingFilter, SearchFilter]
    filterset_class = ItemFilter
    ordering_fields = ["code", "name"]
    search_fields = ["code", "name"]

    @action(detail=True, methods=['get'], url_path='purchase-requests')
    def purchase_requests(self, request, pk=None):
        """
        Get all purchase requests that include this item.
        Returns purchase request details with the specific item details.
        """
        item = self.get_object()

        # Get all purchase request items for this item
        pr_items = PurchaseRequestItem.objects.filter(
            item=item
        ).select_related(
            'purchase_request',
            'purchase_request__requestor'
        ).prefetch_related(
            'purchase_request__request_items__item',
            'purchase_request__offers__supplier'
        ).order_by('-purchase_request__created_at')

        # Build response with PR details and item-specific info
        results = []
        for pr_item in pr_items:
            pr = pr_item.purchase_request
            results.append({
                'purchase_request_id': pr.id,
                'request_number': pr.request_number,
                'title': pr.title,
                'status': pr.status,
                'status_label': pr.get_status_display(),
                'priority': pr.priority,
                'requestor': pr.requestor.username if pr.requestor else None,
                'created_at': pr.created_at,
                'submitted_at': pr.submitted_at,
                'total_amount_eur': pr.total_amount_eur,
                'item_details': {
                    'quantity': pr_item.quantity,
                    'item_description': pr_item.item_description,
                    'specifications': pr_item.specifications,
                    'priority': pr_item.priority,
                }
            })

        return Response(results)

    @action(detail=True, methods=['get'], url_path='planning-requests')
    def planning_requests(self, request, pk=None):
        """
        Get all planning requests that include this item.
        Returns planning request details with the specific item details.
        """
        from planning.models import PlanningRequestItem

        item = self.get_object()

        # Get all planning request items for this item
        planning_items = PlanningRequestItem.objects.filter(
            item=item
        ).select_related(
            'planning_request',
            'planning_request__created_by'
        ).prefetch_related(
            'planning_request__items__item'
        ).order_by('-planning_request__created_at')

        # Build response with planning request details and item-specific info
        results = []
        for planning_item in planning_items:
            pl = planning_item.planning_request
            results.append({
                'planning_request_id': pl.id,
                'request_number': pl.request_number,
                'title': pl.title,
                'status': pl.status,
                'status_label': pl.get_status_display(),
                'priority': pl.priority,
                'created_by': pl.created_by.username if pl.created_by else None,
                'created_at': pl.created_at,
                'needed_date': pl.needed_date,
                'item_details': {
                    'job_no': planning_item.job_no,
                    'quantity': planning_item.quantity,
                    'item_description': planning_item.item_description,
                    'specifications': planning_item.specifications,
                }
            })

        return Response(results)

class PurchaseRequestViewSet(viewsets.ModelViewSet):
    queryset = PurchaseRequest.objects.all()
    serializer_class = PurchaseRequestSerializer
    permission_classes = [IsFinanceAuthorized]
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_class = PurchaseRequestFilter
    ordering_fields = ['id', 'title', 'requestor', 'priority', 'status', 'created_at', 'total_amount_eur']  # Add any fields you want to allow
    ordering = ['-id']  # Default ordering
    
    def get_queryset(self):
        wf_qs = (
            ApprovalWorkflow.objects
            .select_related("policy")
            .prefetch_related(
                "stage_instances",
                "stage_instances__decisions__approver",
            )
            .order_by("-created_at")
        )
        return (
            PurchaseRequest.objects
            .select_related("requestor")
            .prefetch_related(
                "request_items__item",
                "offers__supplier",
                "purchase_orders",
                "planning_request_items",
                Prefetch("approvals", queryset=wf_qs),  # ← use the generic relation
            )
        )
    
    def get_serializer_class(self):
        if self.action == 'create':
            return PurchaseRequestCreateSerializer
        return PurchaseRequestSerializer
    
    @action(detail=True, methods=["POST"], permission_classes=[IsFinanceAuthorized])
    def submit(self, request, pk=None):
        pr = self.get_object()
        if pr.status == 'cancelled':
            return Response({"detail": "Cancelled requests cannot be processed."}, status=400)
        try:
            submit_purchase_request(pr, request.user)
        except Exception as e:
            return Response({"detail": str(e)}, status=400)
        return Response({"detail": "Submitted."})

    @action(detail=True, methods=["POST"], permission_classes=[IsFinanceAuthorized])
    def approve(self, request, pk=None):
        pr = self.get_object()
        if pr.status == 'cancelled':
            return Response({"detail": "Cancelled requests cannot be processed."}, status=400)
        try:
            decide(pr, request.user, approve=True, comment=request.data.get("comment",""))
        except PermissionError as e:
            return Response({"detail": str(e)}, status=403)
        except Exception as e:
            return Response({"detail": str(e)}, status=400)
        return Response({"detail": "Approved."})

    @action(detail=True, methods=["POST"], permission_classes=[IsFinanceAuthorized])
    def reject(self, request, pk=None):
        pr = self.get_object()
        if pr.status == 'cancelled':
            return Response({"detail": "Cancelled requests cannot be processed."}, status=400)
        try:
            decide(pr, request.user, approve=False, comment=request.data.get("comment",""))
        except PermissionError as e:
            return Response({"detail": str(e)}, status=403)
        except Exception as e:
            return Response({"detail": str(e)}, status=400)
        return Response({"detail": "Rejected."})
    
    @action(detail=False, methods=['get'])
    def my_requests(self, request):
        """Get current user's purchase requests"""
        user = request.user
        queryset = PurchaseRequest.objects.filter(requestor=user)
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'], permission_classes=[IsFinanceAuthorized])
    def pending_approval(self, request):
        user = request.user
        ct_pr = ContentType.objects.get_for_model(PurchaseRequest)

        # 1) Get open CURRENT stages where I am an approver and haven’t decided
        my_decision_qs = ApprovalDecision.objects.filter(stage_instance=OuterRef('pk'), approver=user)

        stages_qs = (
            ApprovalStageInstance.objects
            .filter(
                workflow__content_type=ct_pr,
                order=F('workflow__current_stage_order'),  # ← no nested Subquery, use F() directly
                is_complete=False,
                is_rejected=False,
                approver_user_ids__contains=[user.id],     # JSONB contains int
            )
            .annotate(already_decided=Exists(my_decision_qs))
            .filter(already_decided=False)
            .values_list('workflow__object_id', flat=True)
        )

        # 2) PRs linked to those stages and still "submitted"
        queryset = (
            PurchaseRequest.objects
            .filter(id__in=Subquery(stages_qs), status='submitted')
            .exclude(requestor=user)          # keep if you want to block self-approval
            .order_by('-created_at')
        )

        page = self.paginate_queryset(queryset)
        if page is not None:
            ser = PurchaseRequestSerializer(page, many=True)
            return self.get_paginated_response(ser.data)
        ser = PurchaseRequestSerializer(queryset, many=True)
        return Response(ser.data)

        
    @action(detail=False, methods=['get'], permission_classes=[IsFinanceAuthorized])
    def approved_by_me(self, request):
        """
        Purchase requests where I have approved (optionally filter by date range).
        Query params:
        - since: ISO datetime (include decisions made at/after this)
        - until: ISO datetime (include decisions made before this)
        - decision: 'approve' or 'reject' (default: approve)
        """
        user = request.user
        decision_type = request.query_params.get("decision", "approve")
        since = request.query_params.get("since")
        until = request.query_params.get("until")

        ct_pr = ContentType.objects.get_for_model(self.get_queryset().model)

        # Base subquery: my decisions on any stage in this PR's workflow
        my_decisions = ApprovalDecision.objects.filter(
            stage_instance__workflow__content_type=ct_pr,
            stage_instance__workflow__object_id=OuterRef('pk'),
            approver=user,
        )
        if decision_type in ("approve", "reject"):
            my_decisions = my_decisions.filter(decision=decision_type)
        if since:
            my_decisions = my_decisions.filter(decided_at__gte=since)
        if until:
            my_decisions = my_decisions.filter(decided_at__lt=until)

        qs = (
            self.get_queryset()
            .annotate(i_decided=Exists(my_decisions))
            .filter(i_decided=True)
            .order_by(*self.ordering)
            .distinct()
        )

        page = self.paginate_queryset(qs)
        if page is not None:
            ser = self.get_serializer(page, many=True)
            return self.get_paginated_response(ser.data)

        ser = self.get_serializer(qs, many=True)
        return Response(ser.data)


    @action(detail=True, methods=["POST"], permission_classes=[IsFinanceAuthorized])
    def generate_pos(self, request, pk=None):
        """
        Manually create POs from recommended offers for this PR.
        Useful for testing. Safe to call multiple times.
        """
        pr = self.get_object()
        pos = create_pos_from_recommended(pr)
        if not pos:
            return Response({"detail": "No POs created (already created or no recommended items)."}, status=200)
        data = PurchaseOrderListSerializer(pos, many=True).data
        return Response({"detail": f"Created {len(pos)} PO(s).", "purchase_orders": data}, status=201)
    
    @action(detail=True, methods=["POST"], permission_classes=[IsFinanceAuthorized])
    def cancel(self, request, pk=None):
        pr = self.get_object()
        reason = request.data.get("reason", "")
        try:
            cancel_purchase_request(pr, request.user, reason=reason)
        except PermissionError as e:
            return Response({"detail": str(e)}, status=status.HTTP_403_FORBIDDEN)
        except Exception as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"detail": "Purchase request cancelled."}, status=status.HTTP_200_OK)
    
class PurchaseRequestDraftViewSet(viewsets.ModelViewSet):
    queryset = PurchaseRequestDraft.objects.all()
    permission_classes = [IsFinanceAuthorized]
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_fields = ['id', 'requestor', 'title']
    ordering_fields = ['id', 'requestor', 'title', 'needed_date', 'priority']
    ordering = ['-id']

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        return qs if user.is_superuser else qs.filter(requestor=user)

    def get_serializer_class(self):
        # list -> brief (no `data`), everything else -> detail (with `data`)
        if self.action == 'list':
            return PurchaseRequestDraftListSerializer
        return PurchaseRequestDraftDetailSerializer

    def perform_create(self, serializer):
        serializer.save(requestor=self.request.user)

    def perform_update(self, serializer):
        # prevent changing ownership on update
        serializer.save(requestor=self.request.user)

    # If you keep manual query param filters, fix the field name:
    def list(self, request, *args, **kwargs):
        # optional: keep DjangoFilterBackend only and delete this override
        title = request.query_params.get('title')
        self.queryset = self.get_queryset()
        if title:
            self.queryset = self.queryset.filter(title__icontains=title)  # <- fixed from name__icontains
        return super().list(request, *args, **kwargs)


class PurchaseRequestItemViewSet(viewsets.ModelViewSet):
    queryset = PurchaseRequestItem.objects.all()
    serializer_class = PurchaseRequestItemSerializer
    permission_classes = [IsFinanceAuthorized]
    
    def get_queryset(self):
        purchase_request_id = self.request.query_params.get('purchase_request', None)
        if purchase_request_id:
            return PurchaseRequestItem.objects.filter(purchase_request_id=purchase_request_id)
        return PurchaseRequestItem.objects.all()

class SupplierOfferViewSet(viewsets.ModelViewSet):
    queryset = SupplierOffer.objects.all()
    serializer_class = SupplierOfferSerializer
    permission_classes = [IsFinanceAuthorized]
    
    def get_queryset(self):
        purchase_request_id = self.request.query_params.get('purchase_request', None)
        if purchase_request_id:
            return SupplierOffer.objects.filter(purchase_request_id=purchase_request_id)
        return SupplierOffer.objects.all()

class ItemOfferViewSet(viewsets.ModelViewSet):
    queryset = ItemOffer.objects.all()
    serializer_class = ItemOfferSerializer
    permission_classes = [IsFinanceAuthorized]
    
    def get_queryset(self):
        purchase_request_id = self.request.query_params.get('purchase_request', None)
        supplier_offer_id = self.request.query_params.get('supplier_offer', None)
        
        queryset = ItemOffer.objects.all()
        if purchase_request_id:
            queryset = queryset.filter(supplier_offer__purchase_request_id=purchase_request_id)
        if supplier_offer_id:
            queryset = queryset.filter(supplier_offer_id=supplier_offer_id)
        
        return queryset
    
    @action(detail=True, methods=['post'])
    def toggle_recommendation(self, request, pk=None):
        """Toggle recommendation status for an item offer"""
        item_offer = self.get_object()
        
        # Ensure only one recommendation per item
        if not item_offer.is_recommended:
            # Remove other recommendations for the same item
            ItemOffer.objects.filter(
                purchase_request_item=item_offer.purchase_request_item
            ).update(is_recommended=False)
            
            # Set this one as recommended
            item_offer.is_recommended = True
        else:
            # Remove this recommendation
            item_offer.is_recommended = False
        
        item_offer.save()
        
        return Response({'is_recommended': item_offer.is_recommended})


class StatusChoicesView(APIView):
    permission_classes = [IsFinanceAuthorized]

    def get(self, request):
        return Response([
            {"value": k, "label": v} for k, v in PurchaseRequest.STATUS_CHOICES
        ])
    
class BasisChoicesView(APIView):
    permission_classes = [IsFinanceAuthorized]

    def get(self, request):
        return Response([
            {"value": k, "label": v} for k, v in PaymentTerms.BASIS_CHOICES
        ])


class PurchaseOrderViewSet(viewsets.ModelViewSet):
    queryset = PurchaseOrder.objects.all()
    permission_classes = [IsFinanceAuthorized]
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_fields = ['status', 'supplier', 'pr']
    # allow API consumer to override, but we’ll default to next_unpaid_due
    ordering_fields = ['id', 'created_at', 'total_amount', 'next_unpaid_due']
    ordering = ['next_unpaid_due', 'id']  # default: earliest first, ties by id

    def create(self, request, *args, **kwargs):
        return Response(status=status.HTTP_405_METHOD_NOT_ALLOWED)

    def update(self, request, *args, **kwargs):
        return Response(status=status.HTTP_405_METHOD_NOT_ALLOWED)

    def partial_update(self, request, *args, **kwargs):
        return Response(status=status.HTTP_405_METHOD_NOT_ALLOWED)

    def _with_payment_annos(self, qs):
        unpaid_exists = PaymentSchedule.objects.filter(
            purchase_order=OuterRef('pk'),
            is_paid=False
        )
        # next unpaid due date; fallback to ordered_at/created_at (as DATE)
        next_unpaid_due = Coalesce(
            Min('payment_schedules__due_date', filter=Q(payment_schedules__is_paid=False)),
            TruncDate('ordered_at'),
            TruncDate('created_at'),
        )
        return qs.annotate(
            has_unpaid=Exists(unpaid_exists),
            next_unpaid_due=next_unpaid_due,
        )

    def get_queryset(self):
        qs = (
            PurchaseOrder.objects
            .select_related('supplier', 'pr', 'supplier_offer')
        )

        schedules_qs = PaymentSchedule.objects.order_by('sequence')

        if self.action == 'list':
            qs = (
                qs
                .annotate(line_count=Count('lines'))
                .prefetch_related(Prefetch('payment_schedules', queryset=schedules_qs))
            )
        else:
            qs = qs.prefetch_related(
                'lines__purchase_request_item__item',
                'lines__allocations',
                Prefetch('payment_schedules', queryset=schedules_qs),
            )

        qs = self._with_payment_annos(qs)

        # Push fully-paid POs to the bottom while preserving ordering.
        # has_unpaid=True -> 0 ; False -> 1 ; ascending puts unpaid first.
        unpaid_rank = Case(
            When(has_unpaid=False, then=Value(1)),
            default=Value(0),
            output_field=IntegerField(),
        )
        return qs.order_by(unpaid_rank, *self.ordering)

    def get_serializer_class(self):
        return (
            PurchaseOrderDetailSerializer
            if self.action == 'retrieve'
            else PurchaseOrderListSerializer
        )
    
    def perform_destroy(self, instance):
        """
        Deletes a Purchase Order. This is a destructive action.
        - Only Admins can perform this.
        - The associated Purchase Request is cancelled.
        - All related PO lines, schedules, and allocations are deleted via CASCADE.
        """
        if not self.request.user.is_staff:
            raise PermissionDenied("Only administrators can delete a purchase order.")

        pr = instance.pr

        with transaction.atomic():
            instance.delete()
            if pr:
                cancel_purchase_request(pr, self.request.user, reason=f"Related PO-{instance.id} was deleted.")


    @action(detail=True, methods=["POST"])
    @transaction.atomic
    def mark_schedule_paid(self, request, pk=None):
        po = self.get_object()
        schedule_id = request.data.get("schedule_id")
        if not schedule_id:
            return Response({"detail": "schedule_id is required."}, status=400)

        paid_with_tax = request.data.get("paid_with_tax", None)
        if paid_with_tax is None:
            return Response({"detail": "paid_with_tax is required (true/false)."}, status=400)
        paid_with_tax = bool(paid_with_tax)

        try:
            ps = po.payment_schedules.get(id=schedule_id)
        except PaymentSchedule.DoesNotExist:
            return Response({"detail": "Schedule not found for this PO."}, status=404)

        if ps.is_paid:
            return Response({"detail": "Already marked paid."}, status=200)

        # (Optional) enforce paying in order for non-immediate bases
        earlier_unpaid = po.payment_schedules.filter(sequence__lt=ps.sequence, is_paid=False).exists()
        if earlier_unpaid and ps.basis != "immediate":
            return Response({"detail": "You must pay prior schedules first."}, status=400)

        # Guard: if this is the last unpaid schedule, net-only is not allowed
        more_unpaid_exists = po.payment_schedules.filter(is_paid=False).exclude(id=ps.id).exists()
        if not more_unpaid_exists and not paid_with_tax:
            return Response({"detail": "Last installment cannot be paid without tax."}, status=400)

        ps.is_paid = True
        ps.paid_with_tax = paid_with_tax
        ps.paid_at = timezone.now()
        ps.paid_by = request.user
        ps.save(update_fields=["is_paid", "paid_with_tax", "paid_at", "paid_by"])

        # Recompute dependent due dates
        recompute_payment_schedule_due_dates(po, save=True)

        all_net_paid = not po.payment_schedules.filter(is_paid=False).exists()
        tax_outstanding = compute_vat_carry_map(po)['tax_outstanding']

        if all_net_paid and tax_outstanding == Decimal('0.00') and po.status != "paid":
            po.status = "paid"
            po.save(update_fields=["status"])

        # Return updated PO snapshot (with derived VAT fields)
        serializer = PurchaseOrderDetailSerializer(po, context=self.get_serializer_context())
        return Response(serializer.data, status=200)

class ProcurementReportViewSet(viewsets.GenericViewSet):
    """
    All procurement reports under /procurement/reports/<report-name>/.
    Uses DRF pagination (paginate_queryset / get_paginated_response).
    """
    permission_classes = [IsFinanceAuthorized]

    @action(detail=False, methods=["get"], url_path="items")
    def items(self, request):
        """
        Items report (EUR-normalized): supports ?code=, ?name=, ?ordering=..., pagination.
        Hides items with no convertible data (same behavior as before).
        """
        from .reports.items import build_items_report

        # optional filters for items
        base_qs = Item.objects.all()
        code_q = request.query_params.get("code")
        name_q = request.query_params.get("name")
        if code_q:
            base_qs = base_qs.filter(code__icontains=code_q)
        if name_q:
            base_qs = base_qs.filter(name__icontains=name_q)

        rows = build_items_report(base_qs, request) or []

        page = self.paginate_queryset(rows)
        if page is not None:
            return self.get_paginated_response(page)
        return Response(rows)
    

    @action(detail=False, methods=["get"], url_path="suppliers")
    def suppliers(self, request):
        """
        Suppliers report (EUR-normalized).
        Filters supported in builder: ?name=, ?code=, ?has_dbs=, ?created_gte=, ?created_lte=, ?status=, ?min_total_spent_eur=
        Ordering: ?ordering=... (default -total_spent_eur). Pagination as usual.
        Hides 'empty' suppliers (no active POs, no spend, no items).
        """
        from .reports.suppliers import build_suppliers_report

        base_qs = Supplier.objects.filter(is_active=True)
        rows = build_suppliers_report(base_qs, request) or []

        page = self.paginate_queryset(rows)
        if page is not None:
            return self.get_paginated_response(page)
        return Response(rows)

    @action(detail=False, methods=["get"], url_path="staff")
    def staff(self, request):
        """
        Procurement staff report:
        Accepts user filters and includes both procurement & external_workshops by default.
        Filters:
          - teams: comma-separated team codes (default: procurement,external_workshops)
          - username: icontains filter on username
          - name: icontains filter on first_name OR last_name
          - email: icontains filter on email
          - is_active: true/false (1/0/yes/no/true/false)
        Plus the existing date filters used inside the builder:
          - created_gte, created_lte
        Ordering: ?ordering=... (default -total_spent_eur). Pagination applied.
        """
        from .reports.employees import build_procurement_staff_report

        User = get_user_model()
        base_qs = User.objects.all()

        # Teams: default to both procurement & external_workshops
        teams_param = request.query_params.get("teams") or request.query_params.get("team")
        if teams_param:
            teams = [t.strip() for t in teams_param.split(",") if t.strip()]
        else:
            teams = ["procurement", "external_workshops"]
        base_qs = base_qs.filter(profile__team__in=teams)

        # User filters
        username_q = request.query_params.get("username")
        name_q     = request.query_params.get("name")
        email_q    = request.query_params.get("email")
        is_active_q = request.query_params.get("is_active")

        if username_q:
            base_qs = base_qs.filter(username__icontains=username_q)

        if name_q:
            base_qs = base_qs.filter(
                Q(first_name__icontains=name_q) | Q(last_name__icontains=name_q)
            )

        if email_q:
            base_qs = base_qs.filter(email__icontains=email_q)

        active_bool = bool_param(is_active_q)
        if active_bool is not None:
            base_qs = base_qs.filter(is_active=active_bool)

        rows = build_procurement_staff_report(base_qs, request) or []

        page = self.paginate_queryset(rows)
        if page is not None:
            return self.get_paginated_response(page)
        return Response(rows)
    
    @action(detail=False, methods=["get"], url_path="executive")
    def executive(self, request):
        from .reports.finance import build_executive_overview
        payload = build_executive_overview(request) or {}
        return Response(payload)

    @action(detail=False, methods=["get"], url_path="concentration")
    def concentration(self, request):
        from .reports.finance import build_concentration_report
        payload = build_concentration_report(request) or {}
        return Response(payload)

    @action(detail=False, methods=["get"], url_path="cash-forecast")
    def cash_forecast(self, request):
        from .reports.finance import build_cash_forecast
        payload = build_cash_forecast(request) or {}
        return Response(payload)

    @action(detail=False, methods=["get"], url_path="cycle-time")
    def cycle_time(self, request):
        from .reports.finance import build_cycle_time_report
        payload = build_cycle_time_report(request) or {}
        return Response(payload)

    @action(detail=False, methods=["get"], url_path="price-variance")
    def price_variance(self, request):
        from .reports.finance import build_price_variance_report
        rows = build_price_variance_report(request) or []
        page = self.paginate_queryset(rows)
        if page is not None:
            return self.get_paginated_response(page)
        return Response(rows)

    @action(detail=False, methods=["get"], url_path="projects")
    def projects(self, request):
        from .reports.finance import build_projects_report
        rows = build_projects_report(request) or []
        page = self.paginate_queryset(rows)
        if page is not None:
            return self.get_paginated_response(page)
        return Response(rows)

