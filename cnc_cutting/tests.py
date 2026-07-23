import json
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from rest_framework.test import APIClient

from cnc_cutting.models import CncPart, CncTask, RemnantPlate
from cnc_cutting.serializers import parse_thickness_from_item_name
from planning.models import FileAsset, FileAttachment, PlanningRequest, PlanningRequestItem
from procurement.models import Item

User = get_user_model()

TASKS_URL = '/cnc_cutting/tasks/'
ITEMS_URL = '/planning/items/'


class PlateFixtureMixin:
    """User + plate catalog items + planning request items + a remnant plate."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create(username='cnc-user')

        cls.item_plate = Item.objects.create(
            code='0100 0000 0005 000 000', name='5 mm ST 37-2 SAC', unit='kg')
        cls.item_plate_comma = Item.objects.create(
            code='0100 0000 0002 500 001', name='2,5 mm PASLANMAZ SAC AISI 304', unit='kg')
        cls.item_plate_noparse = Item.objects.create(
            code='0100 9999 0000 000 001', name='PLAZMA SARF MALZEMESİ', unit='kg')
        cls.item_nonplate = Item.objects.create(
            code='0200 0000 0001 000 000', name='CIVATA M12', unit='adet')

        cls.planning_request = PlanningRequest.objects.create(
            request_number='PL-CNC-1', title='t', created_by=cls.user)

        def pri(item, job_no='900-01', qty='500', delivered=False, consumed=False):
            return PlanningRequestItem.objects.create(
                planning_request=cls.planning_request, item=item,
                job_no=job_no, quantity=Decimal(qty),
                is_delivered=delivered, is_consumed=consumed)

        cls.pri = pri(cls.item_plate, delivered=True)
        cls.pri_comma = pri(cls.item_plate_comma)
        cls.pri_noparse = pri(cls.item_plate_noparse)
        cls.pri_consumed = pri(cls.item_plate, consumed=True)
        cls.pri_nonplate = pri(cls.item_nonplate)

        cls.remnant = RemnantPlate.objects.create(
            thickness_mm=Decimal('10'), dimensions='1000x2000', quantity=2,
            material='ST 44-2')

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def create_cut(self, **extra):
        data = {'name': 'Kesim', 'nesting_id': 'N-1'}
        data.update(extra)
        return self.client.post(TASKS_URL, data, format='multipart')

    def patch_cut(self, key, **data):
        return self.client.patch(f'{TASKS_URL}{key}/', data, format='multipart')


class ThicknessParseTests(TestCase):
    def test_parse_variants(self):
        self.assertEqual(parse_thickness_from_item_name('5 mm ST 37-2 SAC'), Decimal('5'))
        self.assertEqual(parse_thickness_from_item_name('2,5 mm SAC'), Decimal('2.5'))
        self.assertEqual(parse_thickness_from_item_name('12.7 MM SAC'), Decimal('12.7'))
        self.assertIsNone(parse_thickness_from_item_name('PLAZMA SARF'))
        self.assertIsNone(parse_thickness_from_item_name(None))
        self.assertIsNone(parse_thickness_from_item_name(''))
        # Anchored: dimension strings must not be read as thickness.
        self.assertIsNone(parse_thickness_from_item_name('SAC 1500x3000 mm'))
        self.assertIsNone(parse_thickness_from_item_name('1000 mm SAC'))  # >= 1000 guard


class PlateSourceCreateTests(PlateFixtureMixin, TestCase):
    def test_create_with_planning_item_links_and_derives(self):
        resp = self.create_cut(planning_request_item_id=self.pri.id)
        self.assertEqual(resp.status_code, 201, resp.data)
        task = CncTask.objects.get(key=resp.data['key'])
        self.assertEqual(task.planning_request_item_id, self.pri.id)
        self.assertEqual(task.material, '5 mm ST 37-2 SAC')
        self.assertEqual(task.thickness_mm, Decimal('5'))
        self.assertEqual(task.quantity, 1)
        self.assertEqual(resp.data['plate_item']['item_code'], self.item_plate.code)
        self.assertEqual(resp.data['plate_item']['cnc_cuts_count'], 1)

    def test_create_derives_comma_decimal_thickness(self):
        resp = self.create_cut(planning_request_item_id=self.pri_comma.id)
        self.assertEqual(resp.status_code, 201, resp.data)
        task = CncTask.objects.get(key=resp.data['key'])
        self.assertEqual(task.thickness_mm, Decimal('2.5'))

    def test_create_unparseable_name_leaves_thickness_null(self):
        resp = self.create_cut(planning_request_item_id=self.pri_noparse.id)
        self.assertEqual(resp.status_code, 201, resp.data)
        task = CncTask.objects.get(key=resp.data['key'])
        self.assertIsNone(task.thickness_mm)
        self.assertEqual(task.material, 'PLAZMA SARF MALZEMESİ')

    def test_create_requires_exactly_one_source(self):
        before = CncTask.objects.count()

        resp = self.create_cut()  # neither
        self.assertEqual(resp.status_code, 400)

        resp = self.create_cut(  # both
            planning_request_item_id=self.pri.id, selected_plate_id=self.remnant.id)
        self.assertEqual(resp.status_code, 400)

        # No orphan tasks were left behind by the failed creates.
        self.assertEqual(CncTask.objects.count(), before)

    def test_create_rejects_consumed_item(self):
        resp = self.create_cut(planning_request_item_id=self.pri_consumed.id)
        self.assertEqual(resp.status_code, 400)

    def test_create_rejects_non_plate_item(self):
        resp = self.create_cut(planning_request_item_id=self.pri_nonplate.id)
        self.assertEqual(resp.status_code, 400)

    def test_create_with_remnant_copies_plate_details(self):
        resp = self.create_cut(selected_plate_id=self.remnant.id)
        self.assertEqual(resp.status_code, 201, resp.data)
        task = CncTask.objects.get(key=resp.data['key'])
        self.assertIsNone(task.planning_request_item_id)
        self.assertEqual(task.material, 'ST 44-2')
        self.assertEqual(task.thickness_mm, Decimal('10'))
        self.assertEqual(task.dimensions, '1000x2000')
        self.assertEqual(task.quantity, 1)
        self.assertEqual(task.plate_usage_records.count(), 1)

    def test_create_marks_item_consumed(self):
        resp = self.create_cut(
            planning_request_item_id=self.pri.id, mark_item_consumed='true')
        self.assertEqual(resp.status_code, 201, resp.data)
        self.pri.refresh_from_db()
        self.assertTrue(self.pri.is_consumed)
        self.assertEqual(self.pri.consumed_by, self.user)
        self.assertIsNotNone(self.pri.consumed_at)

    def test_create_mark_consumed_without_item_rejected(self):
        resp = self.create_cut(selected_plate_id=self.remnant.id, mark_item_consumed='true')
        self.assertEqual(resp.status_code, 400)

    def test_parts_search_includes_plate_source(self):
        resp = self.create_cut(
            planning_request_item_id=self.pri.id,
            parts_data=json.dumps([{'job_no': '900-01', 'image_no': 'IMG-1',
                                    'position_no': 'P1', 'weight_kg': 12.5, 'quantity': 2}]))
        self.assertEqual(resp.status_code, 201, resp.data)

        resp = self.client.get('/cnc_cutting/parts/search/', {'image_no': 'IMG-1'})
        self.assertEqual(resp.status_code, 200)
        rows = resp.data['results'] if isinstance(resp.data, dict) and 'results' in resp.data else resp.data
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row['plate_item_name'], '5 mm ST 37-2 SAC')
        self.assertEqual(row['plate_item_code'], self.item_plate.code)
        self.assertTrue(row['plate_item_is_delivered'])
        self.assertEqual(row['planning_request_item'], self.pri.id)
        self.assertEqual(row['material'], '5 mm ST 37-2 SAC')
        self.assertFalse(row['has_remnant_plate'])

        # Remnant-sourced part carries the legacy/copied fields instead
        resp = self.create_cut(
            selected_plate_id=self.remnant.id,
            parts_data=json.dumps([{'job_no': '900-01', 'image_no': 'IMG-2',
                                    'weight_kg': 5, 'quantity': 1}]))
        self.assertEqual(resp.status_code, 201, resp.data)
        resp = self.client.get('/cnc_cutting/parts/search/', {'image_no': 'IMG-2'})
        rows = resp.data['results'] if isinstance(resp.data, dict) and 'results' in resp.data else resp.data
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]['has_remnant_plate'])
        self.assertIsNone(rows[0]['planning_request_item'])
        self.assertEqual(rows[0]['material'], 'ST 44-2')

    def test_explicit_fields_win_over_derivation(self):
        resp = self.create_cut(
            planning_request_item_id=self.pri.id,
            material='ÖZEL MALZEME', thickness_mm='7.5', quantity='3')
        self.assertEqual(resp.status_code, 201, resp.data)
        task = CncTask.objects.get(key=resp.data['key'])
        self.assertEqual(task.material, 'ÖZEL MALZEME')
        self.assertEqual(task.thickness_mm, Decimal('7.5'))
        self.assertEqual(task.quantity, 3)


class PlateSourceUpdateTests(PlateFixtureMixin, TestCase):
    def _cut_with_item(self, pri=None):
        resp = self.create_cut(planning_request_item_id=(pri or self.pri).id)
        assert resp.status_code == 201, resp.data
        return CncTask.objects.get(key=resp.data['key'])

    def _cut_with_remnant(self):
        resp = self.create_cut(selected_plate_id=self.remnant.id)
        assert resp.status_code == 201, resp.data
        return CncTask.objects.get(key=resp.data['key'])

    def test_switch_item_to_remnant(self):
        task = self._cut_with_item()
        resp = self.patch_cut(task.key, selected_plate_id=self.remnant.id,
                              planning_request_item_id='')
        self.assertEqual(resp.status_code, 200, resp.data)
        task.refresh_from_db()
        self.assertIsNone(task.planning_request_item_id)
        self.assertEqual(task.plate_usage_records.count(), 1)

    def test_switch_remnant_to_item(self):
        task = self._cut_with_remnant()
        resp = self.patch_cut(task.key, planning_request_item_id=self.pri.id,
                              selected_plate_id='')
        self.assertEqual(resp.status_code, 200, resp.data)
        task.refresh_from_db()
        self.assertEqual(task.planning_request_item_id, self.pri.id)
        self.assertEqual(task.plate_usage_records.count(), 0)
        self.assertEqual(task.material, '5 mm ST 37-2 SAC')

    def test_setting_one_source_clears_other_even_without_key(self):
        task = self._cut_with_remnant()
        resp = self.patch_cut(task.key, planning_request_item_id=self.pri.id)
        self.assertEqual(resp.status_code, 200, resp.data)
        task.refresh_from_db()
        self.assertEqual(task.planning_request_item_id, self.pri.id)
        self.assertEqual(task.plate_usage_records.count(), 0)

        task2 = self._cut_with_item(pri=self.pri_comma)
        resp = self.patch_cut(task2.key, selected_plate_id=self.remnant.id)
        self.assertEqual(resp.status_code, 200, resp.data)
        task2.refresh_from_db()
        self.assertIsNone(task2.planning_request_item_id)
        self.assertEqual(task2.plate_usage_records.count(), 1)

    def test_empty_value_clears_item(self):
        task = self._cut_with_item()
        resp = self.patch_cut(task.key, planning_request_item_id='')
        self.assertEqual(resp.status_code, 200, resp.data)
        task.refresh_from_db()
        self.assertIsNone(task.planning_request_item_id)

    def test_both_sources_rejected(self):
        task = self._cut_with_item()
        resp = self.patch_cut(task.key, planning_request_item_id=self.pri_comma.id,
                              selected_plate_id=self.remnant.id)
        self.assertEqual(resp.status_code, 400)

    def test_resending_currently_linked_consumed_item_allowed(self):
        task = self._cut_with_item()
        self.pri.is_consumed = True
        self.pri.save(update_fields=['is_consumed'])
        resp = self.patch_cut(task.key, planning_request_item_id=self.pri.id)
        self.assertEqual(resp.status_code, 200, resp.data)

        # ...but a different cut still can't pick it.
        resp = self.create_cut(planning_request_item_id=self.pri.id)
        self.assertEqual(resp.status_code, 400)

    def test_patch_without_source_keys_leaves_sources_untouched(self):
        task = self._cut_with_item()
        resp = self.patch_cut(task.key, name='Yeni ad')
        self.assertEqual(resp.status_code, 200, resp.data)
        task.refresh_from_db()
        self.assertEqual(task.name, 'Yeni ad')
        self.assertEqual(task.planning_request_item_id, self.pri.id)

    def test_unmark_consumed_via_cut_update(self):
        task = self._cut_with_item()
        self.pri.is_consumed = True
        self.pri.save(update_fields=['is_consumed'])
        resp = self.patch_cut(task.key, mark_item_consumed='false')
        self.assertEqual(resp.status_code, 200, resp.data)
        self.pri.refresh_from_db()
        self.assertFalse(self.pri.is_consumed)
        self.assertIsNone(self.pri.consumed_at)
        self.assertIsNone(self.pri.consumed_by)

    def test_set_null_on_item_delete(self):
        task = self._cut_with_item()
        self.pri.delete()
        task.refresh_from_db()
        self.assertIsNone(task.planning_request_item_id)


class PlanningConsumedApiTests(PlateFixtureMixin, TestCase):
    def test_mark_consumed_standalone_no_cut_required(self):
        # Legacy retire path: the item has zero linked cuts.
        self.assertEqual(self.pri.cnc_tasks.count(), 0)
        resp = self.client.post(f'{ITEMS_URL}{self.pri.id}/mark_consumed/')
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertTrue(resp.data['is_consumed'])
        self.pri.refresh_from_db()
        self.assertTrue(self.pri.is_consumed)
        self.assertEqual(self.pri.consumed_by, self.user)

        resp = self.client.post(f'{ITEMS_URL}{self.pri.id}/mark_consumed/')
        self.assertEqual(resp.status_code, 400)

    def test_unmark_consumed(self):
        resp = self.client.post(f'{ITEMS_URL}{self.pri_consumed.id}/unmark_consumed/')
        self.assertEqual(resp.status_code, 200, resp.data)
        self.pri_consumed.refresh_from_db()
        self.assertFalse(self.pri_consumed.is_consumed)
        self.assertIsNone(self.pri_consumed.consumed_at)
        self.assertIsNone(self.pri_consumed.consumed_by)

        resp = self.client.post(f'{ITEMS_URL}{self.pri_consumed.id}/unmark_consumed/')
        self.assertEqual(resp.status_code, 400)

    def test_bulk_mark_consumed(self):
        resp = self.client.post(
            f'{ITEMS_URL}bulk_mark_consumed/',
            {'ids': [self.pri.id, self.pri_consumed.id]}, format='json')
        self.assertEqual(resp.status_code, 200, resp.data)
        self.pri.refresh_from_db()
        self.pri_consumed.refresh_from_db()
        self.assertTrue(self.pri.is_consumed)
        self.assertTrue(self.pri_consumed.is_consumed)

    @staticmethod
    def _results(resp):
        return resp.data['results'] if isinstance(resp.data, dict) and 'results' in resp.data else resp.data

    def test_is_plate_and_is_consumed_filters(self):
        resp = self.client.get(ITEMS_URL, {'fields': 'simple', 'is_plate': 'true'})
        self.assertEqual(resp.status_code, 200)
        codes = {row['item_code'] for row in self._results(resp)}
        self.assertNotIn(self.item_nonplate.code, codes)
        self.assertIn(self.item_plate.code, codes)

        resp = self.client.get(
            ITEMS_URL, {'fields': 'simple', 'is_plate': 'true', 'is_consumed': 'false'})
        ids = {row['id'] for row in self._results(resp)}
        self.assertNotIn(self.pri_consumed.id, ids)
        self.assertIn(self.pri.id, ids)

    def test_cuts_count_and_files_count_no_fanout(self):
        # Two quantity-1 cuts + one Adet=3 cut linked to the same item, plus one
        # attached file. Usage is quantity-weighted: 1 + 1 + 3 = 5.
        for _ in range(2):
            resp = self.client.post(TASKS_URL, {
                'name': 'Kesim', 'nesting_id': 'N-x',
                'planning_request_item_id': self.pri.id,
            }, format='multipart')
            self.assertEqual(resp.status_code, 201, resp.data)
        resp = self.client.post(TASKS_URL, {
            'name': 'Kesim', 'nesting_id': 'N-x3', 'quantity': '3',
            'planning_request_item_id': self.pri.id,
        }, format='multipart')
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertEqual(resp.data['plate_item']['cnc_cuts_count'], 5)

        asset = FileAsset.objects.create(file='attachments/test.pdf', uploaded_by=self.user)
        FileAttachment.objects.create(
            asset=asset, uploaded_by=self.user,
            content_type=ContentType.objects.get_for_model(PlanningRequestItem),
            object_id=self.pri.id)

        # simple list carries the quantity-weighted cut count
        resp = self.client.get(ITEMS_URL, {'fields': 'simple', 'item': self.item_plate.id})
        rows = {row['id']: row for row in self._results(resp)}
        self.assertEqual(rows[self.pri.id]['cnc_cuts_count'], 5)
        self.assertIn('is_consumed', rows[self.pri.id])

        # full list: files_count must not be inflated by cnc usage, nor the
        # usage sum by the files join
        resp = self.client.get(ITEMS_URL, {'item': self.item_plate.id})
        rows = {row['id']: row for row in self._results(resp)}
        self.assertEqual(rows[self.pri.id]['files_count'], 1)
        self.assertEqual(rows[self.pri.id]['cnc_cuts_count'], 5)

        # Legacy cut with quantity=None counts as 1
        CncTask.objects.create(key='LEG-Q1', name='legacy', planning_request_item=self.pri)
        resp = self.client.get(ITEMS_URL, {'fields': 'simple', 'item': self.item_plate.id})
        rows = {row['id']: row for row in self._results(resp)}
        self.assertEqual(rows[self.pri.id]['cnc_cuts_count'], 6)


class MaterialWaitServiceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create(username='mw-user')
        item = Item.objects.create(code='0100 0000 0008 000 000', name='8 mm S355 SAC', unit='kg')
        nonplate = Item.objects.create(code='0300 0000 0001 000 000', name='BOYA', unit='kg')
        planning_request = PlanningRequest.objects.create(
            request_number='PL-MW-1', title='t', created_by=cls.user)

        def pri(item_, job_no, delivered):
            return PlanningRequestItem.objects.create(
                planning_request=planning_request, item=item_, job_no=job_no,
                quantity=Decimal('100'), is_delivered=delivered)

        cls.pri_wait = pri(item, 'MW-1', delivered=False)
        cls.pri_ok = pri(item, 'MW-2', delivered=True)
        pri(nonplate, 'MW-1', delivered=False)  # non-plate: never counted

        def cut(key, pri_=None, done=False):
            return CncTask.objects.create(
                key=key, name=key, planning_request_item=pri_,
                completion_date=1 if done else None)

        cls.cut_wait = cut('MW-C1', cls.pri_wait)             # open + undelivered → waits
        cls.cut_done = cut('MW-C2', cls.pri_wait, done=True)  # completed → ignored
        cls.cut_ok = cut('MW-C3', cls.pri_ok)                 # delivered → no wait
        cls.cut_unlinked = cut('MW-C4')                       # no link → plain waiting

        CncPart.objects.create(cnc_task=cls.cut_wait, job_no='MW-1',
                               weight_kg=Decimal('10'), quantity=2)
        CncPart.objects.create(cnc_task=cls.cut_done, job_no='MW-1',
                               weight_kg=Decimal('5'), quantity=1)
        CncPart.objects.create(cnc_task=cls.cut_ok, job_no='MW-2',
                               weight_kg=Decimal('7'), quantity=1)
        CncPart.objects.create(cnc_task=cls.cut_unlinked, job_no='MW-1',
                               weight_kg=Decimal('3'), quantity=1)

    def test_material_wait_map(self):
        from projects.services.production_plan import _material_wait_map

        result = _material_wait_map(['MW-1', 'MW-2'])
        self.assertEqual(result['MW-1'], {'cuts_waiting': 1, 'plate_items_pending': 1})
        # MW-2's plate item is delivered and its cut is open but not blocked.
        self.assertNotIn('MW-2', result)
        self.assertEqual(_material_wait_map([]), {})

    def test_meeting_brief_cutting_material_aggregates(self):
        from projects.services.meeting_brief import _cutting

        c = _cutting(['MW-1'])
        # cut_wait parts: 2 pcs / 20 kg wait on material; cut_unlinked stays plain waiting.
        self.assertEqual(c['parts_waiting_material'], 2)
        self.assertAlmostEqual(c['weight_waiting_material'], 20.0)
        self.assertEqual(c['parts_waiting'], 3)

    def test_meeting_brief_cutting_detail_flags(self):
        from projects.services.meeting_brief import _cutting_detail

        parts = _cutting_detail(None, ['MW-1'])['parts']
        by_nest = {p['nesting']: p for p in parts}
        self.assertTrue(by_nest['MW-C1']['material_pending'])
        self.assertEqual(by_nest['MW-C1']['plate_item_code'], '0100 0000 0008 000 000')
        self.assertFalse(by_nest['MW-C2']['material_pending'])  # completed
        self.assertFalse(by_nest['MW-C4']['material_pending'])  # unlinked
