# Phase 10 — Hosting, publication, maintenance and production preparation

Phase 10 adds private local staging for owner-approved static website versions. The project page's **Private staging and integrity checks** panel creates an inert copy under `output/staging/site-<id>/v<version>/` with a manifest of file hashes. It never starts a web server, sends files to a host, changes DNS, or makes the artifact public.

## Integrity checks, alerts and rollback

Run a check from the project page, or run local maintenance for all current staged releases:

```sh
python manage.py maintain --phase10
```

To keep the local process running, repeat checks hourly; each current release is checked at most once per UTC date:

```sh
python manage.py maintain --phase10 --watch
```

Checks compare file hashes with the staged manifest and verify bounded static content. A failure creates an owner-visible maintenance alert. The check does not change or repair files. To roll back the local staging pointer, first run a passing integrity check on the target release, then explicitly select that release in the project page. Every stage, check and rollback is recorded. None changes a public release.

The public deployment adapter is an explicit fail-closed placeholder. No hosting account, publish command, domain action or customer approval is configured in this release.

## Production preparation checklist

Before a separate production project, identify the hosting provider and account owner; verify source ownership and customer publication approval; decide the hosting region and data retention; use a registrar-managed DNS zone and record current values before changes; configure TLS with automatic renewal and verify the actual hostname and certificate chain; add appropriate security headers; select a tested backup cadence and retention; exercise restore into an isolated environment; keep credentials in an external secret store; configure monitoring, alert recipients, incident ownership and rollback procedures; and document access, rate limits, logging and deletion requirements.

AgencyOS has not performed those checks. The current application uses local SQLite and a local worker. This is not production hosting, availability, backup, TLS, privacy or security certification. No public deployment or live-domain change occurred.
