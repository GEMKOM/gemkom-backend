from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('projects', '0055_customer_customer_link'),
    ]

    operations = [
        migrations.RenameField(
            model_name='customer',
            old_name='customer_link',
            new_name='customer_info',
        ),
    ]
