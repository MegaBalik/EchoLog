from django.core.management.base import BaseCommand
from django.utils import timezone

from outreach.gmail import (
    build_service,
    current_history_id,
    history_added_thread_ids,
    inspect_thread,
    is_connected,
    profile_email,
    recent_mailbox_thread_ids,
)
from outreach.models import GmailSyncState, Recipient, SenderAccount


class Command(BaseCommand):
    help = 'Mark sent recipients as replied/bounced using Gmail metadata + incremental history for every sender.'

    def handle(self, *args, **options):
        senders = SenderAccount.objects.filter(active=True).order_by('id')
        if not senders.exists():
            self.stdout.write('No active sender accounts.')
            return

        summaries = []
        for sender in senders:
            if not is_connected(sender):
                summaries.append(f'{sender.email}: not connected')
                continue
            try:
                summaries.append(self._check_sender(sender))
            except Exception as exc:
                summaries.append(f'{sender.email}: ERROR {exc}')

        for summary in summaries:
            self.stdout.write(summary)

    def _check_sender(self, sender):
        service = build_service(sender)
        own_email = profile_email(service)
        state = GmailSyncState.get_for_sender(sender)

        pending = Recipient.objects.filter(
            sender_account=sender,
            sent_at__isnull=False,
            replied_at__isnull=True,
            gmail_thread_id__gt='',
        ).exclude(status__in=[Recipient.Status.BOUNCED, Recipient.Status.SKIPPED])

        if not state.history_id:
            state.history_id = current_history_id(service)
            state.save(update_fields=['history_id', 'updated_at'])
            return f'{sender.email}: initialized Gmail history baseline'

        try:
            changed_thread_ids, latest_history_id = history_added_thread_ids(
                state.history_id, service=service
            )
            recovery = False
        except Exception as exc:
            status = getattr(getattr(exc, 'resp', None), 'status', None)
            if status != 404:
                raise
            changed_thread_ids = recent_mailbox_thread_ids(service=service)
            latest_history_id = current_history_id(service)
            recovery = True

        if not pending.exists():
            state.history_id = latest_history_id
            state.save(update_fields=['history_id', 'updated_at'])
            return f'{sender.email}: no pending recipients; checkpoint advanced'

        candidate_thread_ids = set(
            pending.filter(gmail_thread_id__in=changed_thread_ids).values_list(
                'gmail_thread_id', flat=True
            )
        )
        candidates = pending.filter(gmail_thread_id__in=candidate_thread_ids).select_related('contact')

        replied = 0
        bounced = 0
        for recipient in candidates.iterator():
            info = inspect_thread(
                recipient.gmail_thread_id,
                own_email=own_email,
                service=service,
            )
            if not info['has_inbound']:
                continue
            if info['bounce']:
                recipient.status = Recipient.Status.BOUNCED
                recipient.contact.bounced = True
                recipient.contact.save(update_fields=['bounced', 'updated_at'])
                bounced += 1
            else:
                recipient.status = Recipient.Status.REPLIED
                recipient.replied_at = info['first_inbound_at'] or timezone.now()
                replied += 1
            recipient.save(update_fields=['status', 'replied_at', 'updated_at'])

        state.history_id = latest_history_id
        state.save(update_fields=['history_id', 'updated_at'])
        mode = 'recovery scan' if recovery else 'incremental history'
        return f'{sender.email} ({mode}): {replied} replies, {bounced} bounces'
