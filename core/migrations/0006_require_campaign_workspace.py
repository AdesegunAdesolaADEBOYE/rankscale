import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0005_alter_campaign_workspace_workspacemember"),
    ]

    operations = [
        migrations.AlterField(
            model_name="campaign",
            name="workspace",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="campaigns",
                to="core.workspace",
            ),
        ),
    ]
