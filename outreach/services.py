from datetime import time

from django.conf import settings
from django.db import transaction
from django.db.models import F, Max
from django.utils import timezone

from .gmail import is_connected, send_plain_email
from .models import Batch, Recipient


VARIABLES = {
    '{Name}': lambda c: c.display_name,
    '{Email}': lambda c: c.email,
    '{Country}': lambda c: c.country,
    '{Company}': lambda c: c.company,
    '{Website}': lambda c: c.website,
    '{Domain}': lambda c: c.domain,
    '{Note}': lambda c: c.note,
    # Backward-compatible V1 aliases.
    '{Organization}': lambda c: c.company or c.display_name,
    '{ContactName}': lambda c: c.name,
}


def render_text(template, contact):
    output = template
    for token, resolver in VARIABLES.items():
        output = output.replace(token, resolver(contact) or '')

    # Any custom imported column can be used as a template token with its original
    # header, e.g. CSV column "Priority" -> {Priority}.
    for key, value in (contact.metadata or {}).items():
        output = output.replace('{' + str(key) + '}', str(value or ''))
    return output


def in_send_window(now=None):
    local_now = timezone.localtime(now or timezone.now())
    if settings.ECHOLOG_SEND_WEEKDAYS_ONLY and local_now.weekday() >= 5:
        return False
    start = time.fromisoformat(settings.ECHOLOG_SEND_WINDOW_START)
    end = time.fromisoformat(settings.ECHOLOG_SEND_WINDOW_END)
    return start <= local_now.time().replace(tzinfo=None) <= end


def sender_sent_today(sender_account, now=None):
    local_now = timezone.localtime(now or timezone.now())
    return Recipient.objects.filter(
        sender_account=sender_account,
        sent_at__date=local_now.date(),
    ).count()


def prior_sent_recipient(contact, excluding_batch):
    return (
        Recipient.objects.filter(contact=contact, sent_at__isnull=False)
        .exclude(batch=excluding_batch)
        .select_related('batch')
        .order_by('-sent_at')
        .first()
    )


def _running_batch_ids_by_turn():
    """Return running batches in a fair order across sender accounts.

    A batch that has never sent is tried first. Afterwards the batch whose most recent
    send is oldest gets the next slot, so multiple sender accounts can progress through
    the same 15-minute worker without one permanently starving the others.
    """
    return list(
        Batch.objects.filter(
            status=Batch.Status.RUNNING,
            sender_account__active=True,
        )
        .annotate(last_sent_at=Max('recipients__sent_at'))
        .order_by(F('last_sent_at').asc(nulls_first=True), 'started_at', 'id')
        .values_list('id', flat=True)
    )


def send_next(now=None, force_window=False):
    """Send at most one real email.

    Each sender account has its own OAuth token and daily ceiling. At most one batch per
    sender is intended to be Running; batches from different senders may run in parallel.
    The worker still sends only one real message per invocation and rotates fairly across
    running batches.
    """
    now = now or timezone.now()
    if not force_window and not in_send_window(now):
        return {'sent': False, 'reason': 'outside_window'}

    candidate_ids = _running_batch_ids_by_turn()
    if not candidate_ids:
        return {'sent': False, 'reason': 'no_running_batch'}

    blocked_reasons = []
    with transaction.atomic():
        for batch_id in candidate_ids:
            batch = (
                Batch.objects.select_for_update()
                .select_related('sender_account')
                .filter(pk=batch_id, status=Batch.Status.RUNNING)
                .first()
            )
            if not batch:
                continue

            sender = batch.sender_account
            if not sender.active:
                blocked_reasons.append('sender_inactive')
                continue
            if not is_connected(sender):
                blocked_reasons.append('sender_not_connected')
                continue

            if sender_sent_today(sender, now) >= sender.daily_limit:
                blocked_reasons.append('sender_daily_limit')
                continue

            local_date = timezone.localtime(now).date()
            batch_today = batch.recipients.filter(sent_at__date=local_date).count()
            if batch_today >= batch.daily_limit:
                blocked_reasons.append('batch_daily_limit')
                continue

            while True:
                recipient = (
                    batch.recipients.select_for_update(skip_locked=True)
                    .select_related('contact', 'batch', 'sender_account')
                    .filter(status=Recipient.Status.QUEUED)
                    .order_by('queue_position', 'id')
                    .first()
                )
                if not recipient:
                    batch.status = Batch.Status.COMPLETED
                    batch.completed_at = now
                    batch.save(update_fields=['status', 'completed_at'])
                    break

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
                    result = send_plain_email(sender, contact.email, subject, body)
                except Exception as exc:
                    recipient.last_error = str(exc)[:4000]
                    recipient.save(update_fields=['last_error', 'updated_at'])
                    blocked_reasons.append('gmail_error')
                    break

                recipient.sender_account = sender
                recipient.gmail_message_id = result['id']
                recipient.gmail_thread_id = result['threadId']
                recipient.gmail_rfc_message_id = result['rfc_message_id']
                recipient.sent_at = now
                recipient.status = Recipient.Status.SENT
                recipient.last_error = ''
                recipient.save()
                return {
                    'sent': True,
                    'recipient_id': recipient.id,
                    'email': contact.email,
                    'sender': sender.email,
                }

        return {
            'sent': False,
            'reason': blocked_reasons[0] if len(set(blocked_reasons)) == 1 and blocked_reasons else 'no_eligible_running_batch',
            'blocked': blocked_reasons,
        }
