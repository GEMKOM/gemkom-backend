import django.db.models.deletion
import sales.models
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('projects', '0026_add_paint_material_rate'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='OfferTemplate',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=200, unique=True)),
                ('description', models.TextField(blank=True)),
                ('is_active', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('created_by', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='offer_templates_created',
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                'verbose_name': 'Teklif Şablonu',
                'verbose_name_plural': 'Teklif Şablonları',
                'ordering': ['name'],
            },
        ),
        migrations.CreateModel(
            name='OfferTemplateNode',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.CharField(max_length=255)),
                ('description', models.TextField(blank=True)),
                ('sequence', models.PositiveIntegerField(default=1)),
                ('is_active', models.BooleanField(default=True)),
                ('template', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='nodes',
                    to='sales.offertemplate',
                )),
                ('parent', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='children',
                    to='sales.offertemplatenode',
                )),
            ],
            options={
                'verbose_name': 'Katalog Öğesi',
                'verbose_name_plural': 'Katalog Öğeleri',
                'ordering': ['template', 'sequence'],
            },
        ),
        migrations.CreateModel(
            name='SalesOffer',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('offer_no', models.CharField(db_index=True, max_length=20, unique=True)),
                ('title', models.CharField(max_length=255)),
                ('description', models.TextField(blank=True)),
                ('customer_inquiry_ref', models.CharField(blank=True, max_length=100)),
                ('delivery_date_requested', models.DateField(blank=True, null=True)),
                ('status', models.CharField(
                    choices=[
                        ('draft', 'Taslak'),
                        ('consultation', 'Danışma'),
                        ('pricing', 'Fiyatlandırma'),
                        ('pending_approval', 'Onay Bekliyor'),
                        ('approved', 'Onaylandı'),
                        ('submitted_customer', 'Müşteriye Sunuldu'),
                        ('won', 'Kazanıldı'),
                        ('lost', 'Kaybedildi'),
                        ('cancelled', 'İptal Edildi'),
                    ],
                    db_index=True,
                    default='draft',
                    max_length=30,
                )),
                ('approval_round', models.PositiveIntegerField(default=0)),
                ('submitted_to_customer_at', models.DateTimeField(blank=True, null=True)),
                ('won_at', models.DateTimeField(blank=True, null=True)),
                ('lost_at', models.DateTimeField(blank=True, null=True)),
                ('cancelled_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('customer', models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name='sales_offers',
                    to='projects.customer',
                )),
                ('converted_job_order', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='source_offer',
                    to='projects.joborder',
                )),
                ('created_by', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='sales_offers_created',
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                'verbose_name': 'Satış Teklifi',
                'verbose_name_plural': 'Satış Teklifleri',
                'ordering': ['-created_at'],
                'indexes': [
                    models.Index(fields=['status', 'customer'], name='sales_salesoffer_status_customer_idx'),
                ],
            },
        ),
        migrations.CreateModel(
            name='SalesOfferItem',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('quantity', models.PositiveIntegerField(default=1)),
                ('title_override', models.CharField(blank=True, max_length=255)),
                ('notes', models.TextField(blank=True)),
                ('sequence', models.PositiveIntegerField(default=1)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('offer', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='items',
                    to='sales.salesoffer',
                )),
                ('template_node', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name='offer_items',
                    to='sales.offertemplatenode',
                )),
                ('created_by', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='offer_items_created',
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                'verbose_name': 'Teklif Kalemi',
                'verbose_name_plural': 'Teklif Kalemleri',
                'ordering': ['offer', 'sequence'],
            },
        ),
        migrations.CreateModel(
            name='SalesOfferFile',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('file', models.FileField(
                    storage=sales.models.PrivateMediaStorage(),
                    upload_to=sales.models.sales_offer_file_upload_path,
                )),
                ('file_type', models.CharField(
                    choices=[
                        ('drawing', 'Çizim'),
                        ('specification', 'Şartname'),
                        ('quotation', 'Fiyat Teklifi'),
                        ('correspondence', 'Yazışma'),
                        ('photo', 'Fotoğraf'),
                        ('other', 'Diğer'),
                    ],
                    default='other',
                    max_length=20,
                )),
                ('name', models.CharField(blank=True, max_length=255)),
                ('description', models.TextField(blank=True)),
                ('uploaded_at', models.DateTimeField(auto_now_add=True)),
                ('offer', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='files',
                    to='sales.salesoffer',
                )),
                ('uploaded_by', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='sales_offer_files_uploaded',
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                'verbose_name': 'Teklif Dosyası',
                'verbose_name_plural': 'Teklif Dosyaları',
                'ordering': ['-uploaded_at'],
            },
        ),
        migrations.CreateModel(
            name='SalesOfferPriceRevision',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('revision_type', models.CharField(
                    choices=[
                        ('initial', 'İlk Teklif'),
                        ('sales_revision', 'Satış Revizyonu'),
                        ('approver_counter', 'Onaylayıcı Karşı Teklifi'),
                        ('approved', 'Onaylanan Fiyat'),
                    ],
                    max_length=20,
                )),
                ('amount', models.DecimalField(decimal_places=2, max_digits=16)),
                ('currency', models.CharField(
                    choices=[
                        ('TRY', 'Türk Lirası'),
                        ('USD', 'Amerikan Doları'),
                        ('EUR', 'Euro'),
                        ('GBP', 'İngiliz Sterlini'),
                    ],
                    default='EUR',
                    max_length=3,
                )),
                ('approval_round', models.PositiveIntegerField(default=1)),
                ('counter_amount', models.DecimalField(blank=True, decimal_places=2, max_digits=16, null=True)),
                ('counter_currency', models.CharField(
                    blank=True,
                    choices=[
                        ('TRY', 'Türk Lirası'),
                        ('USD', 'Amerikan Doları'),
                        ('EUR', 'Euro'),
                        ('GBP', 'İngiliz Sterlini'),
                    ],
                    max_length=3,
                )),
                ('notes', models.TextField(blank=True)),
                ('is_current', models.BooleanField(db_index=True, default=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('offer', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='price_revisions',
                    to='sales.salesoffer',
                )),
                ('created_by', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='price_revisions_created',
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                'verbose_name': 'Fiyat Revizyonu',
                'verbose_name_plural': 'Fiyat Revizyonları',
                'ordering': ['offer', 'created_at'],
                'indexes': [
                    models.Index(fields=['offer', 'is_current'], name='sales_pricerev_offer_current_idx'),
                    models.Index(fields=['offer', 'approval_round'], name='sales_pricerev_offer_round_idx'),
                ],
            },
        ),
    ]
