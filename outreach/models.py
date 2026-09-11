from django.conf import settings
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from django.utils import timezone


class Contact(models.Model):
    organization_name = models.CharField(max_length=240)
    contact_name = models.CharField(max_length=240, blank=True)
    email = models.EmailField(unique=True)
    country = models.CharField(max_length=120, blank=True)
    segment = models.CharField(max_length=120, blank=True)
    website = models.URLField(blank=True)
    notes = models.TextField(blank=True)
    do_not_contact = models.BooleanField(default=False)
    bounced = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['organization_name', 'email']

    def __str__(self):
        return f'{self.organization_name} <{self.email}>'


class Batch(models.Model):
    class Status(models.TextChoices):
        DRAFT = 'draft', 'Draft'
        RUNNING = 'running', 'Running'
        PAUSED = 'paused', 'Paused'
        COMPLETED = 'completed', 'Completed'

    name = models.CharField(max_length=240)
    subject = models.CharField(max_length=998)
    body = models.TextField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    daily_limit = models.PositiveSmallIntegerField(
        default=30,
        validators=[MinValueValidator(1), MaxValueValidator(2000)],
        help_text='Per-batch ceiling. The global server limit still applies.',
    )
    allow_recontact = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.name

    @property
    def total_count(self):
        return self.recipients.count()

    @property
    def sent_count(self):
        return self.recipients.exclude(sent_at__isnull=True).count()

    @property
    def replied_count(self):
        return self.recipients.exclude(replied_at__isnull=True).count()

    @property
    def queued_count(self):
        return self.recipients.filter(status=Recipient.Status.QUEUED).count()

    @property
    def progress_percent(self):
        total = self.total_count
        return int((self.sent_count / total) * 100) if total else 0


class Recipient(models.Model):
    class Status(models.TextChoices):
        QUEUED = 'queued', 'Queued'
        SENT = 'sent', 'Sent'
        REPLIED = 'replied', 'Replied'
        BOUNCED = 'bounced', 'Bounced'
        SKIPPED = 'skipped', 'Skipped'

    class Hope(models.TextChoices):
        REJECT = 'reject', 'Reject'
        HOPEFUL = 'hopeful', 'Hopeful'
        ACTIVE = 'active', 'Active'

    batch = models.ForeignKey(Batch, on_delete=models.CASCADE, related_name='recipients')
    contact = models.ForeignKey(Contact, on_delete=models.PROTECT, related_name='recipients')
    queue_position = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.QUEUED)
    hope = models.CharField(max_length=20, choices=Hope.choices, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    replied_at = models.DateTimeField(null=True, blank=True)
    gmail_message_id = models.CharField(max_length=255, blank=True)
    gmail_thread_id = models.CharField(max_length=255, blank=True, db_index=True)
    gmail_rfc_message_id = models.CharField(max_length=998, blank=True)
    notes = models.TextField(blank=True)
    last_error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['batch_id', 'queue_position', 'id']
        constraints = [
            models.UniqueConstraint(fields=['batch', 'contact'], name='unique_contact_per_batch')
        ]
        indexes = [
            models.Index(fields=['status', 'sent_at']),
            models.Index(fields=['replied_at']),
        ]

    def __str__(self):
        return f'{self.batch}: {self.contact.email}'

    @property
    def follow_up_due(self):
        if not self.sent_at or self.replied_at or self.status in {self.Status.BOUNCED, self.Status.SKIPPED}:
            return False
        cutoff = timezone.now() - timezone.timedelta(days=settings.ECHOLOG_DEFAULT_FOLLOWUP_DAYS)
        return self.sent_at <= cutoff

    @property
    def communication_label(self):
        if self.status == self.Status.BOUNCED:
            return 'Bounced'
        if self.status == self.Status.SKIPPED:
            return 'Skipped'
        if self.replied_at:
            return 'Replied'
        if self.follow_up_due:
            return 'Follow-up due'
        if self.sent_at:
            return 'Sent'
        return 'Queued'


class GmailSyncState(models.Model):
    singleton_key = models.PositiveSmallIntegerField(default=1, unique=True, editable=False)
    history_id = models.CharField(max_length=64, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'Gmail sync @ {self.history_id or "not initialized"}'

    @classmethod
    def get_solo(cls):
        obj, _ = cls.objects.get_or_create(singleton_key=1)
        return obj
