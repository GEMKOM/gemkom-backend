from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('projects', '0054_phase_fk_on_update_cascade'),
    ]

    operations = [
        migrations.AddField(
            model_name='customer',
            name='customer_link',
            field=models.URLField(
                blank=True,
                help_text='Müşteri klasörü veya harici bağlantı (bildirimlerde kullanılır)',
                max_length=500,
                null=True,
            ),
        ),
    ]
