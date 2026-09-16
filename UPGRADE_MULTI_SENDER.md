# EchoLog multi-sender upgrade

This upgrade converts the original single Gmail identity into explicit `SenderAccount` records.

## What migration 0003 does

- Creates `SenderAccount`.
- Creates the first sender from the existing legacy settings:
  - name: `RB Translations`
  - email: `ECHOLOG_FROM_EMAIL`
  - token filename: basename of `ECHOLOG_GOOGLE_TOKEN_FILE`
  - daily limit: `ECHOLOG_DEFAULT_SENDER_DAILY_LIMIT` (or legacy `ECHOLOG_DAILY_LIMIT`)
- Assigns all existing batches to that sender.
- Assigns all already-sent recipients to that sender as their historical actual sender.
- Moves the existing Gmail history checkpoint to that sender.
- Keeps the existing `google_token.json`; no Gmail reconnect is required for the original account if the token file is already present.

## Local upgrade

```bash
# activate the existing venv first
python manage.py migrate
python manage.py check
python manage.py test
```

Open EchoLog. Existing batches should show `RB Translations` as their sender. Add a second sender from **+ Sender**, then authorize that mailbox with Google OAuth.

## VPS deployment

Pause the scheduled workers during the code/database switch:

```bash
sudo systemctl stop echolog-send.timer echolog-replies.timer
cd /var/www/echolog

git pull
source .venv/bin/activate
set -a
source .env
set +a

pip install -r requirements.txt
python manage.py migrate
python manage.py check
python manage.py collectstatic --noinput

sudo systemctl restart echolog.service
sudo systemctl start echolog-send.timer echolog-replies.timer
```

The old `.env` remains compatible. Optional new setting:

```text
ECHOLOG_DEFAULT_SENDER_DAILY_LIMIT=30
ECHOLOG_GOOGLE_TOKEN_DIR=/var/www/echolog/secrets
```

If those are omitted, EchoLog falls back to legacy `ECHOLOG_DAILY_LIMIT` and to the directory containing `ECHOLOG_GOOGLE_TOKEN_FILE`.

## Operational behavior after upgrade

- A batch always belongs to one sender account.
- The sender can be changed while the batch is Draft/Paused **only until the first real message is sent**.
- The actual sender is stored on each sent recipient for immutable history and reply matching.
- One batch may run per sender account. Starting another batch for the same sender pauses the previous one.
- Different sender accounts may have running batches simultaneously.
- The 15-minute worker still sends at most one real email per invocation and rotates fairly across running senders.
- Daily limits are applied per sender and per batch.
- Reply detection runs separately for each connected sender and keeps a separate Gmail history checkpoint for each account.
