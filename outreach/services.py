from datetime import time
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from .gmail import send_plain_email
from .models import Batch, Recipient


VARIABLES = {
    '{Name}': lambda c: c.organization_name,
    '{Organization}': lambda c: c.organization_name,
    '{ContactName}': lambda c: c.contact_name,
    '{Email}': lambda c: c.email,
    '{Country}': lambda c: c.country,
}


def render_text(template, contact):
    output = template
    for token, resolver in VARIABLES.items():
        output = output.replace(token, resolver(contact) or '')
    return output


def in_send_window(now=None):
    local_now = timezone.localtime(now or timezone.now())
    if settings.ECHOLOG_SEND_WEEKDAYS_ONLY and local_now.weekday() >= 5:
        return False
    start = time.fromisoformat(settings.ECHOLOG_SEND_WINDOW_START)
    end = time.fromisoformat(settings.ECHOLOG_SEND_WINDOW_END)
    return start <= local_now.time().replace(tzinfo=None) <= end


def globally_sent_today(now=None):
    local_now = timezone.localtime(now or timezone.now())
    return Recipient.objects.filter(sent_at__date=local_now.date()).count()


def prior_sent_recipient(contact, excluding_batch):
    return (
        Recipient.objects.filter(contact=contact, sent_at__isnull=False)
        .exclude(batch=excluding_batch)
        .select_related('batch')
        .order_by('-sent_at')
        .first()
    )


def send_next(now=None, force_window=False):
    """Send at most one real email.

    Suppressed/duplicate queue entries are skipped immediately in the same run so they do
    not consume 15-minute timer slots. The function is intentionally single-message: V1
    relies on the systemd timer cadence plus the daily cap for smooth throttling.
    """
    now = now or timezone.now()
    if not force_window and not in_send_window(now):
        return {'sent': False, 'reason': 'outside_window'}

    with transaction.atomic():
        batch = (
            Batch.objects.select_for_update()
            .filter(status=Batch.Status.RUNNING)
            .order_by('started_at', 'id')
            .first()
        )
        if not batch:
            return {'sent': False, 'reason': 'no_running_batch'}

        today_count = globally_sent_today(now)
        if today_count >= settings.ECHOLOG_DAILY_LIMIT:
            return {'sent': False, 'reason': 'global_daily_limit'}

        local_date = timezone.localtime(now).date()
        batch_today = batch.recipients.filter(sent_at__date=local_date).count()
        if batch_today >= batch.daily_limit:
            return {'sent': False, 'reason': 'batch_daily_limit'}

        while True:
            recipient = (
                batch.recipients.select_for_update(skip_locked=True)
                .select_related('contact', 'batch')
                .filter(status=Recipient.Status.QUEUED)
                .order_by('queue_position', 'id')
                .first()
            )
            if not recipient:
                batch.status = Batch.Status.COMPLETED
                batch.completed_at = now
                batch.save(update_fields=['status', 'completed_at'])
                return {'sent': False, 'reason': 'batch_completed'}

            contact = recipient.contact
            if contact.do_not_contact or contact.bounced:
                recipient.status = Recipient.Status.SKIPPED
                recipient.last_error = 'Suppressed: do not contact / bounced.'
                recipient.save(update_fields=['status', 'last_error', 'updated_at'])
                continue

            prior = prior_sent_recipient(contact, batch)
            if prior and not batch.allow_recontact:
                recipient.status = Recipient.Status.SKIPPED
                recipient.last_error = (
                    f'Previously contacted in batch “{prior.batch.name}” '
                    f'on {timezone.localtime(prior.sent_at):%Y-%m-%d}.'
                )
                recipient.save(update_fields=['status', 'last_error', 'updated_at'])
                continue

            subject = render_text(batch.subject, contact)
            body = render_text(batch.body, contact)
            try:
                result = send_plain_email(contact.email, subject, body)
            except Exception as exc:
                recipient.last_error = str(exc)[:4000]
                recipient.save(update_fields=['last_error', 'updated_at'])
                return {
                    'sent': False,
                    'reason': 'gmail_error',
                    'recipient_id': recipient.id,
                    'error': str(exc),
                }

            recipient.gmail_message_id = result['id']
            recipient.gmail_thread_id = result['threadId']
            recipient.gmail_rfc_message_id = result['rfc_message_id']
            recipient.sent_at = now
            recipient.status = Recipient.Status.SENT
            recipient.last_error = ''
            recipient.save()
            return {'sent': True, 'recipient_id': recipient.id, 'email': contact.email}
