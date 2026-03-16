from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('notifications', '0013_add_department_code_to_sales_consultation_vars'),
    ]

    operations = [
        migrations.AddField(
            model_name='notificationconfig',
            name='groups',
            field=models.JSONField(blank=True, default=list),
        ),
    ]
