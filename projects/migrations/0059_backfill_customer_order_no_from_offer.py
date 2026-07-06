from django.db import migrations


def backfill_customer_order_no(apps, schema_editor):
    """
    Old offer conversions stored customer_inquiry_ref in customer_order_no (or left it empty).
    Backfill from source_offer.order_no for all linked job orders.
    """
    JobOrder = apps.get_model('projects', 'JobOrder')

    to_update = []
    for job in JobOrder.objects.filter(source_offer_id__isnull=False).select_related('source_offer'):
        offer = job.source_offer
        if not offer:
            continue
        order_no = (offer.order_no or '').strip()
        if not order_no:
            continue

        stored = (job.customer_order_no or '').strip()
        inquiry_ref = (offer.customer_inquiry_ref or '').strip()
        if not stored or (inquiry_ref and stored == inquiry_ref):
            to_update.append(JobOrder(pk=job.pk, customer_order_no=order_no))

    if to_update:
        JobOrder.objects.bulk_update(to_update, ['customer_order_no'], batch_size=500)


def reverse_backfill(apps, schema_editor):
    pass  # non-destructive reverse


class Migration(migrations.Migration):

    dependencies = [
        ('projects', '0058_remove_customer_customer_info'),
    ]

    operations = [
        migrations.RunPython(backfill_customer_order_no, reverse_code=reverse_backfill),
    ]
