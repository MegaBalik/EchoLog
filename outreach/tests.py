import csv
from datetime import datetime, timedelta
from io import StringIO
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .forms import parse_contacts_file
from .models import Batch, Contact, Recipient, SenderAccount
from .services import render_text, send_next


PRAGUE = ZoneInfo('Europe/Prague')


def default_sender():
    sender, _ = SenderAccount.objects.get_or_create(
        email='info@rb-translations.cz',
        defaults={'name': 'RB Translations', 'daily_limit': 30},
    )
    return sender


class ImportParserTests(TestCase):
    def test_txt_name_email_country_legacy_format(self):
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
        self.assertEqual(items[0].metadata, {})

    def test_csv_core_fields_and_custom_metadata(self):
        upload = SimpleUploadedFile(
            'batch.csv',
            (
                'Name,Email,Country,Company,Website,Priority,Specialization,CzechRelevant\n'
                'Anna Weber,anna@example.com,Germany,Nordlicht Translations,https://www.nordlicht.example,A,Medical;Technical,Yes\n'
            ).encode('utf-8'),
            content_type='text/csv',
        )
        item = parse_contacts_file(upload)[0]
        self.assertEqual(item.name, 'Anna Weber')
        self.assertEqual(item.company, 'Nordlicht Translations')
        self.assertEqual(item.domain, 'nordlicht.example')
        self.assertEqual(item.metadata, {
            'Priority': 'A',
            'Specialization': 'Medical;Technical',
            'CzechRelevant': 'Yes',
        })

    def test_csv_header_aliases_are_case_insensitive(self):
        upload = SimpleUploadedFile(
            'batch.csv',
            b'CONTACT NAME,EMAIL ADDRESS,Organisation,Notes\nEva,eva@example.com,Example Ltd,Call later\n',
            content_type='text/csv',
        )
        item = parse_contacts_file(upload)[0]
        self.assertEqual(item.name, 'Eva')
        self.assertEqual(item.company, 'Example Ltd')
        self.assertEqual(item.note, 'Call later')

    def test_csv_duplicate_email_is_deduplicated(self):
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
        self.batch = Batch.objects.create(sender_account=default_sender(), 
            name='DE',
            subject='Hello {Name} / {Company}',
            body='Country: {Country}; priority: {Priority}; org: {Organization}',
        )
        self.contact = Contact.objects.create(
            name='Anna Weber',
            company='Alpha GmbH',
            email='a@example.com',
            country='Germany',
            metadata={'Priority': 'A'},
        )
        self.recipient = Recipient.objects.create(batch=self.batch, contact=self.contact)

    def test_render_fixed_and_metadata_variables(self):
        self.assertEqual(
            render_text(self.batch.subject, self.contact),
            'Hello Anna Weber / Alpha GmbH',
        )
        self.assertEqual(
            render_text(self.batch.body, self.contact),
            'Country: Germany; priority: A; org: Alpha GmbH',
        )

    def test_name_falls_back_to_company_for_legacy_contacts(self):
        contact = Contact.objects.create(company='Legacy Agency', email='legacy@example.com')
        self.assertEqual(contact.display_name, 'Legacy Agency')
        self.assertEqual(render_text('Hello {Name}', contact), 'Hello Legacy Agency')

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
    @patch('outreach.services.is_connected', return_value=True)
    @patch('outreach.services.send_plain_email')
    def test_sends_one_message(self, mocked_send, mocked_connected):
        mocked_send.return_value = {'id': 'm1', 'threadId': 't1', 'rfc_message_id': '<x@example.com>'}
        batch = Batch.objects.create(sender_account=default_sender(), 
            name='DE', subject='Hi {Name}', body='Hello',
            status=Batch.Status.RUNNING, started_at=timezone.now(),
        )
        contact = Contact.objects.create(name='Alpha', email='a@example.com')
        recipient = Recipient.objects.create(batch=batch, contact=contact, queue_position=1)
        result = send_next(now=self.aware(2026, 9, 10, 10, 0))
        self.assertTrue(result['sent'])
        recipient.refresh_from_db()
        self.assertEqual(recipient.status, Recipient.Status.SENT)
        self.assertEqual(recipient.gmail_thread_id, 't1')
        self.assertEqual(recipient.sender_account, default_sender())
        mocked_send.assert_called_once()

    @override_settings(ECHOLOG_DAILY_LIMIT=30, ECHOLOG_SEND_WINDOW_START='08:30', ECHOLOG_SEND_WINDOW_END='16:30')
    @patch('outreach.services.is_connected', return_value=True)
    @patch('outreach.services.send_plain_email')
    def test_prior_contact_is_skipped_without_consuming_timer_slot(self, mocked_send, mocked_connected):
        mocked_send.return_value = {'id': 'm2', 'threadId': 't2', 'rfc_message_id': '<y@example.com>'}
        old = Batch.objects.create(sender_account=default_sender(), name='Old', subject='x', body='x', status=Batch.Status.COMPLETED)
        c1 = Contact.objects.create(name='Known', email='known@example.com')
        Recipient.objects.create(
            batch=old, contact=c1, status=Recipient.Status.SENT,
            sent_at=self.aware(2026, 9, 1, 10),
        )

        batch = Batch.objects.create(sender_account=default_sender(), 
            name='New', subject='Hi', body='Body',
            status=Batch.Status.RUNNING, started_at=timezone.now(),
        )
        r1 = Recipient.objects.create(batch=batch, contact=c1, queue_position=1)
        c2 = Contact.objects.create(name='Fresh', email='fresh@example.com')
        r2 = Recipient.objects.create(batch=batch, contact=c2, queue_position=2)

        result = send_next(now=self.aware(2026, 9, 10, 10))
        self.assertTrue(result['sent'])
        r1.refresh_from_db()
        r2.refresh_from_db()
        self.assertEqual(r1.status, Recipient.Status.SKIPPED)
        self.assertEqual(r2.status, Recipient.Status.SENT)
        self.assertEqual(mocked_send.call_count, 1)

    @override_settings(ECHOLOG_SEND_WINDOW_START='08:30', ECHOLOG_SEND_WINDOW_END='16:30')
    @patch('outreach.services.is_connected', return_value=True)
    @patch('outreach.services.send_plain_email')
    def test_sender_daily_limit(self, mocked_send, mocked_connected):
        sender = default_sender()
        sender.daily_limit = 1
        sender.save(update_fields=['daily_limit'])
        first_batch = Batch.objects.create(sender_account=default_sender(), name='First', subject='x', body='x')
        first_contact = Contact.objects.create(name='One', email='one@example.com')
        Recipient.objects.create(
            batch=first_batch, contact=first_contact, sender_account=sender,
            status=Recipient.Status.SENT, sent_at=self.aware(2026, 9, 10, 9),
        )

        batch = Batch.objects.create(sender_account=default_sender(), 
            name='Second', subject='x', body='x',
            status=Batch.Status.RUNNING, started_at=timezone.now(),
        )
        contact = Contact.objects.create(name='Two', email='two@example.com')
        Recipient.objects.create(batch=batch, contact=contact)
        result = send_next(now=self.aware(2026, 9, 10, 10))
        self.assertFalse(result['sent'])
        self.assertEqual(result['reason'], 'sender_daily_limit')
        mocked_send.assert_not_called()

    @override_settings(ECHOLOG_SEND_WINDOW_START='08:30', ECHOLOG_SEND_WINDOW_END='16:30')
    @patch('outreach.services.is_connected', return_value=True)
    @patch('outreach.services.send_plain_email')
    def test_outside_window_does_not_send(self, mocked_send, mocked_connected):
        result = send_next(now=self.aware(2026, 9, 10, 7))
        self.assertEqual(result['reason'], 'outside_window')
        mocked_send.assert_not_called()


class ViewTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(
            'radim', email='info@rb-translations.cz', password='test-pass-12345'
        )
        self.client.force_login(self.user)

    def test_dashboard_loads(self):
        response = self.client.get(reverse('outreach:dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'EchoLog')

    def test_batch_import_creates_core_fields_and_metadata(self):
        upload = SimpleUploadedFile(
            'contacts.csv',
            (
                'Name,Email,Country,Company,Priority,Region\n'
                'Jan Novak,jan@example.cz,Czechia,Run Club,A,Prague\n'
                'Eva Muller,eva@example.at,Austria,Alpine GmbH,B,Tyrol\n'
            ).encode('utf-8'),
            content_type='text/csv',
        )
        response = self.client.post(reverse('outreach:batch_create'), {
            'name': 'Generic test',
            'sender_account': default_sender().pk,
            'subject': 'Hello {Name} – {Priority}',
            'body': 'Hi from {Company}',
            'daily_limit': 30,
            'allow_recontact': '',
            'contacts_file': upload,
        })
        self.assertEqual(response.status_code, 302)
        batch = Batch.objects.get(name='Generic test')
        self.assertEqual(batch.recipients.count(), 2)
        contact = Contact.objects.get(email='jan@example.cz')
        self.assertEqual(contact.name, 'Jan Novak')
        self.assertEqual(contact.company, 'Run Club')
        self.assertEqual(contact.metadata, {'Priority': 'A', 'Region': 'Prague'})

    def test_existing_contact_is_enriched_and_metadata_merged(self):
        Contact.objects.create(
            name='Old Name', email='same@example.com', company='Old Co',
            metadata={'Existing': 'Keep', 'Priority': 'C'},
        )
        upload = SimpleUploadedFile(
            'contacts.csv',
            b'Name,Email,Company,Priority,Region\nNew Name,same@example.com,New Co,A,Moravia\n',
            content_type='text/csv',
        )
        response = self.client.post(reverse('outreach:batch_create'), {
            'name': 'Enrichment', 'sender_account': default_sender().pk, 'subject': 'Hi', 'body': 'Body',
            'daily_limit': 30, 'allow_recontact': '', 'contacts_file': upload,
        })
        self.assertEqual(response.status_code, 302)
        contact = Contact.objects.get(email='same@example.com')
        self.assertEqual(contact.name, 'New Name')
        self.assertEqual(contact.company, 'New Co')
        self.assertEqual(contact.metadata, {
            'Existing': 'Keep', 'Priority': 'A', 'Region': 'Moravia',
        })

    def test_report_search_finds_metadata(self):
        batch = Batch.objects.create(sender_account=default_sender(), name='Search', subject='x', body='x')
        contact = Contact.objects.create(
            name='Anna', email='anna@example.com', metadata={'Specialization': 'Medical'}
        )
        Recipient.objects.create(batch=batch, contact=contact)
        response = self.client.get(reverse('outreach:report'), {'q': 'Medical'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'anna@example.com')

    def test_report_export_flattens_metadata_columns(self):
        batch = Batch.objects.create(sender_account=default_sender(), name='Export', subject='x', body='x')
        contact = Contact.objects.create(
            name='Anna', email='anna@example.com', country='DE',
            metadata={'Priority': 'A', 'Specialization': 'Medical'},
        )
        Recipient.objects.create(batch=batch, contact=contact)
        response = self.client.get(reverse('outreach:report_export'))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8-sig')
        rows = list(csv.reader(StringIO(content)))
        self.assertIn('Meta: Priority', rows[0])
        self.assertIn('Meta: Specialization', rows[0])
        self.assertIn('A', rows[1])
        self.assertIn('Medical', rows[1])


class BatchLifecycleViewTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(
            'batch-user', email='batch@example.com', password='test-pass-12345'
        )
        self.client.force_login(self.user)

    def _recipient(self, batch, email, *, sent=False):
        contact = Contact.objects.create(name=email.split('@')[0], email=email)
        recipient = Recipient.objects.create(batch=batch, contact=contact)
        if sent:
            recipient.sender_account = batch.sender_account
            recipient.sent_at = timezone.now()
            recipient.status = Recipient.Status.SENT
            recipient.save(update_fields=['sender_account', 'sent_at', 'status', 'updated_at'])
        return recipient

    def test_message_editable_in_draft(self):
        batch = Batch.objects.create(sender_account=default_sender(), name='Draft', subject='Old', body='Old body')
        response = self.client.post(reverse('outreach:batch_edit_message', args=[batch.pk]), {
            'sender_account': default_sender().pk,
            'subject': 'New subject',
            'body': 'New body',
        })
        self.assertEqual(response.status_code, 302)
        batch.refresh_from_db()
        self.assertEqual(batch.subject, 'New subject')
        self.assertEqual(batch.body, 'New body')

    def test_message_locked_while_running(self):
        batch = Batch.objects.create(sender_account=default_sender(), 
            name='Running', subject='Old', body='Old body', status=Batch.Status.RUNNING
        )
        response = self.client.post(reverse('outreach:batch_edit_message', args=[batch.pk]), {
            'sender_account': default_sender().pk,
            'subject': 'New subject',
            'body': 'New body',
        })
        self.assertEqual(response.status_code, 302)
        batch.refresh_from_db()
        self.assertEqual(batch.subject, 'Old')
        self.assertEqual(batch.body, 'Old body')

    def test_message_editable_after_pause(self):
        batch = Batch.objects.create(sender_account=default_sender(), 
            name='Paused', subject='Old', body='Old body', status=Batch.Status.PAUSED
        )
        response = self.client.post(reverse('outreach:batch_edit_message', args=[batch.pk]), {
            'sender_account': default_sender().pk,
            'subject': 'Paused subject',
            'body': 'Paused body',
        })
        self.assertEqual(response.status_code, 302)
        batch.refresh_from_db()
        self.assertEqual(batch.subject, 'Paused subject')
        self.assertEqual(batch.body, 'Paused body')

    def test_delete_unsent_batch_removes_batch_and_recipients(self):
        batch = Batch.objects.create(sender_account=default_sender(), name='Unsent', subject='x', body='x')
        recipient = self._recipient(batch, 'queued@example.com')
        response = self.client.post(reverse('outreach:batch_delete', args=[batch.pk]))
        self.assertRedirects(response, reverse('outreach:dashboard'))
        self.assertFalse(Batch.objects.filter(pk=batch.pk).exists())
        self.assertFalse(Recipient.objects.filter(pk=recipient.pk).exists())
        self.assertTrue(Contact.objects.filter(email='queued@example.com').exists())

    def test_delete_partially_sent_batch_keeps_only_sent_history(self):
        batch = Batch.objects.create(sender_account=default_sender(), 
            name='Partial', subject='x', body='x', status=Batch.Status.PAUSED
        )
        sent = self._recipient(batch, 'sent@example.com', sent=True)
        queued = self._recipient(batch, 'queued2@example.com')
        response = self.client.post(reverse('outreach:batch_delete', args=[batch.pk]))
        self.assertRedirects(response, reverse('outreach:batch_detail', args=[batch.pk]))
        batch.refresh_from_db()
        self.assertEqual(batch.status, Batch.Status.COMPLETED)
        self.assertIsNotNone(batch.completed_at)
        self.assertTrue(Recipient.objects.filter(pk=sent.pk).exists())
        self.assertFalse(Recipient.objects.filter(pk=queued.pk).exists())
        self.assertEqual(batch.recipients.count(), 1)

    def test_report_hides_batch_and_metadata_columns_but_keeps_batch_filter(self):
        batch = Batch.objects.create(sender_account=default_sender(), name='VisibleFilterBatch', subject='x', body='x')
        contact = Contact.objects.create(
            name='Anna', email='anna-report@example.com', metadata={'Priority': 'A'}
        )
        Recipient.objects.create(batch=batch, contact=contact)
        response = self.client.get(reverse('outreach:report'))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, '<th>Metadata</th>', html=True)
        self.assertNotContains(response, '<th>Batch</th>', html=True)
        self.assertContains(response, 'VisibleFilterBatch')
        self.assertContains(response, 'name="batch"')
