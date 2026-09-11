import base64
import os
from email.message import EmailMessage
from email.utils import make_msgid, parsedate_to_datetime
from pathlib import Path

from django.conf import settings

SCOPES = [
    'https://www.googleapis.com/auth/gmail.send',
    'https://www.googleapis.com/auth/gmail.metadata',
]


class GmailNotConfigured(RuntimeError):
    pass


def _imports():
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import Flow
        from googleapiclient.discovery import build
    except ImportError as exc:
        raise GmailNotConfigured('Google API packages are not installed. Run pip install -r requirements.txt.') from exc
    return Request, Credentials, Flow, build


def token_path():
    return Path(settings.ECHOLOG_GOOGLE_TOKEN_FILE)


def client_secret_path():
    return Path(settings.ECHOLOG_GOOGLE_CLIENT_SECRET_FILE)


def is_connected():
    return token_path().exists()


def clear_credentials():
    path = token_path()
    if path.exists():
        path.unlink()


def load_credentials(refresh=True):
    Request, Credentials, _, _ = _imports()
    path = token_path()
    if not path.exists():
        raise GmailNotConfigured('Gmail is not connected yet.')
    creds = Credentials.from_authorized_user_file(str(path), SCOPES)
    if refresh and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        save_credentials(creds)
    if not creds.valid:
        raise GmailNotConfigured('Stored Gmail credentials are invalid. Reconnect Gmail.')
    return creds


def save_credentials(creds):
    path = token_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(creds.to_json(), encoding='utf-8')
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def build_service():
    _, _, _, build = _imports()
    creds = load_credentials()
    return build('gmail', 'v1', credentials=creds, cache_discovery=False)


def make_flow(redirect_uri, state=None):
    _, _, Flow, _ = _imports()
    secret = client_secret_path()
    if not secret.exists():
        raise GmailNotConfigured(f'Missing Google OAuth client file: {secret}')
    flow = Flow.from_client_secrets_file(str(secret), scopes=SCOPES, state=state)
    flow.redirect_uri = redirect_uri
    return flow


def send_plain_email(to_email, subject, body, from_email=None):
    service = build_service()
    msg = EmailMessage()
    msg['To'] = to_email
    msg['From'] = from_email or settings.ECHOLOG_FROM_EMAIL
    msg['Subject'] = subject
    msg_id = make_msgid(domain=(from_email or settings.ECHOLOG_FROM_EMAIL).split('@')[-1])
    msg['Message-ID'] = msg_id
    msg.set_content(body)
    encoded = base64.urlsafe_b64encode(msg.as_bytes()).decode('ascii')
    sent = service.users().messages().send(userId='me', body={'raw': encoded}).execute()
    return {
        'id': sent.get('id', ''),
        'threadId': sent.get('threadId', ''),
        'rfc_message_id': msg_id,
    }


def get_profile(service=None):
    service = service or build_service()
    return service.users().getProfile(userId='me').execute()


def profile_email(service=None):
    return get_profile(service).get('emailAddress', '').lower()


def current_history_id(service=None):
    return str(get_profile(service).get('historyId', ''))


def history_added_thread_ids(start_history_id, service=None):
    """Return thread IDs of messages added since start_history_id + latest history ID.

    Unlike messages.list search, users.history.list is permitted with gmail.metadata.
    """
    service = service or build_service()
    thread_ids = set()
    page_token = None
    latest_history_id = str(start_history_id)
    while True:
        payload = service.users().history().list(
            userId='me',
            startHistoryId=str(start_history_id),
            historyTypes=['messageAdded'],
            maxResults=500,
            pageToken=page_token,
        ).execute()
        for history in payload.get('history', []):
            for added in history.get('messagesAdded', []):
                message = added.get('message', {})
                if message.get('threadId'):
                    thread_ids.add(message['threadId'])
        latest_history_id = str(payload.get('historyId') or latest_history_id)
        page_token = payload.get('nextPageToken')
        if not page_token:
            break
    return thread_ids, latest_history_id


def recent_mailbox_thread_ids(service=None, max_pages=20):
    """Metadata-scope recovery scan when a Gmail history ID has expired.

    messages.list without `q` is allowed with gmail.metadata. It returns IDs/thread IDs only.
    We cap the scan to max_pages * 500 newest mailbox messages; matching EchoLog threads are
    then inspected with metadata only.
    """
    service = service or build_service()
    thread_ids = set()
    page_token = None
    for _ in range(max_pages):
        payload = service.users().messages().list(
            userId='me', maxResults=500, pageToken=page_token
        ).execute()
        for message in payload.get('messages', []):
            if message.get('threadId'):
                thread_ids.add(message['threadId'])
        page_token = payload.get('nextPageToken')
        if not page_token:
            break
    return thread_ids


def _headers(message):
    return {h['name'].lower(): h['value'] for h in message.get('payload', {}).get('headers', [])}


def inspect_thread(thread_id, own_email=None, service=None):
    service = service or build_service()
    own_email = (own_email or profile_email(service)).lower()
    thread = service.users().threads().get(
        userId='me',
        id=thread_id,
        format='metadata',
        metadataHeaders=['From', 'To', 'Date', 'Message-ID', 'In-Reply-To', 'Subject'],
    ).execute()

    inbound = []
    any_bounce = False
    for message in thread.get('messages', []):
        labels = set(message.get('labelIds', []))
        headers = _headers(message)
        from_value = headers.get('from', '').lower()
        if 'SENT' in labels or own_email in from_value:
            continue
        is_bounce = 'mailer-daemon' in from_value or 'postmaster' in from_value
        any_bounce = any_bounce or is_bounce
        date_value = headers.get('date')
        parsed = None
        if date_value:
            try:
                parsed = parsedate_to_datetime(date_value)
            except (TypeError, ValueError, OverflowError):
                parsed = None
        inbound.append({'date': parsed, 'from': headers.get('from', ''), 'bounce': is_bounce})

    dates = [item['date'] for item in inbound if item['date']]
    return {
        'has_inbound': bool(inbound),
        'bounce': any_bounce,
        'first_inbound_at': min(dates) if dates else None,
    }
