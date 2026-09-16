import csv
import io
import re
from dataclasses import dataclass, field
from urllib.parse import urlparse

from django import forms
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db.models import Q

from .models import Batch, Recipient, SenderAccount


CORE_FIELDS = ('name', 'email', 'country', 'company', 'website', 'domain', 'note')

# Import headers are case-insensitive and forgiving. Only these aliases are treated
# as fixed EchoLog fields; every other header becomes custom metadata.
CORE_HEADER_ALIASES = {
    'name': 'name',
    'contact': 'name',
    'contact_name': 'name',
    'email': 'email',
    'e_mail': 'email',
    'email_address': 'email',
    'country': 'country',
    'company': 'company',
    'company_name': 'company',
    'organization': 'company',
    'organisation': 'company',
    'organization_name': 'company',
    'organisation_name': 'company',
    'website': 'website',
    'web': 'website',
    'url': 'website',
    'domain': 'domain',
    'note': 'note',
    'notes': 'note',
}


@dataclass
class ParsedContact:
    name: str = ''
    email: str = ''
    country: str = ''
    company: str = ''
    website: str = ''
    domain: str = ''
    note: str = ''
    metadata: dict = field(default_factory=dict)


def _decode_upload(uploaded_file):
    raw = uploaded_file.read()
    for encoding in ('utf-8-sig', 'utf-8', 'cp1250', 'latin-1'):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValidationError('Could not decode the file. Please use UTF-8 text/CSV.')


def _canonical_header(value):
    value = value.strip().casefold()
    return re.sub(r'[^a-z0-9]+', '_', value).strip('_')


def _domain_from_website(website):
    website = (website or '').strip()
    if not website:
        return ''
    try:
        parsed = urlparse(website if '://' in website else f'https://{website}')
        hostname = parsed.hostname or ''
        return hostname.removeprefix('www.').lower()
    except ValueError:
        return ''


def _row_to_contact(raw_header, row):
    values = {field_name: '' for field_name in CORE_FIELDS}
    metadata = {}

    for index, header in enumerate(raw_header):
        header = header.strip()
        if not header:
            continue
        value = row[index].strip() if index < len(row) else ''
        mapped = CORE_HEADER_ALIASES.get(_canonical_header(header))
        if mapped:
            # If aliases happen to repeat, keep the last non-empty value.
            if value or not values[mapped]:
                values[mapped] = value
        elif value:
            # Preserve the user's original header spelling for display/export/template use.
            metadata[header] = value

    if not values['domain'] and values['website']:
        values['domain'] = _domain_from_website(values['website'])

    return ParsedContact(**values, metadata=metadata)


def parse_contacts_file(uploaded_file):
    text = _decode_upload(uploaded_file)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        raise ValidationError('The uploaded file is empty.')

    items = []
    filename = (uploaded_file.name or '').lower()

    # CSV/TSV/semicolon mode. A header is detected when the first row contains an
    # Email column (case-insensitive). Unknown header columns become metadata.
    if filename.endswith('.csv') or any(sep in lines[0] for sep in ('\t', ';', ',')):
        sample = '\n'.join(lines[:10])
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=',;\t')
        except csv.Error:
            dialect = csv.excel
        reader = csv.reader(io.StringIO(text), dialect)
        rows = [[cell.strip() for cell in row] for row in reader if any(cell.strip() for cell in row)]
        if not rows:
            raise ValidationError('No rows found.')

        raw_header = rows[0]
        mapped_header = [CORE_HEADER_ALIASES.get(_canonical_header(h)) for h in raw_header]
        has_header = 'email' in mapped_header

        if has_header:
            for row in rows[1:]:
                items.append(_row_to_contact(raw_header, row))
        else:
            # Headerless CSV/TSV keeps the original V1 positional format.
            for row in rows:
                if len(row) < 2:
                    raise ValidationError(f'Expected at least Name and Email: {row}')
                items.append(ParsedContact(
                    name=row[0].strip(),
                    email=row[1].strip(),
                    country=row[2].strip() if len(row) > 2 else '',
                ))
    else:
        # Legacy TXT mode: Name - Email - Country (spaces around the hyphen are the delimiter).
        for number, line in enumerate(lines, start=1):
            parts = re.split(r'\s+-\s+', line, maxsplit=2)
            if len(parts) < 2:
                raise ValidationError(f'Line {number}: expected “Name - Email - Country”.')
            items.append(ParsedContact(
                name=parts[0].strip(),
                email=parts[1].strip(),
                country=parts[2].strip() if len(parts) > 2 else '',
            ))

    normalized = []
    seen = set()
    for number, item in enumerate(items, start=1):
        email = item.email.strip().lower()
        try:
            validate_email(email)
        except ValidationError:
            raise ValidationError(f'Row {number}: invalid email “{item.email}”.')

        if email in seen:
            continue
        seen.add(email)

        item.email = email
        item.name = item.name.strip()
        item.country = item.country.strip()
        item.company = item.company.strip()
        item.website = item.website.strip()
        item.domain = item.domain.strip().lower()
        item.note = item.note.strip()
        item.metadata = {
            str(key).strip(): str(value).strip()
            for key, value in (item.metadata or {}).items()
            if str(key).strip() and str(value).strip()
        }
        normalized.append(item)

    return normalized


class SenderAccountForm(forms.ModelForm):
    class Meta:
        model = SenderAccount
        fields = ['name', 'email', 'daily_limit']
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': 'e.g. RB Translations or TRP'}),
            'email': forms.EmailInput(attrs={'placeholder': 'you@example.com'}),
        }


class BatchCreateForm(forms.ModelForm):
    contacts_file = forms.FileField(
        help_text=(
            'TXT: Name - Email - Country, or CSV/TSV. Known columns are Name, Email, '
            'Country, Company, Website, Domain and Note; every other column is saved as metadata.'
        )
    )

    class Meta:
        model = Batch
        fields = ['name', 'sender_account', 'subject', 'body', 'daily_limit', 'allow_recontact']
        widgets = {
            'body': forms.Textarea(attrs={'rows': 14, 'placeholder': 'Hello {Name},\n\n...'}),
            'subject': forms.TextInput(attrs={'placeholder': 'A short subject'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['sender_account'].queryset = SenderAccount.objects.filter(active=True)
        self.fields['sender_account'].label = 'Send from'

    def clean_contacts_file(self):
        uploaded = self.cleaned_data['contacts_file']
        if uploaded.size > 2 * 1024 * 1024:
            raise ValidationError('File is too large. 2 MB is more than enough for an EchoLog batch.')
        self.parsed_contacts = parse_contacts_file(uploaded)
        return uploaded


class BatchMessageForm(forms.ModelForm):
    class Meta:
        model = Batch
        fields = ['sender_account', 'subject', 'body']
        widgets = {
            'subject': forms.TextInput(attrs={'placeholder': 'A short subject'}),
            'body': forms.Textarea(attrs={'rows': 14, 'placeholder': 'Hello {Name},\n\n...'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        current_id = self.instance.sender_account_id if self.instance and self.instance.pk else None
        qs = SenderAccount.objects.filter(active=True)
        if current_id:
            qs = SenderAccount.objects.filter(Q(active=True) | Q(pk=current_id))
        self.fields['sender_account'].queryset = qs.distinct()
        self.fields['sender_account'].label = 'Send from'
        if self.instance and self.instance.pk and not self.instance.sender_editable:
            self.fields['sender_account'].disabled = True


class TestSendForm(forms.Form):
    email = forms.EmailField(label='Send test to')

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.is_bound:
            self.fields['email'].initial = getattr(user, 'email', '') or settings.ECHOLOG_FROM_EMAIL


class RecipientUpdateForm(forms.ModelForm):
    class Meta:
        model = Recipient
        fields = ['hope', 'notes']
        widgets = {'notes': forms.Textarea(attrs={'rows': 4})}
