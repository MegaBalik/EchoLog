from django.core.management.base import BaseCommand
from outreach.services import send_next


class Command(BaseCommand):
    help = 'Send at most one queued outreach email, rotating fairly across running sender accounts.'

    def add_arguments(self, parser):
        parser.add_argument('--force-window', action='store_true', help='Ignore weekday/time window (daily limits still apply).')

    def handle(self, *args, **options):
        try:
            result = send_next(force_window=options['force_window'])
            self.stdout.write(str(result))
        except Exception as exc:
            self.stderr.write(self.style.ERROR(f'Send failed: {exc}'))
            raise
