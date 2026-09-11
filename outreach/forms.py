import csv
import io
import re
from dataclasses import dataclass
from django import forms
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from .models import Batch, Recipient


@dataclass
class ParsedContact:
    name: str
    email: str
    country: str = ''


def _decode_upload(uploaded_file):
    raw = uploaded_file.read()
    for encoding in ('utf-8-sig', 'utf-8', 'cp1250', 'latin-1'):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValidationError('Could not decode the file. Please use UTF-8 text/CSV.')


def parse_contacts_file(uploaded_file):
    text = _decode_upload(uploaded_file)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        raise ValidationError('The uploaded file is empty.')

    items = []
    filename = (uploaded_file.name or '').lower()

    # CSV/TSV/semicolon mode. Header names are case-insensitive.
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
        header = [h.lower().replace(' ', '_') for h in rows[0]]
        has_header = 'email' in header and any(h in header for h in ('name', 'organization', 'organization_name'))
        data_rows = rows[1:] if has_header else rows
        if has_header:
            name_idx = next(i for i, h in enumerate(header) if h in ('name', 'organization', 'organization_name'))
            email_idx = header.index('email')
            country_idx = header.index('country') if 'country' in header else None
            for row in data_rows:
                try:
                    items.append(ParsedContact(row[name_idx], row[email_idx], row[country_idx] if country_idx is not None and country_idx < len(row) else ''))
                except IndexError:
                    raise ValidationError(f'Invalid row: {row}')
        else:
            for row in data_rows:
                if len(row) < 2:
                    raise ValidationError(f'Expected at least Name and Email: {row}')
                items.append(ParsedContact(row[0], row[1], row[2] if len(row) > 2 else ''))
    else:
        # TXT mode: Name - Email - Country (spaces around the hyphen are the delimiter).
        for number, line in enumerate(lines, start=1):
            parts = re.split(r'\s+-\s+', line, maxsplit=2)
            if len(parts) < 2:
                raise ValidationError(f'Line {number}: expected “Name - Email - Country”.')
            items.append(ParsedContact(parts[0].strip(), parts[1].strip(), parts[2].strip() if len(parts) > 2 else ''))

    normalized = []
    seen = set()
    for number, item in enumerate(items, start=1):
        if not item.name:
            raise ValidationError(f'Row {number}: Name is empty.')
        email = item.email.strip().lower()
        try:
            validate_email(email)
        except ValidationError:
            raise ValidationError(f'Row {number}: invalid email “{item.email}”.')
        if email in seen:
            continue
        seen.add(email)
        normalized.append(ParsedContact(item.name.strip(), email, item.country.strip()))
    return normalized


class BatchCreateForm(forms.ModelForm):
    contacts_file = forms.FileField(help_text='TXT: Name - Email - Country, or CSV/TSV with name,email,country.')

    class Meta:
        model = Batch
        fields = ['name', 'subject', 'body', 'daily_limit', 'allow_recontact']
        widgets = {
            'body': forms.Textarea(attrs={'rows': 14, 'placeholder': 'Hello {Name},\n\n...'}),
            'subject': forms.TextInput(attrs={'placeholder': 'A short subject'}),
        }

    def clean_contacts_file(self):
        uploaded = self.cleaned_data['contacts_file']
        if uploaded.size > 2 * 1024 * 1024:
            raise ValidationError('File is too large. 2 MB is more than enough for an EchoLog batch.')
        self.parsed_contacts = parse_contacts_file(uploaded)
        return uploaded


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
