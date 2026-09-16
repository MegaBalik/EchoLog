from django.core.management.base import BaseCommand

from outreach.models import Batch
from outreach.services import send_next


class Command(BaseCommand):
    help = 'Send at most one queued outreach email per active sender account.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--force-window',
            action='store_true',
            help='Ignore weekday/time window (daily limits still apply).',
        )

    def handle(self, *args, **options):
        sender_ids = list(
            Batch.objects.filter(
                status=Batch.Status.RUNNING,
                sender_account__active=True,
            )
            .values_list('sender_account_id', flat=True)
            .distinct()
        )

        if not sender_ids:
            self.stdout.write(str({
                'sent_count': 0,
                'reason': 'no_running_batch',
            }))
            return

        results = []

        for sender_id in sender_ids:
            try:
                result = send_next(
                    force_window=options['force_window'],
                    sender_account_id=sender_id,
                )
            except Exception as exc:
                result = {
                    'sent': False,
                    'sender_account_id': sender_id,
                    'reason': 'error',
                    'error': str(exc),
                }

            results.append(result)

        output = {
            'sent_count': sum(1 for result in results if result.get('sent')),
            'results': results,
        }

        self.stdout.write(str(output))