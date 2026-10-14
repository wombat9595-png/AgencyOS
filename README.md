# AgencyOS — Phase 1 (Rebuilt)

A local-first starter app for managing an AI website agency. This is a working foundation, not a production-hardened or cloud-deployed service.

## Included
- Owner account setup and login
- Dashboard overview
- Lead/contact records
- Human-reviewed outreach email drafts (no email is sent)
- Quote records and status tracking
- Internal invoice records and payment status tracking (does not collect payments or issue tax invoices)
- Website project tracking

## Requirements
- Python 3.10 or newer
- macOS Terminal

## Run on your Mac
1. Unzip the downloaded `AgencyOS_Phase1_Rebuilt.zip`.
2. Open Terminal and move into the `AgencyOS_Phase1` folder. For example:
   `cd ~/Downloads/AgencyOS_Phase1`
3. Create a virtual environment:
   `python3 -m venv .venv`
4. Activate it:
   `source .venv/bin/activate`
5. Install dependencies:
   `python -m pip install -r requirements.txt`
6. Set a private secret key for this local run:
   `export AGENCYOS_SECRET_KEY="$(python -c 'import secrets; print(secrets.token_hex(32))')"`
7. Start the app:
   `python app.py`
8. Open `http://127.0.0.1:5000/setup` in your browser and create the owner account with a strong password.

Keep the Terminal window open while using the app. Press `Control+C` to stop it.

## Data and backup
The app creates `agencyos.db` in this folder when first run. This file contains your records. Stop the app before copying it as a backup. Do not upload the database or share passwords.

## Important limitations
- Data stays on this computer by default.
- The email drafting feature uses a basic template; no external AI API is connected yet.
- Outreach is drafted only; the app never sends messages.
- Quotes and invoices are internal records, not accounting documents or payment processing.
- There is no automated lead scraping, website generation, public hosting, multi-user access, password reset, or production deployment yet.
- Before any public deployment, add CSRF protection, rate limiting, secure production secret management, HTTPS, robust account recovery, audit logging, and a security review. Do not expose the development server directly to the internet.

## Suggested Phase 2
1. Improve lead research with compliant, source-attributed imports and duplicate detection.
2. Add configurable AI provider integration for outreach drafts, with approval before sending.
3. Add a website brief intake form and AI-assisted site-generation workflow.
4. Add quote PDF export and client approval.
5. Add integrations only after choosing providers and reviewing their permissions.
