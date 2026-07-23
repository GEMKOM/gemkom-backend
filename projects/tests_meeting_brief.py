from datetime import date
from decimal import Decimal

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.test import RequestFactory, TestCase
from django.test.utils import CaptureQueriesContext
from django.db import connection
from rest_framework.test import APIClient

from projects.models import (
    Customer, DiscussionAttachment, JobOrder, JobOrderCostSummary,
    JobOrderDepartmentTask, JobOrderDepartmentTaskFile,
    JobOrderDiscussionComment, JobOrderDiscussionTopic, JobOrderFile,
    JobOrderTargetDateRevision, TechnicalDrawingRelease,
)
from projects.services.meeting_brief import (
    _financial, build_meeting_brief, build_meeting_brief_section,
)

User = get_user_model()


def _allowed_host():
    for host in settings.ALLOWED_HOSTS:
        if host and not host.startswith(('.', '*')):
            return host
    return 'localhost'


class MeetingBriefFixtureMixin:
    """Root 900-01 with child 900-01-01, plus a noise job 901-01 that must
    never leak into the root's brief."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create(username='brief-user')
        cls.customer = Customer.objects.create(code='C-MB', name='Brief Customer')
        cls.root = JobOrder.objects.create(
            job_no='900-01', title='Brief Root', customer=cls.customer, status='active')
        cls.child = JobOrder.objects.create(
            job_no='900-01-01', title='Brief Child', customer=cls.customer,
            parent=cls.root, status='active')
        cls.noise = JobOrder.objects.create(
            job_no='901-01', title='Noise', customer=cls.customer, status='active')

    def brief(self, include_financial=False, root=None):
        request = RequestFactory().get('/')
        return build_meeting_brief(root or self.root, request, include_financial)

    def section(self, name, root=None):
        return build_meeting_brief_section(root or self.root, name)


class QualityRevisionTests(MeetingBriefFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        from quality_control.models import NCR
        common = dict(description='d', detected_by=cls.user, created_by=cls.user)
        NCR.objects.create(job_order=cls.root, title='open minor', severity='minor',
                           status='draft', **common)
        NCR.objects.create(job_order=cls.child, title='open critical', severity='critical',
                           status='rejected', **common)
        NCR.objects.create(job_order=cls.child, title='closed', severity='major',
                           status='closed', **common)
        NCR.objects.create(job_order=cls.noise, title='other job', severity='critical',
                           status='draft', **common)

        TechnicalDrawingRelease.objects.create(
            job_order=cls.child, revision_number=1, revision_code='A',
            folder_path='p', status='superseded')
        TechnicalDrawingRelease.objects.create(
            job_order=cls.child, revision_number=2, revision_code='B',
            folder_path='p', status='released')
        # Created LAST: the newest release event is a non-released one, so
        # `latest` picks it while `current` stays the released B. (-pk breaks
        # the auto_now_add microsecond tie.)
        TechnicalDrawingRelease.objects.create(
            job_order=cls.root, revision_number=1, revision_code='C1',
            folder_path='p', status='in_revision')

        JobOrderTargetDateRevision.objects.create(
            job_order=cls.root, previous_date=date(2026, 7, 1),
            new_date=date(2026, 7, 15), reason='Tedarik gecikmesi', changed_by=cls.user)
        JobOrderTargetDateRevision.objects.create(
            job_order=cls.root, previous_date=date(2026, 7, 15),
            new_date=date(2026, 8, 1), reason='Revizyon', changed_by=cls.user)
        JobOrderTargetDateRevision.objects.create(job_order=cls.child)  # not counted

    def test_ncr_counts_cover_subtree_and_exclude_noise(self):
        q = self.brief()['quality']
        self.assertEqual(q['total'], 3)
        self.assertEqual(q['open'], 2)
        self.assertEqual(q['open_by_severity'], {'minor': 1, 'major': 0, 'critical': 1})
        self.assertEqual({n['title'] for n in q['open_list']}, {'open minor', 'open critical'})

    def test_drawing_revision_counts_and_current(self):
        d = self.brief()['revisions']['drawing']
        self.assertEqual(d['revision_count'], 1)       # superseded rows
        self.assertEqual(d['in_revision_count'], 1)
        self.assertEqual(d['release_count'], 3)
        self.assertEqual(d['current']['revision_code'], 'B')
        self.assertEqual(d['current']['job_no'], self.child.job_no)

    def test_drawing_latest_is_newest_event_any_status(self):
        d = self.brief()['revisions']['drawing']
        self.assertEqual(d['latest']['revision_code'], 'C1')
        self.assertEqual(d['latest']['status'], 'in_revision')
        self.assertEqual(d['latest']['job_no'], self.root.job_no)
        self.assertIsNotNone(d['latest']['released_at'])

    def test_section_details_fetched_on_demand(self):
        # Heavy lists live in the section endpoint, not the main brief.
        brief = self.brief()
        self.assertNotIn('list', brief['quality'])
        self.assertNotIn('releases', brief['revisions']['drawing'])

        self.assertEqual(len(self.section('quality')['list']), 3)  # all statuses
        detail = self.section('revisions')
        self.assertEqual(len(detail['releases']), 3)
        self.assertEqual(detail['releases'][0]['revision_code'], 'C1')
        self.assertEqual(len(detail['target_date_revisions']), 2)  # root only

    def test_target_date_revisions_root_only(self):
        t = self.brief()['revisions']['target_date']
        self.assertEqual(t['count'], 2)
        self.assertEqual(t['latest_list'][0]['reason'], 'Revizyon')


class ProcurementCuttingTests(MeetingBriefFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        from planning.models import PlanningRequest, PlanningRequestItem
        from procurement.models import Item, PurchaseRequest, PurchaseRequestItem

        item = Item.objects.create(code='IT-1', name='Plaka', unit='adet')
        planning_request = PlanningRequest.objects.create(
            request_number='PL-MB-1', title='t', created_by=cls.user)
        # check_inventory=True lets quantity_from_inventory produce a
        # quantity_to_purchase of 0 (save() recomputes it either way).
        inventory_request = PlanningRequest.objects.create(
            request_number='PL-MB-2', title='t', created_by=cls.user,
            check_inventory=True)

        def pri(job_no, qty, delivered=False, from_inventory='0', request=None):
            return PlanningRequestItem.objects.create(
                planning_request=request or planning_request, item=item,
                job_no=job_no, quantity=Decimal(qty),
                quantity_from_inventory=Decimal(from_inventory),
                is_delivered=delivered)

        cls.pri_delivered = pri(cls.child.job_no, '5', delivered=True)
        cls.pri_requested = pri(cls.child.job_no, '5')
        cls.pri_untouched = pri(cls.root.job_no, '5')
        cls.pri_partial = pri(cls.child.job_no, '5')
        cls.pri_rejected = pri(cls.child.job_no, '5')
        # fully from stock -> quantity_to_purchase 0 -> excluded
        pri(cls.child.job_no, '10', from_inventory='10', request=inventory_request)
        pri(cls.noise.job_no, '5')          # other job: excluded

        pr_ok = PurchaseRequest.objects.create(
            request_number='PR-MB-1', title='t', requestor=cls.user, status='submitted')
        pr_bad = PurchaseRequest.objects.create(
            request_number='PR-MB-2', title='t', requestor=cls.user, status='rejected')
        PurchaseRequestItem.objects.create(
            purchase_request=pr_ok, item=item, quantity=Decimal('5'),
            planning_request_item=cls.pri_requested)
        PurchaseRequestItem.objects.create(
            purchase_request=pr_ok, item=item, quantity=Decimal('2'),
            planning_request_item=cls.pri_partial)
        PurchaseRequestItem.objects.create(
            purchase_request=pr_bad, item=item, quantity=Decimal('5'),
            planning_request_item=cls.pri_rejected)

        from cnc_cutting.models import CncPart, CncTask
        open_nest = CncTask.objects.create(key='NEST-MB-1', name='n1')
        done_nest = CncTask.objects.create(key='NEST-MB-2', name='n2', completion_date=1)
        CncPart.objects.create(cnc_task=open_nest, job_no=cls.child.job_no,
                               weight_kg=Decimal('10'), quantity=2)
        CncPart.objects.create(cnc_task=done_nest, job_no=cls.root.job_no,
                               weight_kg=Decimal('5'), quantity=None)  # None counts as 1
        CncPart.objects.create(cnc_task=open_nest, job_no=cls.noise.job_no,
                               weight_kg=Decimal('99'), quantity=1)

    def test_procurement_waiting_split(self):
        p = self.brief()['procurement']
        counters = {k: p[k] for k in (
            'items_total', 'items_delivered', 'items_waiting',
            'requested_waiting', 'not_yet_requested')}
        self.assertEqual(counters, {
            'items_total': 5,
            'items_delivered': 1,
            'items_waiting': 4,
            'requested_waiting': 1,
            # untouched + partial-PR + rejected-PR all still need a request
            'not_yet_requested': 3,
        })

    def test_cutting_counts_and_weights(self):
        c = self.brief()['cutting']
        self.assertEqual(c['parts_total'], 3)
        self.assertEqual(c['parts_cut'], 1)
        self.assertEqual(c['parts_waiting'], 2)
        self.assertAlmostEqual(c['weight_total'], 25.0)
        self.assertAlmostEqual(c['weight_cut'], 5.0)
        self.assertAlmostEqual(c['weight_waiting'], 20.0)

    def test_section_details_fetched_on_demand(self):
        brief = self.brief()
        self.assertNotIn('items', brief['procurement'])
        self.assertNotIn('parts', brief['cutting'])

        # ALL items come back, blockers first and delivered last.
        items = self.section('procurement')['items']
        self.assertEqual(len(items), 5)
        self.assertEqual(items[0]['stage'], 'not_requested')
        self.assertEqual(items[-1]['stage'], 'delivered')
        self.assertEqual(sum(1 for w in items if w['stage'] == 'delivered'), 1)
        self.assertEqual({w['item_code'] for w in items}, {'IT-1'})

        # ALL parts with their cut state, uncut first.
        parts = self.section('cutting')['parts']
        self.assertEqual(len(parts), 2)
        self.assertFalse(parts[0]['cut'])
        self.assertEqual(parts[0]['quantity'], 2)
        self.assertTrue(parts[1]['cut'])


class MachiningWeldingTests(MeetingBriefFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        from tasks.models import Operation, Part, Timer

        part_open = Part.objects.create(key='PART-MB-1', name='p1', job_no=cls.child.job_no)
        Part.objects.create(key='PART-MB-2', name='p2', job_no=cls.root.job_no,
                            completion_date=1)
        Part.objects.create(key='PART-MB-3', name='p3', job_no=cls.noise.job_no)

        op_open = Operation.objects.create(
            key='OP-MB-1', name='o1', part=part_open, order=1,
            estimated_hours=Decimal('10'))
        Operation.objects.create(
            key='OP-MB-2', name='o2', part=part_open, order=2,
            estimated_hours=Decimal('5'), completion_date=1)
        Operation.objects.create(  # est<=0: counted in op totals, ignored in hours
            key='OP-MB-3', name='o3', part=part_open, order=3, completion_date=1)
        op_ct = ContentType.objects.get_for_model(Operation)
        Timer.objects.create(user=cls.user, start_time=0, finish_time=4 * 3600 * 1000,
                             content_type=op_ct, object_id=op_open.key)

        # Welding board: main welding task with subtasks carrying assignments.
        cls.main_weld = JobOrderDepartmentTask.objects.create(
            job_order=cls.child, department='manufacturing', task_type='welding',
            title='Kaynaklı İmalat', status='in_progress')
        sub_a = JobOrderDepartmentTask.objects.create(
            job_order=cls.child, department='manufacturing', parent=cls.main_weld,
            title='Bölüm A', status='in_progress', manual_progress=Decimal('60'))
        sub_b = JobOrderDepartmentTask.objects.create(
            job_order=cls.child, department='manufacturing', parent=cls.main_weld,
            title='Bölüm B', status='completed')
        sub_paint = JobOrderDepartmentTask.objects.create(
            job_order=cls.child, department='manufacturing', parent=cls.main_weld,
            title='Boya', status='pending')

        from subcontracting.models import (
            Subcontractor, SubcontractingAssignment, SubcontractingPriceTier,
        )
        sub = Subcontractor.objects.create(name='Taşeron X')
        weld_tier = SubcontractingPriceTier.objects.create(
            job_order=cls.child, tier_type='welding', name='Kaynak',
            price_per_kg=Decimal('1'), allocated_weight_kg=Decimal('1000'))
        paint_tier = SubcontractingPriceTier.objects.create(
            job_order=cls.child, tier_type='paint', name='Boya',
            price_per_kg=Decimal('1'), allocated_weight_kg=Decimal('1000'))
        cls.assignment = SubcontractingAssignment.objects.create(
            department_task=sub_a, subcontractor=sub, price_tier=weld_tier,
            allocated_weight_kg=Decimal('600'))
        SubcontractingAssignment.objects.create(  # paint tier: excluded
            department_task=sub_paint, subcontractor=sub, price_tier=paint_tier,
            allocated_weight_kg=Decimal('50'))

        from teams.models import Team
        from welding.models import InternalTeamAssignment, WeldingPlanAllocation
        team = Team.objects.create(name='Ekip 1')
        InternalTeamAssignment.objects.create(
            department_task=sub_b, team=team, allocated_weight_kg=Decimal('400'))
        WeldingPlanAllocation.objects.create(  # not yet promoted -> planned row
            department_task=cls.main_weld, subcontractor=sub,
            allocated_weight_kg=Decimal('250'),
            planned_start_date=date(2026, 8, 1), planned_end_date=date(2026, 8, 20))
        WeldingPlanAllocation.objects.create(  # promoted -> must NOT double-list
            department_task=cls.main_weld, team=team,
            allocated_weight_kg=Decimal('400'),
            promoted_internal_team_assignment_id=None,
            promoted_subcontracting_assignment=cls.assignment)

        # Task-progress cases on the ROOT job (no assignments — the "manual
        # progress without kg" signal):
        weld2 = JobOrderDepartmentTask.objects.create(  # rollup over welding-typed child
            job_order=cls.root, department='manufacturing', task_type='welding',
            title='Kök Kaynak', status='in_progress', weight=20)
        JobOrderDepartmentTask.objects.create(  # deduped (parent also selected)
            job_order=cls.root, department='manufacturing', task_type='welding',
            parent=weld2, title='Alt Kaynak', status='in_progress',
            manual_progress=Decimal('40'))
        JobOrderDepartmentTask.objects.create(  # blocked -> 0 despite manual 70
            job_order=cls.root, department='manufacturing', task_type='welding',
            title='Bloklu Kaynak', status='blocked', manual_progress=Decimal('70'))
        JobOrderDepartmentTask.objects.create(  # skipped -> excluded entirely
            job_order=cls.root, department='manufacturing', task_type='welding',
            title='Atlanan Kaynak', status='skipped', manual_progress=Decimal('100'))
        JobOrderDepartmentTask.objects.create(  # manual 100 open -> capped 99
            job_order=cls.root, department='manufacturing', task_type='welding',
            title='Tavan Kaynak', status='in_progress', manual_progress=Decimal('100'))

        from welding.models import WeldingTimeEntry
        WeldingTimeEntry.objects.create(
            employee=cls.user, job_no=cls.child.job_no, date=date(2026, 7, 20),
            hours=Decimal('5.50'), overtime_type='regular')
        WeldingTimeEntry.objects.create(
            employee=cls.user, job_no=cls.child.job_no, date=date(2026, 7, 18),
            hours=Decimal('3.00'), overtime_type='after_hours')
        WeldingTimeEntry.objects.create(
            employee=cls.user, job_no=cls.root.job_no, date=date(2026, 7, 19),
            hours=Decimal('2.00'), overtime_type='holiday')
        WeldingTimeEntry.objects.create(  # other job: excluded
            employee=cls.user, job_no=cls.noise.job_no, date=date(2026, 7, 19),
            hours=Decimal('99.00'), overtime_type='regular')

    def test_machining_hours_and_counts(self):
        m = self.brief()['machining']
        self.assertEqual(m['operations_total'], 3)
        self.assertEqual(m['operations_completed'], 2)
        self.assertEqual(m['operations_waiting'], 1)
        self.assertAlmostEqual(m['estimated_hours_total'], 15.0)
        self.assertAlmostEqual(m['hours_spent'], 4.0)
        # completed op earns its 5h estimate; open op earns min(4/10,1)*10 = 4h
        self.assertAlmostEqual(m['hours_earned'], 9.0)
        self.assertAlmostEqual(m['hours_remaining'], 6.0)
        self.assertEqual(m['parts_total'], 2)
        self.assertEqual(m['parts_completed'], 1)

    def test_welding_resources(self):
        w = self.brief()['welding']
        self.assertEqual(w['resources_total'], 3)  # subcontractor + team + planned
        by_kind = {(r['kind'], r['planned']): r for r in w['resources']}

        committed_sub = by_kind[('subcontractor', False)]
        self.assertEqual(committed_sub['name'], 'Taşeron X')
        self.assertAlmostEqual(committed_sub['allocated_weight_kg'], 600.0)
        self.assertAlmostEqual(committed_sub['progress_pct'], 60.0)

        committed_team = by_kind[('team', False)]
        self.assertAlmostEqual(committed_team['progress_pct'], 100.0)

        planned = by_kind[('subcontractor', True)]
        self.assertAlmostEqual(planned['allocated_weight_kg'], 250.0)
        self.assertIsNone(planned['progress_pct'])
        self.assertEqual(planned['planned_start_date'], date(2026, 8, 1))

        # (600*60 + 400*100) / 1000 = 76.0 over committed rows only
        self.assertAlmostEqual(w['weighted_progress_pct'], 76.0)
        self.assertAlmostEqual(w['allocated_kg_total'], 1250.0)

    def test_welding_task_progress_mirrors_model(self):
        # main_weld (w10, in_progress): (60+100+0)/3 subtasks = 53.33
        # weld2 (w20): welding-typed child deduped from the flat set, rollup 40
        # blocked (w10): 0 despite manual 70; skipped: excluded
        # capped (w10): min(100, 99) = 99
        # -> (53.33*10 + 40*20 + 0*10 + 99*10) / 50 = 46.5
        w = self.brief()['welding']
        self.assertAlmostEqual(w['task_progress_pct'], 46.5, places=1)

    def test_welding_hours_buckets(self):
        hours = self.brief()['welding']['hours']
        self.assertEqual(hours, {
            'regular': 5.5, 'after_hours': 3.0, 'holiday': 2.0, 'total': 10.5,
        })

    def test_machining_operations_section(self):
        self.assertNotIn('operations', self.brief()['machining'])
        operations = self.section('machining')['operations']
        self.assertEqual(len(operations), 3)
        # Open work first, biggest estimate up top
        self.assertEqual(operations[0]['key'], 'OP-MB-1')
        self.assertFalse(operations[0]['completed'])
        self.assertAlmostEqual(operations[0]['hours_spent'], 4.0)


class FilesTests(MeetingBriefFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        JobOrderFile.objects.create(
            job_order=cls.child, file='job_order_files/900-01-01/a.pdf',
            uploaded_by=cls.user)
        JobOrderFile.objects.create(
            job_order=cls.noise, file='job_order_files/901-01/x.pdf')

        task = JobOrderDepartmentTask.objects.create(
            job_order=cls.root, department='design', title='Dizayn')
        JobOrderDepartmentTaskFile.objects.create(
            task=task, file='department_task_files/1/b.pdf', uploaded_by=cls.user)

        topic = JobOrderDiscussionTopic.objects.create(
            job_order=cls.root, title='Konu', content='c', created_by=cls.user)
        comment_topic = JobOrderDiscussionTopic.objects.create(
            job_order=cls.child, title='Konu 2', content='c', created_by=cls.user)
        comment = JobOrderDiscussionComment.objects.create(
            topic=comment_topic, content='c', created_by=cls.user)
        # bulk_create skips DiscussionAttachment.save(), which would hit
        # storage for file.size
        DiscussionAttachment.objects.bulk_create([
            DiscussionAttachment(topic=topic, file='discussion_files/1/1/c.pdf',
                                 name='c.pdf', size=10, uploaded_by=cls.user),
            DiscussionAttachment(comment=comment, file='discussion_files/2/2/d.pdf',
                                 name='d.pdf', size=20, uploaded_by=cls.user),
        ])

        # Sales-offer files exist but must NOT appear (user decision).
        from sales.models import SalesOffer, SalesOfferFile
        offer = SalesOffer.objects.create(
            offer_no='OF-MB-1', customer=cls.customer, title='Teklif')
        SalesOfferFile.objects.create(
            offer=offer, file='sales_offer_files/OF-MB-1/s1.pdf', name='s1.pdf')
        cls.root.source_offer = offer
        cls.root.save(update_fields=['source_offer'])

    def test_groups_totals_and_no_offer_group(self):
        f = self.brief()['files']
        self.assertEqual(f['job_order']['total'], 1)
        self.assertEqual(f['job_order']['items'][0]['name'], 'a.pdf')
        self.assertEqual(f['task']['total'], 1)
        self.assertNotIn('offer', f)
        self.assertEqual(f['discussion']['total'], 2)
        names = {i['name'] for i in f['discussion']['items']}
        self.assertEqual(names, {'c.pdf', 'd.pdf'})
        job_nos = {i['job_no'] for i in f['discussion']['items']}
        self.assertEqual(job_nos, {self.root.job_no, self.child.job_no})


class FinancialLadderTests(MeetingBriefFixtureMixin, TestCase):
    def _summary(self, actual, estimated, price=Decimal('1000'), job=None):
        job = job or self.root
        JobOrderCostSummary.objects.update_or_create(
            job_order=job,
            defaults={
                'actual_total_cost': actual,
                'estimated_total_cost': estimated,
                'selling_price': price,
                'selling_price_currency': 'EUR',
            },
        )
        job.refresh_from_db()
        return job

    def test_no_summary_is_no_data(self):
        self.assertEqual(_financial(self.root)['verdict'], 'no_data')

    def test_zero_summary_is_no_data(self):
        job = self._summary(Decimal('0'), None)
        self.assertEqual(_financial(job)['verdict'], 'no_data')

    def test_no_price_anywhere(self):
        job = self._summary(Decimal('100'), Decimal('200'), price=Decimal('0'))
        self.assertEqual(_financial(job)['verdict'], 'no_price')

    def test_healthy(self):
        job = self._summary(Decimal('500'), Decimal('800'))
        result = _financial(job)
        self.assertEqual(result['verdict'], 'healthy')
        self.assertFalse(result['price_is_derived'])

    def test_risky_ratio(self):
        job = self._summary(Decimal('920'), None)
        self.assertEqual(_financial(job)['verdict'], 'risky')

    def test_risky_budget_overrun(self):
        job = self._summary(Decimal('150'), Decimal('100'))
        result = _financial(job)
        self.assertEqual(result['verdict'], 'risky')
        self.assertIn('bütçe', result['reason'].lower())

    def test_critical_projected_over_price(self):
        job = self._summary(Decimal('600'), Decimal('1100'))
        self.assertEqual(_financial(job)['verdict'], 'critical')

    def test_critical_actual_at_price(self):
        job = self._summary(Decimal('1000'), None)
        self.assertEqual(_financial(job)['verdict'], 'critical')

    def test_derived_price_from_child(self):
        job = self._summary(Decimal('100'), Decimal('200'), price=Decimal('0'))
        self._summary(Decimal('0'), None, price=Decimal('500'), job=self.child)
        result = _financial(job)
        self.assertEqual(result['verdict'], 'healthy')
        self.assertTrue(result['price_is_derived'])


class MeetingBriefEndpointTests(MeetingBriefFixtureMixin, TestCase):
    def setUp(self):
        self.client = APIClient()
        self.host = _allowed_host()
        self.superuser = User.objects.create(username='brief-admin', is_superuser=True)

    def _get(self, job_no, user):
        self.client.force_authenticate(user=user)
        return self.client.get(
            f'/projects/job-orders/{job_no}/meeting-brief/', HTTP_HOST=self.host)

    def test_root_returns_brief_with_financial_for_superuser(self):
        response = self._get(self.root.job_no, self.superuser)
        self.assertEqual(response.status_code, 200)
        for key in ('quality', 'revisions', 'procurement', 'cutting',
                    'machining', 'welding', 'files', 'financial'):
            self.assertIn(key, response.data)
        self.assertEqual(response.data['node_count'], 2)

    def test_financial_key_absent_without_cost_permission(self):
        response = self._get(self.root.job_no, self.user)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('financial', response.data)

    def test_child_job_is_rejected(self):
        response = self._get(self.child.job_no, self.superuser)
        self.assertEqual(response.status_code, 400)

    def test_section_endpoint(self):
        self.client.force_authenticate(user=self.superuser)
        response = self.client.get(
            f'/projects/job-orders/{self.root.job_no}/meeting-brief/machining/',
            HTTP_HOST=self.host)
        self.assertEqual(response.status_code, 200)
        self.assertIn('operations', response.data)

        # Unknown section never matches the route
        response = self.client.get(
            f'/projects/job-orders/{self.root.job_no}/meeting-brief/bogus/',
            HTTP_HOST=self.host)
        self.assertEqual(response.status_code, 404)

        # Non-root guard applies to sections too
        response = self.client.get(
            f'/projects/job-orders/{self.child.job_no}/meeting-brief/machining/',
            HTTP_HOST=self.host)
        self.assertEqual(response.status_code, 400)

    def test_query_count_stays_bounded(self):
        request = RequestFactory().get('/')
        with CaptureQueriesContext(connection) as ctx:
            build_meeting_brief(self.root, request, include_financial=True)
        self.assertLessEqual(len(ctx.captured_queries), 35,
                             f'{len(ctx.captured_queries)} queries')
