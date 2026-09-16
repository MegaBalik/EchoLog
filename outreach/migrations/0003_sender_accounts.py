from pathlib import Path

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.core.validators
import outreach.models


def bootstrap_sender_accounts(apps, schema_editor):
    SenderAccount = apps.get_model('outreach', 'SenderAccount')
    Batch = apps.get_model('outreach', 'Batch')
    Recipient = apps.get_model('outreach', 'Recipient')
    GmailSyncState = apps.get_model('outreach', 'GmailSyncState')

    email = getattr(settings, 'ECHOLOG_FROM_EMAIL', 'info@rb-translations.cz').strip().lower()
    token_file = Path(getattr(settings, 'ECHOLOG_GOOGLE_TOKEN_FILE', 'google_token.json')).name
    daily_limit = int(getattr(settings, 'ECHOLOG_DEFAULT_SENDER_DAILY_LIMIT', getattr(settings, 'ECHOLOG_DAILY_LIMIT', 30)))

    sender, _ = SenderAccount.objects.get_or_create(
        email=email,
        defaults={
            'name': 'RB Translations',
            'token_file': token_file,
            'daily_limit': daily_limit,
            'active': True,
        },
    )

    Batch.objects.filter(sender_account__isnull=True).update(sender_account=sender)
    Recipient.objects.filter(
        sent_at__isnull=False,
        sender_account__isnull=True,
    ).update(sender_account=sender)
    GmailSyncState.objects.filter(sender_account__isnull=True).update(sender_account=sender)


class Migration(migrations.Migration):

    dependencies = [
        ('outreach', '0002_generic_contact_metadata'),
    ]

    operations = [
        migrations.CreateModel(
            name='SenderAccount',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=120)),
                ('email', models.EmailField(max_length=254, unique=True)),
                ('token_file', models.CharField(default=outreach.models.generate_sender_token_filename, editable=False, help_text='OAuth token filename inside the configured EchoLog token directory.', max_length=255, unique=True)),
                ('daily_limit', models.PositiveSmallIntegerField(default=30, validators=[django.core.validators.MinValueValidator(1), django.core.validators.MaxValueValidator(2000)])),
                ('active', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'ordering': ['name', 'email'],
            },
        ),
        migrations.AddField(
            model_name='batch',
            name='sender_account',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, related_name='batches', to='outreach.senderaccount'),
        ),
        migrations.AddField(
            model_name='recipient',
            name='sender_account',
            field=models.ForeignKey(blank=True, help_text='The actual sender used when this recipient was sent.', null=True, on_delete=django.db.models.deletion.PROTECT, related_name='sent_recipients', to='outreach.senderaccount'),
        ),
        migrations.AddField(
            model_name='gmailsyncstate',
            name='sender_account',
            field=models.OneToOneField(null=True, on_delete=django.db.models.deletion.CASCADE, related_name='gmail_sync_state', to='outreach.senderaccount'),
        ),
        migrations.RunPython(bootstrap_sender_accounts, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name='gmailsyncstate',
            name='singleton_key',
        ),
        migrations.AlterField(
            model_name='batch',
            name='sender_account',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='batches', to='outreach.senderaccount'),
        ),
        migrations.AlterField(
            model_name='gmailsyncstate',
            name='sender_account',
            field=models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='gmail_sync_state', to='outreach.senderaccount'),
        ),
        migrations.AlterField(
            model_name='batch',
            name='daily_limit',
            field=models.PositiveSmallIntegerField(default=30, help_text='Per-batch ceiling. The sender account daily limit also applies.', validators=[django.core.validators.MinValueValidator(1), django.core.validators.MaxValueValidator(2000)]),
        ),
    ]
