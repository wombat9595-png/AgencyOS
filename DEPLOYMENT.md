# AgencyOS deployment preparation

Prepared, not deployed. Recommended first controlled internal pilot: one dedicated Linux VM in **AWS Sydney (`ap-southeast-2`)**, one owner, Gunicorn behind a TLS reverse proxy, SQLite on encrypted persistent local disk, separate supervised workers and encrypted off-host backups. Customer sites must use a separate static origin; do not serve generated content as the authenticated AgencyOS application.

## Hosting decision and costs

[Lightsail regions](https://docs.aws.amazon.com/lightsail/latest/userguide/understanding-regions-and-availability-zones-in-amazon-lightsail.html) include Sydney. The [current public price list](https://aws.amazon.com/lightsail/pricing/) shows Linux public-IPv4 plans at US$12/month (2 GB) and US$24/month (4 GB). Start sizing at 4 GB for headroom; validate in the selected Sydney account before purchase. Backups, excess transfer, domains, taxes, support and external monitoring are additional. A planning allowance of US$30–60/month for a small single-host pilot is an engineering budget, not a provider quote or availability guarantee. Do not assume free-tier eligibility.

An AWS compute + managed PostgreSQL design in Sydney offers a path to multiple application hosts and managed recovery, at greater cost/complexity. It is **not currently compatible without application work**: AgencyOS uses SQLite pragmas, row objects, placeholders, `last_insert_rowid()`, indexes and migration patterns. A managed database is recommended before multiple tenants/hosts or sustained write contention. Migration plan: isolate repositories, map schemas/transactions, introduce versioned migrations, port claims/leases with row locking, copy and reconcile counts/hashes, then run the full concurrency/restore/lifecycle suite before an explicit cutover. No customer database was converted.

SQLite is appropriate only for a bounded single-host pilot with a local disk, 15-second connection busy timeouts and one-owner access. Do not put the file on NFS or use an ephemeral platform filesystem. This design has a single host failure domain and no HA claim. Region choice alone does not establish full Australian residency: AI/email/CDN, support access, logs and backups require separate vendor review.

## Prepared configuration

- `requirements-production.txt`: Gunicorn plus application dependencies. The final lock file captures the validated versions.
- `wsgi.py`: explicit pre-migrated WSGI entry point; never calls the development Flask server.
- `deploy/agencyos-web.service`: loopback Gunicorn, restart-on-failure, restrictive filesystem/user settings.
- `deploy/agencyos-worker@.service`: independently supervised Phase 4, 5 and 8 workers. Do not instantiate other numbers. Legacy Phase 3 external work remains explicitly started only.
- `deploy/agencyos-backup.*`, `deploy/agencyos-check.*`: persistent timers, encrypted backups, worker/budget/backup alerts and local artifact monitoring.
- `deploy/agencyos-failure@.service`: service failures to the system journal. External notification delivery is not configured.
- `deploy/nginx.conf.example`: explicit placeholder hostname/TLS paths, HTTP redirect, login throttling, loopback upstream. The app trusts only one forwarded protocol hop; never expose port 8000 or accept arbitrary proxy headers at it.
- `deploy/production.env.example`: paths only; actual secret material is outside Git. Run as an unprivileged dedicated OS user. Files under `/etc/agencyos/secrets` should be readable only by the service owner; directory mode 0700/files 0600.

Strict production startup requires an absolute database path, stable session secret of at least 32 characters, and explicit trusted hosts. It enables Secure/HttpOnly/SameSite cookies and eight-hour sessions. Production web setup is disabled. Provision the sole owner through `production.py create-owner --database <new-db> --username <owner> --password-file <private-file>`; it refuses to replace an existing owner. Account recovery/MFA still requires a separate operational design. An existing database with multiple users is not a multi-tenant service; only the first owner is allowed access.

## Installation, upgrades and restoration

Maintainer procedure (no resources were provisioned here): install Python 3.13 and the production lock in a dedicated venv; create persistent database/staging/backup directories owned by the service account; generate independent random session, bank-encryption and backup keys into private files; initialize a **new** database with `production.py migrate --database <new-file>`; create the owner, then validate configuration and secrets. Enable services only after explicit hosting approval, firewall/TLS review and a successful restoration exercise on the destination host.

For an upgrade: stop workers/web, create an encrypted backup, restore it to a new directory, and run `production.py migrate --database <isolated-copy> --upgrade-copy`. Test this copy and compare source records before any approved cutover. Preserve the original database and code release. The command refuses existing databases unless `--upgrade-copy` is explicitly supplied. Do not run older code against an upgraded database. For rollback, stop processes and restore the prior code plus a compatible preserved database copy; never silently overwrite an active database.

`production.py backup --database <db> --output <new-file-or-existing-backup-directory> --key-file <backup-key> --staging-root <staging>` uses SQLite's online backup API, integrity verification, a member hash manifest and Fernet authenticated encryption. Existing backup files are never overwritten. `production.py restore --database <source-reference> --input <encrypted-backup> --destination <new-directory> --key-file <key>` verifies member hashes/SQLite foreign keys and restores only into a new directory. The local safety ceiling is 128 MiB uncompressed; move to streaming encrypted object backups before exceeding it. No secret files are included: retain encryption key versions separately in approved escrow, or bank values/backups will be unrecoverable.

Proposed RPO: 24 hours, plus pre-upgrade/on-demand backups; proposed RTO: 2 hours. These are targets, not measured service guarantees. Off-host encrypted copies, retention (proposed 30 daily/12 monthly), access review and periodic restore drills need approved storage/operator setup. No existing data or backup is automatically deleted.

## Health, logging and incident response

`/healthz` reports process liveness; `/readyz` checks database/schema availability without exposing paths. Readiness does not imply a healthy provider or worker. `production.py check --database <db>` records deduplicated alerts for stale workers with queued jobs, failed/interrupted work, high AI reservations and missing/stale backups. The Launch dashboard shows these alerts; journal forwarding/external paging requires configuration and a tested recipient.

Application production request logs contain endpoint name, status and duration, excluding query strings, body, credentials and unsubscribe tokens. Nginx access logging is disabled in the example. Restrict journal access and retention. For an incident: activate Emergency Pause, stop relevant worker, preserve evidence and backups, inspect exact task/provider outcomes, rotate compromised keys, recover on an isolated copy and approve resumption. Never automatically replay uncertain paid/email/payment work. A fresh session key invalidates all sessions; keep bank/backup key versions until encrypted records are explicitly re-encrypted and recovery-tested.

## Evidence boundary

Gunicorn, strict host/session behavior, provisioning, migration copies, encrypted backup and restoration were tested locally on Python 3.13. Linux systemd/nginx configuration is prepared and statically inspected; those daemons, public TLS, cloud resources and actual provider accounts have not been exercised. A Linux-host deployment rehearsal, external monitoring test and professional security/privacy review remain launch prerequisites.
