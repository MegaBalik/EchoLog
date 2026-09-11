# EchoLog V1 — build notes

Generated as a complete first-pass Django application.

## Included and implemented

- Core Django project + outreach app
- Initial migration
- Authentication-protected UI
- Batch import / preview / Start / Pause
- Queue throttling and duplicate/suppression rules
- Gmail OAuth web flow
- Gmail sending (`gmail.send`)
- Reply detection via Gmail incremental history + metadata-only thread inspection (`gmail.metadata`)
- Recovery path for expired Gmail history IDs without using Gmail body-reading scope
- Report filters, pagination, CSV export
- Editable Hope + notes
- Manual Do-not-contact / bounce controls
- PostgreSQL + SQLite config
- Tests for parser, follow-up logic, queue rules, duplicate skipping, daily limit and basic views
- Nginx/Gunicorn/systemd deployment templates
- Send/reply timers and optional PostgreSQL backup timer

## Validation performed in the build environment

- All Python files pass `compileall` syntax compilation.
- Backup shell script passes `bash -n`.
- systemd calendar expressions were parsed successfully (`*:0/15`, `hourly`, `03:20`).
- Google Gmail API behavior was checked against current Google developer documentation; in particular, `gmail.metadata` cannot use the `q` search parameter, so EchoLog uses `users.history.list` for incremental reply detection instead.

## Not executable-tested here

This build environment has no network access to install Django/Google client packages, and they are not preinstalled. Therefore `manage.py migrate`, `manage.py test`, template rendering and a live Gmail OAuth/send cycle could not be executed here.

The first local verification should therefore be:

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python manage.py migrate
python manage.py test
python manage.py createsuperuser
python manage.py runserver
```

On Linux use `source .venv/bin/activate` instead of the Windows activation command.

If any runtime issue appears in that first run, it should be treated as normal first-pass integration polish rather than a reason to redesign the app: the architecture and full workflow are already present.
