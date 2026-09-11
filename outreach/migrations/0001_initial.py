import django.core.validators
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name='Batch',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=240)),
                ('subject', models.CharField(max_length=998)),
                ('body', models.TextField()),
                ('status', models.CharField(choices=[('draft', 'Draft'), ('running', 'Running'), ('paused', 'Paused'), ('completed', 'Completed')], default='draft', max_length=20)),
                ('daily_limit', models.PositiveSmallIntegerField(default=30, help_text='Per-batch ceiling. The global server limit still applies.', validators=[django.core.validators.MinValueValidator(1), django.core.validators.MaxValueValidator(2000)])),
                ('allow_recontact', models.BooleanField(default=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('started_at', models.DateTimeField(blank=True, null=True)),
                ('completed_at', models.DateTimeField(blank=True, null=True)),
            ],
            options={'ordering': ['-created_at']},
        ),
        migrations.CreateModel(
            name='GmailSyncState',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('singleton_key', models.PositiveSmallIntegerField(default=1, editable=False, unique=True)),
                ('history_id', models.CharField(blank=True, max_length=64)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
        ),
        migrations.CreateModel(
            name='Contact',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('organization_name', models.CharField(max_length=240)),
                ('contact_name', models.CharField(blank=True, max_length=240)),
                ('email', models.EmailField(max_length=254, unique=True)),
                ('country', models.CharField(blank=True, max_length=120)),
                ('segment', models.CharField(blank=True, max_length=120)),
                ('website', models.URLField(blank=True)),
                ('notes', models.TextField(blank=True)),
                ('do_not_contact', models.BooleanField(default=False)),
                ('bounced', models.BooleanField(default=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={'ordering': ['organization_name', 'email']},
        ),
        migrations.CreateModel(
            name='Recipient',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('queue_position', models.PositiveIntegerField(default=0)),
                ('status', models.CharField(choices=[('queued', 'Queued'), ('sent', 'Sent'), ('replied', 'Replied'), ('bounced', 'Bounced'), ('skipped', 'Skipped')], default='queued', max_length=20)),
                ('hope', models.CharField(blank=True, choices=[('reject', 'Reject'), ('hopeful', 'Hopeful'), ('active', 'Active')], max_length=20)),
                ('sent_at', models.DateTimeField(blank=True, null=True)),
                ('replied_at', models.DateTimeField(blank=True, null=True)),
                ('gmail_message_id', models.CharField(blank=True, max_length=255)),
                ('gmail_thread_id', models.CharField(blank=True, db_index=True, max_length=255)),
                ('gmail_rfc_message_id', models.CharField(blank=True, max_length=998)),
                ('notes', models.TextField(blank=True)),
                ('last_error', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('batch', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='recipients', to='outreach.batch')),
                ('contact', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='recipients', to='outreach.contact')),
            ],
            options={'ordering': ['batch_id', 'queue_position', 'id']},
        ),
        migrations.AddConstraint(
            model_name='recipient',
            constraint=models.UniqueConstraint(fields=('batch', 'contact'), name='unique_contact_per_batch'),
        ),
        migrations.AddIndex(
            model_name='recipient',
            index=models.Index(fields=['status', 'sent_at'], name='outreach_re_status_7ab0e0_idx'),
        ),
        migrations.AddIndex(
            model_name='recipient',
            index=models.Index(fields=['replied_at'], name='outreach_re_replied_842a0e_idx'),
        ),
    ]
