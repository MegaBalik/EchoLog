# EchoLog — pre-launch checklist

Use this before clicking **Start batch** on the first real campaign.

## Domain / mailbox

- [ ] `info@rb-translations.cz` is the Gmail/Google Workspace account authorized in EchoLog.
- [ ] SPF for `rb-translations.cz` is valid and includes the legitimate sending infrastructure.
- [ ] DKIM signing is enabled and passes on a normal message sent from the mailbox.
- [ ] DMARC exists; start with an appropriate monitoring policy if you are not yet ready to enforce quarantine/reject.
- [ ] Send a normal message to Gmail/Outlook and inspect headers: SPF, DKIM and DMARC should pass/alignment should be sane.

## EchoLog

- [ ] Production `DEBUG=0`.
- [ ] Strong `DJANGO_SECRET_KEY`.
- [ ] PostgreSQL configured and migrations applied.
- [ ] HTTPS works at the EchoLog hostname.
- [ ] Google OAuth redirect URI exactly matches the production callback.
- [ ] Gmail status on dashboard says connected.
- [ ] `ECHOLOG_DEFAULT_SENDER_DAILY_LIMIT=30` (or another deliberately chosen conservative value).
- [ ] Send timer active every 15 minutes.
- [ ] Reply timer active hourly.
- [ ] PostgreSQL backup timer active and at least one restore procedure documented/tested.

## First batch

- [ ] Import file preview looks right; no delimiter damage.
- [ ] Subject/body frozen as intended.
- [ ] Send a test to yourself and inspect From/Reply-To/rendering.
- [ ] First three personalized previews look correct.
- [ ] Prior-contact warning reviewed.
- [ ] Target list is genuinely relevant to the offer.
- [ ] Suppression / Do-not-contact entries are respected.
- [ ] No tracking pixel, URL shortener, or unnecessary attachment in the first cold message.
- [ ] Start with the conservative cadence; review replies/bounces before increasing anything.

## After launch

- [ ] Check Report regularly for bounces and suppress bad addresses.
- [ ] Classify replies as Reject / Hopeful / Active.
- [ ] Respect any request not to be contacted again immediately.
- [ ] Investigate unusual delivery errors before resuming/increasing volume.
