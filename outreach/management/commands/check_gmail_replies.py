from django.core.management.base import BaseCommand
from django.utils import timezone
from outreach.gmail import (
    build_service,
    current_history_id,
    history_added_thread_ids,
    inspect_thread,
    profile_email,
    recent_mailbox_thread_ids,
)
from outreach.models import GmailSyncState, Recipient


class Command(BaseCommand):
    help = 'Mark sent recipients as replied/bounced using Gmail metadata + incremental history.'

    def handle(self, *args, **options):
        service = build_service()
        own_email = profile_email(service)
        state = GmailSyncState.get_solo()

        pending = Recipient.objects.filter(
            sent_at__isnull=False,
            replied_at__isnull=True,
            gmail_thread_id__gt='',
        ).exclude(status__in=[Recipient.Status.BOUNCED, Recipient.Status.SKIPPED])

        # First run only establishes the history baseline. OAuth callback normally does this already.
        if not state.history_id:
            state.history_id = current_history_id(service)
            state.save(update_fields=['history_id', 'updated_at'])
            self.stdout.write('Initialized Gmail history baseline.')
            return

        try:
            changed_thread_ids, latest_history_id = history_added_thread_ids(state.history_id, service=service)
            recovery = False
        except Exception as exc:
            # Gmail returns 404 when historyId is too old. Keep the fallback intentionally broad:
            # a recent mailbox ID scan does not fetch message bodies and can recover matching threads.
            status = getattr(getattr(exc, 'resp', None), 'status', None)
            if status != 404:
                raise
            changed_thread_ids = recent_mailbox_thread_ids(service=service)
            latest_history_id = current_history_id(service)
            recovery = True

        if not pending.exists():
            state.history_id = latest_history_id
            state.save(update_fields=['history_id', 'updated_at'])
            self.stdout.write('No pending recipients; Gmail history checkpoint advanced.')
            return

        candidate_thread_ids = set(
            pending.filter(gmail_thread_id__in=changed_thread_ids).values_list('gmail_thread_id', flat=True)
        )
        candidates = pending.filter(gmail_thread_id__in=candidate_thread_ids).select_related('contact')

        replied = 0
        bounced = 0
        for recipient in candidates.iterator():
            info = inspect_thread(recipient.gmail_thread_id, own_email=own_email, service=service)
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
        self.stdout.write(self.style.SUCCESS(f'{mode}: {replied} replies, {bounced} bounces.'))
