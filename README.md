# EchoLog

EchoLog is a deliberately small private outreach/reporting app:

**import batch → preview/test → Start/Pause → controlled Gmail queue → reply detection → report → Hope**

It is generic: translation agencies, sports clubs, schools, SMEs, or any other legitimate targeted outreach can use the same workflow.

## V1 features

- Login-protected Django UI
- TXT/CSV/TSV import (`Name - Email - Country` remains the simplest legacy format)
- Generic contact core: `Name, Email, Country, Company, Website, Domain, Note`
- Any additional CSV/TSV columns are stored automatically in contact JSON metadata
- Batch-specific frozen Subject + Body
- Variables for all core fields plus custom metadata headers (e.g. `{Priority}`)
- Collapsible batch queue/dashboard
- Start / Pause; one running batch per sender account
- Per-sender daily cap (default 30) + per-batch ceiling
- Working-day send window (default 08:30–16:30 Europe/Prague)
- One real message per scheduled worker run (recommended every 15 min)
- Gmail API sending from multiple explicit sender accounts, each with its own OAuth token
- Gmail metadata-only reply detection (message bodies are not fetched)
- `Follow-up due` computed automatically after 14 days without a reply
- Separate editable business outcome: `Reject / Hopeful / Active`
- Notes, country/batch/status/Hope filters and search
- Duplicate/prior-contact protection; optional explicit recontact per batch
- Global Do-not-contact suppression
- Bounce status + conservative automatic bounce recognition in matching Gmail threads
- CSV export
- Django admin
- PostgreSQL-ready production config; SQLite fallback for local development
- systemd + Nginx deployment examples

## 1. Local setup

```bash
cd EchoLog
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux/macOS:
# source .venv/bin/activate

pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Open `http://127.0.0.1:8000/` and sign in.

Without PostgreSQL environment variables EchoLog uses local SQLite automatically.

## 2. Test a batch without Gmail

You can create/import a batch, inspect previews, use reports, and test UI/database behavior before Gmail is connected. Start Batch is intentionally blocked until Gmail OAuth is connected.

Simple TXT sample:

```text
Alpha GmbH - vendor@alpha.de - Germany
Beta Language AG - info@beta.at - Austria
```

For richer data, use CSV/TSV with any subset of the fixed fields:

```csv
Name,Email,Country,Company,Website,Priority,Specialization
Anna Weber,anna@example.com,Germany,Nordlicht Translations,https://nordlicht.example,A,Medical;Technical
```

`Priority` and `Specialization` are not database columns; EchoLog stores them in `Contact.metadata`. Any other unknown header works the same way. If the same email is imported later, non-empty core fields enrich/update the existing contact and metadata keys are merged.

## 3. Gmail API / OAuth

EchoLog requests only these Gmail scopes:

- `gmail.send` — send individual messages
- `gmail.metadata` — inspect IDs, threads, labels and headers without reading message bodies

For the deployed app:

1. Create/open a Google Cloud project.
2. Enable **Gmail API**.
3. Configure Google Auth platform / OAuth consent. For a Workspace-only private app, use **Internal** audience if your Google Workspace configuration permits it.
4. Create an OAuth **Web application** client.
5. Add the production redirect URI exactly:

   `https://echolog.rb-translations.cz/google/oauth/callback/`

6. Download the client JSON and place it at:

   `/var/www/echolog/secrets/google_client_secret.json`

7. Protect it so only the app user can read it.
8. EchoLog migration 0003 creates the first `SenderAccount` from the legacy `ECHOLOG_FROM_EMAIL` setting.
9. Add further senders with **+ Sender** in the UI and authorize each mailbox separately.
10. EchoLog stores one refresh-token file per sender inside `ECHOLOG_GOOGLE_TOKEN_DIR` (the original sender keeps the existing `google_token.json`).

For local OAuth testing, add this redirect URI to the same web client if Google accepts the loopback URI for your client configuration:

`http://127.0.0.1:8000/google/oauth/callback/`

Official references:
- https://developers.google.com/workspace/gmail/api/guides/sending
- https://developers.google.com/workspace/gmail/api/guides/threads
- https://developers.google.com/workspace/gmail/api/quickstart/python

## 4. Sending cadence

Recommended production timer: run `send_outreach_queue` every 15 minutes.

```bash
python manage.py send_outreach_queue
```

The command sends **at most one real message** per invocation. It immediately skips suppressed/previously-contacted queue entries without wasting timer slots.

With the default 08:30–16:30 window and sender daily cap 30, this naturally spreads messages through the working day. Each sender has its own ceiling; the batch ceiling can further restrict a specific campaign. Different senders may have running batches at the same time, and the worker rotates fairly between them.

The queue worker refuses to send:
- outside the configured window / on weekends,
- above that sender account’s daily cap,
- above the current batch daily ceiling,
- if no eligible batch is Running,
- to Do-not-contact or bounced contacts,
- to previously contacted addresses unless the new batch explicitly allows recontact.

## 5. Reply detection

Run:

```bash
python manage.py check_gmail_replies
```

Recommended timer: hourly.

The command:
1. finds sent EchoLog recipients still waiting for a reply,
2. asks Gmail for inbound **message/thread IDs** in the relevant date range,
3. intersects those Gmail thread IDs with EchoLog's saved thread IDs,
4. fetches metadata only for matching threads,
5. marks `Replied` and records `replied_at`.

Obvious mailer-daemon/postmaster messages inside a matching thread are marked `Bounced` and suppress the contact. Because delivery-status notifications vary between providers, V1 also offers a manual **Mark bounced** action in Report.

## 6. Environment variables

Copy `.env.example` and change secrets/hostnames. Important settings:

- `ECHOLOG_DEFAULT_SENDER_DAILY_LIMIT=30` (legacy `ECHOLOG_DAILY_LIMIT` is still accepted)
- `ECHOLOG_SEND_WINDOW_START=08:30`
- `ECHOLOG_SEND_WINDOW_END=16:30`
- `ECHOLOG_SEND_WEEKDAYS_ONLY=1`
- `ECHOLOG_DEFAULT_FOLLOWUP_DAYS=14`
- `ECHOLOG_FROM_EMAIL=info@rb-translations.cz` (legacy bootstrap value for migration 0003)
- `ECHOLOG_GOOGLE_TOKEN_DIR=/var/www/echolog/secrets`

## 7. Production deployment pattern

The `deploy/` folder contains templates for:

- Gunicorn app service
- Nginx virtual host
- 15-minute send timer
- hourly reply-check timer
- optional daily PostgreSQL backup timer

The templates assume `/var/www/echolog`. Adjust user/path/domain if your VPS layout differs.

Typical sequence:

```bash
sudo mkdir -p /var/www/echolog
# copy project there
cd /var/www/echolog
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
# create .env from .env.example
.venv/bin/python manage.py migrate
.venv/bin/python manage.py collectstatic --noinput
.venv/bin/python manage.py createsuperuser
```

Then install/enable the systemd and Nginx templates from `deploy/`.

## 8. Pre-launch deliverability checklist

Before the first real campaign, verify `rb-translations.cz` has correct SPF, DKIM and DMARC and that normal mail from `info@rb-translations.cz` authenticates correctly. Keep the outreach targeted, maintain the suppression list, and do not increase volume just because Gmail's technical account limits are much higher.

See `PRELAUNCH_CHECKLIST.md`.

## Design choices deliberately left out of V1

No CRM pipeline, no email body reader, no tracking pixel/open tracking, no click tracking, no automatic follow-up sequence, no Redis/Celery, no newsletter editor, no AI classification of replies. Gmail remains the place where you read and answer messages; EchoLog remains the queue and the log.
