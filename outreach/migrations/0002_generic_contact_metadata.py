from django.db import migrations, models


def move_segment_to_metadata(apps, schema_editor):
    Contact = apps.get_model('outreach', 'Contact')
    for contact in Contact.objects.order_by('pk').iterator():
        metadata = dict(contact.metadata or {})
        if contact.segment and 'Segment' not in metadata:
            metadata['Segment'] = contact.segment
        contact.metadata = metadata
        contact.save(update_fields=['metadata'])


def restore_segment_from_metadata(apps, schema_editor):
    Contact = apps.get_model('outreach', 'Contact')
    for contact in Contact.objects.order_by('pk').iterator():
        metadata = contact.metadata or {}
        contact.segment = str(metadata.get('Segment', ''))
        contact.save(update_fields=['segment'])


class Migration(migrations.Migration):
    dependencies = [
        ('outreach', '0001_initial'),
    ]

    operations = [
        migrations.RenameField(
            model_name='contact',
            old_name='organization_name',
            new_name='company',
        ),
        migrations.RenameField(
            model_name='contact',
            old_name='contact_name',
            new_name='name',
        ),
        migrations.RenameField(
            model_name='contact',
            old_name='notes',
            new_name='note',
        ),
        migrations.AddField(
            model_name='contact',
            name='domain',
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name='contact',
            name='metadata',
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AlterField(
            model_name='contact',
            name='company',
            field=models.CharField(blank=True, max_length=240),
        ),
        # The default makes the preceding schema state safely reversible after the
        # field is removed below.
        migrations.AlterField(
            model_name='contact',
            name='segment',
            field=models.CharField(blank=True, default='', max_length=120),
        ),
        migrations.RunPython(move_segment_to_metadata, restore_segment_from_metadata),
        migrations.RemoveField(
            model_name='contact',
            name='segment',
        ),
        migrations.AlterModelOptions(
            name='contact',
            options={'ordering': ['company', 'name', 'email']},
        ),
    ]
