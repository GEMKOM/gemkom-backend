from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase

from planning.models import FileAsset, FileAttachment, PlanningRequest, PlanningRequestItem
from procurement.models import Item, PurchaseRequest, PurchaseRequestItem
from procurement.serializers import PurchaseRequestCreateSerializer
from procurement.services import revise_purchase_request


class PurchaseRequestRevisionAttachmentTests(TestCase):
    def test_revise_and_resubmit_preserves_item_attachments_without_duplicates(self):
        user = get_user_model().objects.create_user(username='requestor')
        item = Item.objects.create(code='ITEM-1', name='Test item', unit='adet')
        planning_request = PlanningRequest.objects.create(
            request_number='GR-TEST-0001',
            title='Planning request',
            created_by=user,
        )
        planning_item = PlanningRequestItem.objects.create(
            planning_request=planning_request,
            item=item,
            job_no='JOB-1',
            quantity='1.00',
            quantity_to_purchase='1.00',
        )

        source_asset = FileAsset.objects.create(
            file='attachments/source-drawing.pdf',
            uploaded_by=user,
        )
        planning_item_ct = ContentType.objects.get_for_model(PlanningRequestItem)
        source_attachment = FileAttachment.objects.create(
            asset=source_asset,
            uploaded_by=user,
            content_type=planning_item_ct,
            object_id=planning_item.id,
        )

        original_pr = PurchaseRequest.objects.create(
            request_number='PR-TEST-0001',
            title='Original request',
            requestor=user,
            status='submitted',
        )
        original_pr.planning_request_items.add(planning_item)
        original_item = PurchaseRequestItem.objects.create(
            purchase_request=original_pr,
            item=item,
            quantity='1.00',
            planning_request_item=planning_item,
        )
        original_item_ct = ContentType.objects.get_for_model(PurchaseRequestItem)
        FileAttachment.objects.create(
            asset=source_asset,
            uploaded_by=user,
            content_type=original_item_ct,
            object_id=original_item.id,
            source_attachment=source_attachment,
        )
        extra_asset = FileAsset.objects.create(
            file='attachments/vendor-specification.pdf',
            uploaded_by=user,
        )
        FileAttachment.objects.create(
            asset=extra_asset,
            uploaded_by=user,
            content_type=original_item_ct,
            object_id=original_item.id,
        )

        draft = revise_purchase_request(original_pr, user)

        self.assertCountEqual(
            draft.data['items'][0]['file_asset_ids'],
            [source_asset.id, extra_asset.id],
        )

        serializer = PurchaseRequestCreateSerializer(
            data=draft.data,
            context={'request': SimpleNamespace(user=user)},
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)
        revised_pr = serializer.save()
        revised_item = revised_pr.request_items.get()

        self.assertEqual(revised_item.files.count(), 2)
        self.assertSetEqual(
            set(revised_item.files.values_list('asset_id', flat=True)),
            {source_asset.id, extra_asset.id},
        )
