from datetime import datetime, timedelta
from io import BytesIO
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .forms import parse_contacts_file
from .models import Batch, Contact, Recipient
from .services import render_text, send_next


PRAGUE = ZoneInfo('Europe/Prague')


class ImportParserTests(TestCase):
    def test_txt_name_email_country(self):
        upload = SimpleUploadedFile(
            'germany.txt',
            'Alpha GmbH - hello@alpha.de - Germany\nBeta AG - info@beta.de - Germany\n'.encode('utf-8'),
            content_type='text/plain',
        )
        items = parse_contacts_file(upload)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0].name, 'Alpha GmbH')
        self.assertEqual(items[0].email, 'hello@alpha.de')
        self.assertEqual(items[0].country, 'Germany')

    def test_csv_header_and_duplicate_email(self):
        upload = SimpleUploadedFile(
            'batch.csv',
            b'name,email,country\nAlpha,a@example.com,CZ\nAlpha again,A@example.com,CZ\n',
            content_type='text/csv',
        )
        items = parse_contacts_file(upload)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].email, 'a@example.com')


class ModelAndTemplateTests(TestCase):
    def setUp(self):
        self.batch = Batch.objects.create(name='DE', subject='Hello {Name}', body='Country: {Country}')
        self.contact = Contact.objects.create(organization_name='Alpha', email='a@example.com', country='Germany')
        self.recipient = Recipient.objects.create(batch=self.batch, contact=self.contact)

    def test_render_variables(self):
        self.assertEqual(render_text(self.batch.subject, self.contact), 'Hello Alpha')
        self.assertEqual(render_text(self.batch.body, self.contact), 'Country: Germany')

    @override_settings(ECHOLOG_DEFAULT_FOLLOWUP_DAYS=14)
    def test_followup_due_after_14_days_without_reply(self):
        self.recipient.sent_at = timezone.now() - timedelta(days=15)
        self.recipient.status = Recipient.Status.SENT
        self.recipient.save()
        self.assertTrue(self.recipient.follow_up_due)
        self.recipient.replied_at = timezone.now()
        self.recipient.status = Recipient.Status.REPLIED
        self.recipient.save()
        self.assertFalse(self.recipient.follow_up_due)


class QueueTests(TestCase):
    def aware(self, y, m, d, hh, mm=0):
        return datetime(y, m, d, hh, mm, tzinfo=PRAGUE)

    @override_settings(
        ECHOLOG_DAILY_LIMIT=30,
        ECHOLOG_SEND_WINDOW_START='08:30',
        ECHOLOG_SEND_WINDOW_END='16:30',
        ECHOLOG_SEND_WEEKDAYS_ONLY=True,
    )
    @patch('outreach.services.send_plain_email')
    def test_sends_one_message(self, mocked_send):
        mocked_send.return_value = {'id': 'm1', 'threadId': 't1', 'rfc_message_id': '<x@example.com>'}
        batch = Batch.objects.create(name='DE', subject='Hi {Name}', body='Hello', status=Batch.Status.RUNNING, started_at=timezone.now())
        contact = Contact.objects.create(organization_name='Alpha', email='a@example.com')
        recipient = Recipient.objects.create(batch=batch, contact=contact, queue_position=1)
        result = send_next(now=self.aware(2026, 9, 10, 10, 0))
        self.assertTrue(result['sent'])
        recipient.refresh_from_db()
        self.assertEqual(recipient.status, Recipient.Status.SENT)
        self.assertEqual(recipient.gmail_thread_id, 't1')
        mocked_send.assert_called_once()

    @override_settings(ECHOLOG_DAILY_LIMIT=30, ECHOLOG_SEND_WINDOW_START='08:30', ECHOLOG_SEND_WINDOW_END='16:30')
    @patch('outreach.services.send_plain_email')
    def test_prior_contact_is_skipped_without_consuming_timer_slot(self, mocked_send):
        mocked_send.return_value = {'id': 'm2', 'threadId': 't2', 'rfc_message_id': '<y@example.com>'}
        old = Batch.objects.create(name='Old', subject='x', body='x', status=Batch.Status.COMPLETED)
        c1 = Contact.objects.create(organization_name='Known', email='known@example.com')
        Recipient.objects.create(batch=old, contact=c1, status=Recipient.Status.SENT, sent_at=self.aware(2026, 9, 1, 10))

        batch = Batch.objects.create(name='New', subject='Hi', body='Body', status=Batch.Status.RUNNING, started_at=timezone.now())
        r1 = Recipient.objects.create(batch=batch, contact=c1, queue_position=1)
        c2 = Contact.objects.create(organization_name='Fresh', email='fresh@example.com')
        r2 = Recipient.objects.create(batch=batch, contact=c2, queue_position=2)

        result = send_next(now=self.aware(2026, 9, 10, 10))
        self.assertTrue(result['sent'])
        r1.refresh_from_db(); r2.refresh_from_db()
        self.assertEqual(r1.status, Recipient.Status.SKIPPED)
        self.assertEqual(r2.status, Recipient.Status.SENT)
        self.assertEqual(mocked_send.call_count, 1)

    @override_settings(ECHOLOG_DAILY_LIMIT=1, ECHOLOG_SEND_WINDOW_START='08:30', ECHOLOG_SEND_WINDOW_END='16:30')
    @patch('outreach.services.send_plain_email')
    def test_global_daily_limit(self, mocked_send):
        first_batch = Batch.objects.create(name='First', subject='x', body='x')
        first_contact = Contact.objects.create(organization_name='One', email='one@example.com')
        Recipient.objects.create(batch=first_batch, contact=first_contact, status=Recipient.Status.SENT, sent_at=self.aware(2026, 9, 10, 9))

        batch = Batch.objects.create(name='Second', subject='x', body='x', status=Batch.Status.RUNNING, started_at=timezone.now())
        contact = Contact.objects.create(organization_name='Two', email='two@example.com')
        Recipient.objects.create(batch=batch, contact=contact)
        result = send_next(now=self.aware(2026, 9, 10, 10))
        self.assertFalse(result['sent'])
        self.assertEqual(result['reason'], 'global_daily_limit')
        mocked_send.assert_not_called()

    @override_settings(ECHOLOG_SEND_WINDOW_START='08:30', ECHOLOG_SEND_WINDOW_END='16:30')
    @patch('outreach.services.send_plain_email')
    def test_outside_window_does_not_send(self, mocked_send):
        result = send_next(now=self.aware(2026, 9, 10, 7))
        self.assertEqual(result['reason'], 'outside_window')
        mocked_send.assert_not_called()


class ViewTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user('radim', email='info@rb-translations.cz', password='test-pass-12345')
        self.client.force_login(self.user)

    def test_dashboard_loads(self):
        response = self.client.get(reverse('outreach:dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'EchoLog')

    def test_batch_import_creates_contacts_and_recipients(self):
        upload = SimpleUploadedFile('cz.txt', b'Club One - one@example.cz - Czechia\nClub Two - two@example.cz - Czechia\n')
        response = self.client.post(reverse('outreach:batch_create'), {
            'name': 'CZ running clubs',
            'subject': 'Hello {Name}',
            'body': 'Hi',
            'daily_limit': 30,
            'allow_recontact': '',
            'contacts_file': upload,
        })
        self.assertEqual(response.status_code, 302)
        batch = Batch.objects.get(name='CZ running clubs')
        self.assertEqual(batch.recipients.count(), 2)
