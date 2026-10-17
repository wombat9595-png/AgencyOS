# AgencyOS on Benji's MacBook

AgencyOS stays private. There is no AWS, domain, tunnel, paid API or hosting prerequisite for running it. Customer website hosting is a separate decision. This branch starts from production-preparation commit `8f1ad0290c240d2682bca8c924d23fb8212a1448` and preserves the earlier branches.

## First opening

1. Download/clone branch **codex/agencyos-first-sale** into a **new folder**. Keep your existing AgencyOS folder and databases.
2. If Python 3.13 or newer is not already installed, install the free macOS installer from [python.org](https://www.python.org/downloads/macos/). No Homebrew or paid developer tool is required.
3. Open **Launch AgencyOS.command**. The first opening creates a separate `.venv-first-sale` environment and installs the pinned, free dependencies. Subsequent openings reuse it. Do not disable macOS security globally. If Finder cannot launch a downloaded command, open Terminal once in the new folder and run `bash "Launch AgencyOS.command"`.
4. The launcher opens the correct private workspace address automatically. It tries port 5000, then an available port from 5050–5059 if another app is using 5000. The exact Dashboard and Launch dashboard addresses are printed in its window; use those rather than a previously copied URL. Create your sole owner login on first opening; save a unique, strong password in your password manager.
5. Select **First customer → Apply first-sale defaults**. This applies the already approved identity and creates three immutable package offers. It does not assert an ABN, change existing tax choices or connect Gmail. Open **Sales team → Sender/GST settings** and confirm your *actual* GST status before any quote.

The launcher always binds to `127.0.0.1`. Do not change it to `0.0.0.0`, add a port forward, publish the dashboard or expose its session. Keep the launcher window open. Close it or press Control+C to stop the server and worker. The worker can continue with the browser closed; it stops if the launcher/computer stops and pauses while the Mac sleeps. No login item, launchd job or 24/7 cloud service is installed. Reopen the launcher to resume durable work. Opening it again while the same workspace is running reopens its verified local dashboard without starting another server. Startup errors remain visible in the launcher window.

Data and secrets are outside Git, in `~/Library/Application Support/AgencyOS/`. The database is `business.sqlite3`; local staging is `staging/`; encrypted backups are `backups/`. File permissions are private to your Mac user. Enable FileVault and protect your macOS account. Ordinary database records are not whole-database encrypted; Gmail tokens and imported bodies/drafts, bank configuration and backups are encrypted. Existing Sales correspondence/events remain plaintext inside the protected database. An unlocked/compromised Mac can decrypt records.

The launcher deliberately disables paid AI, external payment API calls, automated discovery, website fetching and Gmail sending even if inherited environment variables contain old credentials. Deterministic local tasks remain usable. Existing independently approved audit adapters remain available in the code; enabling real website access needs a separately reviewed operating configuration. No real site was inspected in development.

## Preserve and import an old database

The default is a **new database**, not an automatic migration of your old one. If you need your previous records, close that old AgencyOS app first and keep its original folder. One explicit import into a fresh private directory is supported:

```bash
.venv-first-sale/bin/python local_run.py --data-dir "$HOME/Library/Application Support/AgencyOS-imported" --import-database "/absolute/path/to/your/previous.db"
```

Use the path of your actual database; do not copy these example words. Import uses SQLite's online backup from a read-only source and migrates only the new copy. It refuses to overwrite an existing business database. For later openings use the **same** `--data-dir` without `--import-database`; the Finder launcher uses the default folder, so do not accidentally open two different workspaces.

Important: old encrypted bank details or Gmail records need their **original matching encryption keys**. A copied database cannot decrypt them with newly generated keys. Before importing encrypted records, arrange a secure local transfer of those keys into the matching private `.secret` files while both apps are stopped. Never send keys in chat or commit them. The app fails closed on unreadable encrypted records; it does not erase them.

Before each existing-workspace migration the launcher creates a Fernet-encrypted SQLite pre-upgrade snapshot. Daily online backups also include inert staging artifacts and checksums. Pre-upgrade `.sqlite3.enc` snapshots are database-only and can be decrypted to a *new* path with the backup key; they are distinct from the ZIP-based backups accepted by `production.py restore`. Copy the keys and encrypted backups securely to a separate owner-controlled storage device; same-disk backups do not protect against a lost Mac. Keep a dated record of matching keys. Daily backup recovery is exercised automatically in tests. Backup retention is manual; encrypted files can consume disk space, and the existing daily ZIP backup has a 128 MiB limit. Keys are intentionally not put inside the data backups.

## Connect only the dedicated Gmail

**Status on delivery: NOT CONNECTED.** Google authorisation and a real profile/inbox test cannot be completed without your participation. Mock tests are not a live connection.

1. In a browser profile signed in **only** as `benji.price.webdesign@gmail.com`, open [Google Cloud Console](https://console.cloud.google.com/). A Cloud project is an API configuration container, not hosting AgencyOS. Do not enable billing, buy services or enter payment details for this work.
2. Create a project for this private app. Enable **Gmail API** only.
3. In **Google Auth Platform** (or **APIs & Services → OAuth consent screen**), configure the audience for your personal account. Use **External / Testing** initially and add **only `benji.price.webdesign@gmail.com`** as a test user. App name can be `Benji's private AgencyOS`. Use accurate support/contact information. Do not claim Google verification.
4. Create an OAuth client of type **Desktop app**, then download its client JSON. Do not create a web-server client or public redirect service. In Testing, refresh tokens involving Gmail permissions generally expire after seven days; reconnecting may be necessary. Confirm current Google rules before relying on long-term operation.
5. In AgencyOS choose **Dedicated Gmail → Desktop OAuth JSON → Save privately**. The launcher stores a restricted copy outside Git; the download itself is still sensitive—store/remove it securely. No Gmail password is requested.
6. Choose **Connect with Google**. Initially leave the separate sending-scope checkbox **off**. Read-only scope is sufficient for inbox and conversation reads; local drafts do not require Gmail modification permission. Inspect the consent screen and sign in as the dedicated account only. The app rejects any other account *before storing tokens or reading messages*. If you choose the wrong account, review/remove the attempted grant in your Google account; the app does not automatically revoke another account's existing permissions.
7. Google returns to this app's loopback callback. After Google confirms the exact account profile, AgencyOS displays **Connected**. Choose **Queue inbox check** to perform the first authorised read. Review the job result and imported message if present. An empty inbox is a valid read. This is the required owner-dependent real-account test; no email is sent.
8. Enable five-minute local polling if desired. The optional checkbox also prepares local reply drafts for unambiguously matched messages. You can read a selected conversation (up to 20 messages) with its explicit button. The normal poll reads at most 20 messages per page from the last 30 days of the inbox, carrying the next page cursor into the next poll. It does not scan archives/spam or import all history. Attachments and HTML-only bodies are not interpreted; inspect them in Gmail yourself.
9. **Disconnect** deletes local tokens and cancels pending poll jobs while preserving correspondence. Select **revoke at Google** to revoke the app grant too. If Google is unavailable, uncheck revocation to disconnect locally, then remove access at [Google Account → Third-party connections](https://myaccount.google.com/connections). Lost-key recovery requires restoring the key or disconnecting and signing in again; never silently replace a key.

Gmail read-only is a restricted scope; sending is a separate scope. Private/personal-use verification exceptions, testing limits, Limited Use obligations and any assessment requirements must be checked against current Google rules. Do not change the app to a public product to bypass them. We could not retrieve the current policy pages through this development environment's proxy; see `FIRST_SALE_POLICY_REVIEW.md`. No paid verification, service or purchase is authorised.

## Sending remains disabled

No live cold outreach is supported by the Gmail adapter. The installed sending path is for **one exact owner-reviewed reply to an imported message**, with matching thread, safe headers, a current policy attestation, explicit recipient consent, suppression checks and a daily ceiling (maximum ten). An uncertain submission is locked for owner investigation in Gmail Sent, never automatically retried. A Gmail send receipt establishes submission, not delivery.

The private launcher forces sending **off**. Saving a policy or requesting `gmail.send` does not enable it. Future activation requires a separate owner-authorised operating configuration after legal/provider review and a controlled real-provider test. Do not turn it on for initial setup. Fully automatic routine sending, Gmail labels and provider bounce/complaint ingestion are not implemented. Replies can be manually reviewed/sent in the dedicated Gmail UI after the owner establishes eligibility; do not mark a local draft as sent without evidence.

## The first customer

- Begin with a genuine referral, inbound enquiry or another documented eligible contact. Record the actual business in Leads, or use authorised CSV intake with provenance and source review. There is no purchased database or claimed nationwide acquired lead list.
- Use First customer/Sales to select one package, research it and review the draft. Source permission, website audit permission and permission to email are separate.
- Match Gmail correspondence, prepare/edit a reply and gather the short questionnaire. A customer's interest is not acceptance. Record confirmation references accurately.
- Prepare a proposal from the confirmed questionnaire, review the immutable quote, and record actual acceptance against the exact quote hash. GST must match your real status. The customer sees clearly limited scope and exclusions.
- Generate the local website, inspect its automated QA, apply a revision and approve the exact version. The three styles have distinct composition/typography; customer services and approved text replace generic package descriptions. Supplied logo/images and arbitrary extra pages are not automatically incorporated. Customer-approved email/phone details produce plain mailto/tel links. Contact forms are non-sending previews, not working backend forms. Preview navigation uses a ten-minute, read-only capability for the exact version; it does not share the dashboard login.
- Prepare the invoice draft. **Live invoice issuance remains blocked**; the existing approval/PDF/payment workflow is synthetic-only. Have the owner resolve the business/tax checklist and issue a compliant invoice through an approved process before requesting real payment.
- For a genuine bank transfer, verify money in your bank independently and record it in First customer against the accepted real quote with a unique transaction reference. This is a traceable **owner attestation**, not a bank API connection. Payment claims are not revenue. No transfer/withdrawal/refund is executed.
- Approve delivery preparation for the exact reviewed static release, download its ZIP and agree on customer-owned hosting/domain and a tested contact solution before publication. No publication is automatic.

Engineering QA is already automated. You do not need to repeat the test suite or debug the setup. Your participation is limited to the real account authorisation, accurate business/tax details, customer commitments, independent receipt confirmation and final publication/delivery approvals.

For a “Not Found” page or a previously copied URL, see [startup recovery](STARTUP_RECOVERY.md). The main dashboard URLs now accept an optional final slash.

## Cannot sign in?

Open **Recover AgencyOS Login.command** to back up and reset the existing owner account in the selected database. Do not create another account or workspace. See [login recovery](LOGIN_RECOVERY.md). Your password is entered only in the local window.
