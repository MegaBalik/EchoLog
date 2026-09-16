# EchoLog — VPS deployment (same pattern as RozTRP / Baltic Space)

This assumes Ubuntu/Debian, Nginx, PostgreSQL and systemd already exist on the VPS. Paths use `/var/www/echolog`; adjust only if your existing layout uses something else.

## 0. DNS first

Create an `A` record:

`echolog.rb-translations.cz -> YOUR_VPS_IP`

Do not touch the domain's MX/mail records.

## 1. Copy the project

```bash
sudo mkdir -p /var/www/echolog
sudo chown -R $USER:www-data /var/www/echolog
# copy/unzip EchoLog contents into /var/www/echolog
cd /var/www/echolog
```

## 2. Virtual environment

```bash
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
```

## 3. PostgreSQL database

Example (run as postgres):

```bash
sudo -u postgres psql
```

```sql
CREATE USER echolog WITH PASSWORD 'PUT_A_STRONG_PASSWORD_HERE';
CREATE DATABASE echolog OWNER echolog;
\q
```

## 4. `.env`

```bash
cp .env.example .env
nano .env
chmod 640 .env
```

Generate a Django secret key, for example:

```bash
.venv/bin/python -c "import secrets; print(secrets.token_urlsafe(64))"
```

Set at minimum:

```env
DJANGO_SECRET_KEY=...
DJANGO_DEBUG=0
DJANGO_ALLOWED_HOSTS=echolog.rb-translations.cz
DJANGO_CSRF_TRUSTED_ORIGINS=https://echolog.rb-translations.cz
POSTGRES_PASSWORD=...
ECHOLOG_FROM_EMAIL=info@rb-translations.cz
ECHOLOG_DEFAULT_SENDER_DAILY_LIMIT=30
```

## 5. Secrets directory

```bash
mkdir -p secrets
sudo chown -R www-data:www-data secrets
sudo chmod 700 secrets
```

Later, copy Google OAuth client JSON to:

`/var/www/echolog/secrets/google_client_secret.json`

and protect it:

```bash
sudo chown www-data:www-data secrets/google_client_secret.json
sudo chmod 600 secrets/google_client_secret.json
```

EchoLog itself creates `google_token.json` after OAuth and attempts to set mode 0600.

## 6. Django initialize

```bash
set -a
source .env
set +a
.venv/bin/python manage.py migrate
.venv/bin/python manage.py collectstatic --noinput
.venv/bin/python manage.py createsuperuser
```

Before production, also run:

```bash
.venv/bin/python manage.py check --deploy
```

Review any warnings; do not blindly ignore security warnings relevant to your setup.

## 7. Gunicorn/systemd

```bash
sudo cp deploy/echolog.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now echolog.service
sudo systemctl status echolog.service
```

If `/var/www/echolog` files are not readable by `www-data`, fix ownership/permissions consistently with your other Django deployments.

## 8. Nginx

```bash
sudo cp deploy/nginx-echolog.conf /etc/nginx/sites-available/echolog
sudo ln -s /etc/nginx/sites-available/echolog /etc/nginx/sites-enabled/echolog
sudo nginx -t
sudo systemctl reload nginx
```

At this point HTTP should reach EchoLog.

## 9. HTTPS

Use the same Certbot setup as your other sites, e.g. if Certbot is already installed:

```bash
sudo certbot --nginx -d echolog.rb-translations.cz
```

Confirm:

`https://echolog.rb-translations.cz/`

Do Gmail OAuth only after HTTPS works, because the production callback URL must exactly match what is registered at Google.

## 10. Google OAuth

In Google Cloud:

1. Enable Gmail API.
2. Configure Google Auth platform.
3. Create OAuth client type **Web application**.
4. Add authorized redirect URI exactly:

   `https://echolog.rb-translations.cz/google/oauth/callback/`

5. Download client JSON and put it in `secrets/google_client_secret.json` as described above.
6. Restart app if paths/settings changed:

```bash
sudo systemctl restart echolog.service
```

7. Sign in to EchoLog and click **Connect Gmail**.
8. Authorize `info@rb-translations.cz`.
9. Dashboard should show **Gmail connected**.

## 11. Scheduled sending / replies

Install timers:

```bash
sudo cp deploy/echolog-send.service deploy/echolog-send.timer /etc/systemd/system/
sudo cp deploy/echolog-replies.service deploy/echolog-replies.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now echolog-send.timer echolog-replies.timer
systemctl list-timers | grep echolog
```

Useful logs:

```bash
journalctl -u echolog.service -n 100 --no-pager
journalctl -u echolog-send.service -n 100 --no-pager
journalctl -u echolog-replies.service -n 100 --no-pager
```

Manual dry-ish checks (the send command can actually send if a batch is Running):

```bash
sudo -u www-data bash -lc 'cd /var/www/echolog && set -a && source .env && set +a && .venv/bin/python manage.py check_gmail_replies'
```

## 12. Database backups

Pre-create backup directory so the service user can write it:

```bash
sudo mkdir -p /var/backups/echolog
sudo chown www-data:www-data /var/backups/echolog
sudo chmod 700 /var/backups/echolog
sudo cp deploy/echolog-backup.service deploy/echolog-backup.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now echolog-backup.timer
```

Test one backup immediately:

```bash
sudo systemctl start echolog-backup.service
sudo systemctl status echolog-backup.service
sudo ls -lh /var/backups/echolog
```

### Restore example

Stop EchoLog before a destructive restore and make a fresh backup first.

```bash
gunzip -c /var/backups/echolog/echolog_YYYYMMDD_HHMMSS.sql.gz | \
  PGPASSWORD='YOUR_PASSWORD' psql -h 127.0.0.1 -U echolog -d echolog
```

For a clean restore, you may prefer recreating an empty database first. Treat restore operations carefully on production.

## 13. First real batch

Do not start with the real list immediately after deployment. Recommended sequence:

1. Import a 2–3-row dummy batch containing addresses you control.
2. Check preview variables.
3. Send a test.
4. Start the dummy batch and confirm the timer sends one message.
5. Reply to it from another mailbox and run/wait for reply checker.
6. Confirm Report changes to `Replied`.
7. Only then import the first real campaign.

Before real outreach, complete `PRELAUNCH_CHECKLIST.md` (SPF/DKIM/DMARC especially).
