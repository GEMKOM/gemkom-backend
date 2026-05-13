import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0037_add_birth_date_to_userprofile'),
        ('organization', '0003_seed_positions_and_permissions'),
    ]

    operations = [
        migrations.AddField(
            model_name='userprofile',
            name='position',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='holders',
                to='organization.position',
                help_text='Position in the org tree. Determines approval chain and permissions.',
            ),
        ),
    ]
