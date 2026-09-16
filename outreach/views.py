import csv
import json
from datetime import timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Q, TextField
from django.db.models.functions import Cast
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from .forms import BatchCreateForm, BatchMessageForm, RecipientUpdateForm, SenderAccountForm, TestSendForm
from .gmail import (
    GmailNotConfigured,
    build_service,
    clear_credentials,
    current_history_id,
    is_connected,
    make_flow,
    profile_email,
    save_credentials,
    send_plain_email,
)
from .models import Batch, Contact, GmailSyncState, Recipient, SenderAccount
from .services import render_text


CONTACT_IMPORT_FIELDS = ('name', 'country', 'company', 'website', 'domain', 'note')


def _safe_post_next(request):
    target = request.POST.get('next', '')
    return target if target.startswith('/') and not target.startswith('//') else reverse('outreach:report')


def _merge_contact_from_import(contact, item):
    """Enrich/update an existing contact from an imported row.

    Non-empty core values from the latest import win. Custom metadata is merged;
    non-empty imported values overwrite the same metadata key while unrelated keys
    stay untouched.
    """
    changed_fields = []

    for field_name in CONTACT_IMPORT_FIELDS:
        incoming = getattr(item, field_name)
        if incoming and getattr(contact, field_name) != incoming:
            setattr(contact, field_name, incoming)
            changed_fields.append(field_name)

    merged_metadata = dict(contact.metadata or {})
    metadata_changed = False
    for key, value in (item.metadata or {}).items():
        if value and merged_metadata.get(key) != value:
            merged_metadata[key] = value
            metadata_changed = True
    if metadata_changed:
        contact.metadata = merged_metadata
        changed_fields.append('metadata')

    if changed_fields:
        contact.save(update_fields=[*changed_fields, 'updated_at'])


@login_required
def dashboard(request):
    sender_id = request.GET.get('sender', '')
    batches = Batch.objects.select_related('sender_account').annotate(
        total=Count('recipients'),
        sent_total=Count('recipients', filter=Q(recipients__sent_at__isnull=False)),
        replied_total=Count('recipients', filter=Q(recipients__replied_at__isnull=False)),
        hopeful_total=Count('recipients', filter=Q(recipients__hope=Recipient.Hope.HOPEFUL)),
        active_total=Count('recipients', filter=Q(recipients__hope=Recipient.Hope.ACTIVE)),
    )
    recipient_totals = Recipient.objects.all()
    if sender_id:
        batches = batches.filter(sender_account_id=sender_id)
        recipient_totals = recipient_totals.filter(batch__sender_account_id=sender_id)
    totals = recipient_totals.aggregate(
        total=Count('id'),
        sent=Count('id', filter=Q(sent_at__isnull=False)),
        replied=Count('id', filter=Q(replied_at__isnull=False)),
        hopeful=Count('id', filter=Q(hope=Recipient.Hope.HOPEFUL)),
        active=Count('id', filter=Q(hope=Recipient.Hope.ACTIVE)),
    )
    sender_accounts = list(SenderAccount.objects.all())
    for sender in sender_accounts:
        sender.gmail_connected = is_connected(sender)
    context = {
        'batches': batches,
        'totals': totals,
        'sender_accounts': sender_accounts,
        'sender_filter': sender_id,
        'default_followup_days': settings.ECHOLOG_DEFAULT_FOLLOWUP_DAYS,
    }
    return render(request, 'outreach/dashboard.html', context)

@login_required
def batch_create(request):
    if request.method == 'POST':
        form = BatchCreateForm(request.POST, request.FILES)
        if form.is_valid():
            with transaction.atomic():
                batch = form.save()
                created = 0
                existing = 0
                suppressed = 0

                for position, item in enumerate(form.parsed_contacts, start=1):
                    contact, was_created = Contact.objects.get_or_create(
                        email=item.email,
                        defaults={
                            'name': item.name,
                            'country': item.country,
                            'company': item.company,
                            'website': item.website,
                            'domain': item.domain,
                            'note': item.note,
                            'metadata': item.metadata,
                        },
                    )
                    if was_created:
                        created += 1
                    else:
                        existing += 1
                        _merge_contact_from_import(contact, item)

                    recipient = Recipient.objects.create(
                        batch=batch,
                        contact=contact,
                        queue_position=position,
                    )
                    if contact.do_not_contact or contact.bounced:
                        recipient.status = Recipient.Status.SKIPPED
                        recipient.last_error = 'Suppressed: do not contact / bounced.'
                        recipient.save(update_fields=['status', 'last_error', 'updated_at'])
                        suppressed += 1

            messages.success(
                request,
                f'Batch created: {len(form.parsed_contacts)} recipients '
                f'({created} new contacts, {existing} already known, {suppressed} suppressed).',
            )
            return redirect('outreach:batch_detail', pk=batch.pk)
    else:
        default_sender = SenderAccount.objects.filter(active=True).first()
        initial = {}
        if default_sender:
            initial = {
                'sender_account': default_sender,
                'daily_limit': default_sender.daily_limit,
            }
        form = BatchCreateForm(initial=initial)
    return render(request, 'outreach/batch_form.html', {'form': form})

@login_required
def batch_detail(request, pk):
    batch = get_object_or_404(Batch.objects.select_related('sender_account'), pk=pk)
    recipients = batch.recipients.select_related('contact', 'sender_account').all()[:50]
    batch_contact_ids = batch.recipients.values_list('contact_id', flat=True)
    previous_contacts = (
        Recipient.objects.filter(contact_id__in=batch_contact_ids, sent_at__isnull=False)
        .exclude(batch=batch)
        .values('contact_id')
        .distinct()
        .count()
    )
    preview = []
    for recipient in recipients[:3]:
        preview.append({
            'to': recipient.contact.email,
            'subject': render_text(batch.subject, recipient.contact),
            'body': render_text(batch.body, recipient.contact),
        })
    test_form = TestSendForm(user=request.user)
    message_form = BatchMessageForm(instance=batch)
    return render(request, 'outreach/batch_detail.html', {
        'batch': batch,
        'recipients': recipients,
        'preview': preview,
        'test_form': test_form,
        'message_form': message_form,
        'previous_contacts': previous_contacts,
        'gmail_connected': is_connected(batch.sender_account),
        'default_followup_days': settings.ECHOLOG_DEFAULT_FOLLOWUP_DAYS,
    })

@login_required
@transaction.atomic
def batch_start(request, pk):
    if request.method != 'POST':
        return redirect('outreach:batch_detail', pk=pk)
    batch = get_object_or_404(
        Batch.objects.select_for_update().select_related('sender_account'), pk=pk
    )
    if not batch.sender_account.active:
        messages.error(request, 'This sender account is inactive.')
        return redirect('outreach:batch_detail', pk=pk)
    if not is_connected(batch.sender_account):
        messages.error(request, f'Connect Gmail for {batch.sender_account.email} before starting this batch.')
        return redirect('outreach:batch_detail', pk=pk)
    if batch.status == Batch.Status.COMPLETED:
        messages.error(request, 'Completed batches cannot be restarted. Create a new batch instead.')
        return redirect('outreach:batch_detail', pk=pk)
    Batch.objects.filter(
        status=Batch.Status.RUNNING,
        sender_account=batch.sender_account,
    ).exclude(pk=batch.pk).update(status=Batch.Status.PAUSED)
    batch.status = Batch.Status.RUNNING
    if not batch.started_at:
        batch.started_at = timezone.now()
    batch.save(update_fields=['status', 'started_at'])
    messages.success(request, 'Batch started. Any other running batch for this sender was paused.')
    return redirect('outreach:batch_detail', pk=pk)

@login_required
def batch_pause(request, pk):
    if request.method == 'POST':
        batch = get_object_or_404(Batch, pk=pk)
        if batch.status == Batch.Status.RUNNING:
            batch.status = Batch.Status.PAUSED
            batch.save(update_fields=['status'])
            messages.success(request, 'Batch paused.')
    return redirect('outreach:batch_detail', pk=pk)


@login_required
@transaction.atomic
def batch_edit_message(request, pk):
    if request.method != 'POST':
        return redirect('outreach:batch_detail', pk=pk)

    batch = get_object_or_404(Batch.objects.select_for_update(), pk=pk)
    if not batch.message_editable:
        messages.error(request, 'The batch can only be edited while it is Draft or Paused.')
        return redirect('outreach:batch_detail', pk=pk)

    form = BatchMessageForm(request.POST, instance=batch)
    if form.is_valid():
        form.save()
        messages.success(request, 'Batch sender and message updated. Unsent recipients will use these settings.')
    else:
        messages.error(request, 'Could not save the batch settings. Check the fields.')
    return redirect('outreach:batch_detail', pk=pk)

@login_required
@transaction.atomic
def batch_delete(request, pk):
    if request.method != 'POST':
        return redirect('outreach:batch_detail', pk=pk)

    batch = get_object_or_404(Batch.objects.select_for_update(), pk=pk)
    sent_qs = batch.recipients.filter(sent_at__isnull=False)

    if not sent_qs.exists():
        name = batch.name
        batch.delete()
        messages.success(request, f'Batch “{name}” deleted.')
        return redirect('outreach:dashboard')

    unsent_qs = batch.recipients.filter(sent_at__isnull=True)
    unsent_count = unsent_qs.count()
    unsent_qs.delete()

    batch.status = Batch.Status.COMPLETED
    if not batch.completed_at:
        batch.completed_at = timezone.now()
    batch.save(update_fields=['status', 'completed_at'])

    messages.success(
        request,
        f'Batch cleaned up: {unsent_count} unsent recipient'
        f'{"s" if unsent_count != 1 else ""} removed; sent history was kept.',
    )
    return redirect('outreach:batch_detail', pk=batch.pk)


@login_required
def batch_test_send(request, pk):
    batch = get_object_or_404(Batch.objects.select_related('sender_account'), pk=pk)
    form = TestSendForm(request.POST, user=request.user)
    if request.method == 'POST' and form.is_valid():
        first = batch.recipients.select_related('contact').first()
        if not first:
            messages.error(request, 'The batch has no recipients.')
        elif not is_connected(batch.sender_account):
            messages.error(request, f'Gmail is not connected for {batch.sender_account.email}.')
        else:
            subject = '[EchoLog TEST] ' + render_text(batch.subject, first.contact)
            body = render_text(batch.body, first.contact)
            try:
                send_plain_email(batch.sender_account, form.cleaned_data['email'], subject, body)
                messages.success(
                    request,
                    f'Test sent from {batch.sender_account.email} to {form.cleaned_data["email"]}.',
                )
            except Exception as exc:
                messages.error(request, f'Test send failed: {exc}')
    return redirect('outreach:batch_detail', pk=pk)

def _filtered_recipients(request):
    qs = Recipient.objects.select_related('contact', 'batch', 'batch__sender_account', 'sender_account').order_by('-sent_at', '-id')
    sender_id = request.GET.get('sender', '')
    batch_id = request.GET.get('batch', '')
    country = request.GET.get('country', '')
    status = request.GET.get('status', '')
    hope = request.GET.get('hope', '')
    q = request.GET.get('q', '').strip()

    if sender_id:
        qs = qs.filter(batch__sender_account_id=sender_id)
    if batch_id:
        qs = qs.filter(batch_id=batch_id)
    if country:
        qs = qs.filter(contact__country=country)
    if hope:
        qs = qs.filter(hope=hope)
    if q:
        qs = qs.annotate(_metadata_text=Cast('contact__metadata', TextField())).filter(
            Q(contact__name__icontains=q)
            | Q(contact__company__icontains=q)
            | Q(contact__email__icontains=q)
            | Q(contact__country__icontains=q)
            | Q(contact__website__icontains=q)
            | Q(contact__domain__icontains=q)
            | Q(contact__note__icontains=q)
            | Q(_metadata_text__icontains=q)
            | Q(notes__icontains=q)
        )
    if status == 'queued':
        qs = qs.filter(status=Recipient.Status.QUEUED)
    elif status == 'sent':
        cutoff = timezone.now() - timedelta(days=settings.ECHOLOG_DEFAULT_FOLLOWUP_DAYS)
        qs = qs.filter(sent_at__gt=cutoff, replied_at__isnull=True).exclude(
            status__in=[Recipient.Status.BOUNCED, Recipient.Status.SKIPPED]
        )
    elif status == 'followup':
        cutoff = timezone.now() - timedelta(days=settings.ECHOLOG_DEFAULT_FOLLOWUP_DAYS)
        qs = qs.filter(sent_at__lte=cutoff, replied_at__isnull=True).exclude(
            status__in=[Recipient.Status.BOUNCED, Recipient.Status.SKIPPED]
        )
    elif status == 'replied':
        qs = qs.filter(replied_at__isnull=False)
    elif status == 'bounced':
        qs = qs.filter(status=Recipient.Status.BOUNCED)
    elif status == 'skipped':
        qs = qs.filter(status=Recipient.Status.SKIPPED)

    return qs, {
        'sender': sender_id,
        'batch': batch_id,
        'country': country,
        'status': status,
        'hope': hope,
        'q': q,
    }

@login_required
def report(request):
    qs, filters = _filtered_recipients(request)
    paginator = Paginator(qs, 100)
    page_obj = paginator.get_page(request.GET.get('page'))
    params = request.GET.copy()
    params.pop('page', None)
    countries = (
        Contact.objects.exclude(country='')
        .values_list('country', flat=True)
        .distinct()
        .order_by('country')
    )
    return render(request, 'outreach/report.html', {
        'recipients': page_obj.object_list,
        'page_obj': page_obj,
        'querystring': params.urlencode(),
        'sender_accounts': SenderAccount.objects.all(),
        'batches': Batch.objects.select_related('sender_account').all(),
        'countries': countries,
        'filters': filters,
        'hope_choices': Recipient.Hope.choices,
    })


@login_required
def recipient_update(request, pk):
    recipient = get_object_or_404(Recipient, pk=pk)
    if request.method == 'POST':
        form = RecipientUpdateForm(request.POST, instance=recipient)
        if form.is_valid():
            form.save()
            messages.success(request, 'Recipient updated.')
    return redirect(_safe_post_next(request))


@login_required
def recipient_suppress(request, pk):
    recipient = get_object_or_404(Recipient.objects.select_related('contact'), pk=pk)
    if request.method == 'POST':
        recipient.contact.do_not_contact = True
        recipient.contact.save(update_fields=['do_not_contact', 'updated_at'])
        messages.success(request, f'{recipient.contact.email} marked Do not contact.')
    return redirect(_safe_post_next(request))


@login_required
def recipient_mark_bounced(request, pk):
    recipient = get_object_or_404(Recipient.objects.select_related('contact'), pk=pk)
    if request.method == 'POST':
        recipient.status = Recipient.Status.BOUNCED
        recipient.contact.bounced = True
        recipient.save(update_fields=['status', 'updated_at'])
        recipient.contact.save(update_fields=['bounced', 'updated_at'])
        messages.success(request, f'{recipient.contact.email} marked bounced and suppressed.')
    return redirect(_safe_post_next(request))


def _csv_cell(value):
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return value if value is not None else ''


@login_required
def report_export(request):
    qs, _ = _filtered_recipients(request)
    rows = list(qs.order_by('batch__name', 'queue_position'))
    metadata_keys = sorted(
        {
            str(key)
            for recipient in rows
            for key in (recipient.contact.metadata or {}).keys()
        },
        key=str.casefold,
    )

    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = 'attachment; filename="echolog-report.csv"'
    response.write('\ufeff')
    writer = csv.writer(response)
    writer.writerow([
        'Batch',
        'Sender',
        'Name',
        'Email',
        'Country',
        'Company',
        'Website',
        'Domain',
        'Note',
        *[f'Meta: {key}' for key in metadata_keys],
        'Communication status',
        'Hope',
        'Sent at',
        'Replied at',
        'Do not contact',
        'Recipient notes',
    ])

    for r in rows:
        contact = r.contact
        metadata = contact.metadata or {}
        writer.writerow([
            r.batch.name,
            str(r.sender_account or r.batch.sender_account),
            contact.name,
            contact.email,
            contact.country,
            contact.company,
            contact.website,
            contact.domain,
            contact.note,
            *[_csv_cell(metadata.get(key, '')) for key in metadata_keys],
            r.communication_label,
            r.get_hope_display() if r.hope else '',
            timezone.localtime(r.sent_at).isoformat() if r.sent_at else '',
            timezone.localtime(r.replied_at).isoformat() if r.replied_at else '',
            'yes' if contact.do_not_contact else 'no',
            r.notes,
        ])
    return response


@login_required
def sender_create(request):
    if request.method == 'POST':
        form = SenderAccountForm(request.POST)
        if form.is_valid():
            sender = form.save()
            messages.success(request, f'Sender account {sender} created. Connect Gmail to authorize it.')
            return redirect('outreach:sender_google_connect', pk=sender.pk)
    else:
        form = SenderAccountForm(initial={
            'daily_limit': getattr(settings, 'ECHOLOG_DEFAULT_SENDER_DAILY_LIMIT', settings.ECHOLOG_DAILY_LIMIT),
        })
    return render(request, 'outreach/sender_form.html', {'form': form})


@login_required
def google_connect(request):
    sender = SenderAccount.objects.filter(active=True).first()
    if not sender:
        messages.error(request, 'Create a sender account first.')
        return redirect('outreach:sender_create')
    return redirect('outreach:sender_google_connect', pk=sender.pk)


@login_required
def sender_google_connect(request, pk):
    sender = get_object_or_404(SenderAccount, pk=pk)
    redirect_uri = request.build_absolute_uri(reverse('outreach:google_callback'))
    try:
        flow = make_flow(redirect_uri)

        auth_url, state = flow.authorization_url(
            access_type='offline',
            include_granted_scopes='true',
            prompt='consent',
        )

        request.session['google_oauth_state'] = state
        request.session['google_oauth_code_verifier'] = flow.code_verifier
        request.session['google_oauth_sender_id'] = sender.pk

        return redirect(auth_url)

    except GmailNotConfigured as exc:
        messages.error(request, str(exc))
        return redirect('outreach:dashboard')


@login_required
def google_callback(request):
    state = request.session.pop('google_oauth_state', None)
    code_verifier = request.session.pop('google_oauth_code_verifier', None)
    sender_id = request.session.pop('google_oauth_sender_id', None)

    if not state or request.GET.get('state') != state or not sender_id:
        messages.error(request, 'Gmail connection failed: OAuth state mismatch.')
        return redirect('outreach:dashboard')

    sender = get_object_or_404(SenderAccount, pk=sender_id)
    redirect_uri = request.build_absolute_uri(reverse('outreach:google_callback'))

    try:
        flow = make_flow(redirect_uri, state=state)
        flow.code_verifier = code_verifier
        flow.fetch_token(authorization_response=request.build_absolute_uri())
        save_credentials(flow.credentials, sender)

        service = build_service(sender)
        connected_email = profile_email(service)

        if connected_email != sender.email.lower():
            clear_credentials(sender)
            raise GmailNotConfigured(
                f'Connected Gmail account is {connected_email}, expected {sender.email}.'
            )

        sync_state = GmailSyncState.get_for_sender(sender)
        sync_state.history_id = current_history_id(service)
        sync_state.save(update_fields=['history_id', 'updated_at'])

        messages.success(
            request,
            f'{sender.email} connected successfully; reply history baseline initialized.',
        )

    except Exception as exc:
        messages.error(request, f'Gmail connection failed: {exc}')

    return redirect('outreach:dashboard')

