from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('projects', '0057_alter_customer_customer_info'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='customer',
            name='customer_info',
        ),
    ]
