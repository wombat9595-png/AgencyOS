# Local dashboard recovery — 17 October 2026

The owner reported the standard Flask “Not Found” page. This proves a server answered, but does not identify the Mac's running checkout or exact URL. The full browser address is still needed to confirm the actual owner-side cause; no remote Mac access is available.

Two reproducible causes were addressed:

- `/launch/`, `/business/` and `/gmail/` previously returned 404 while their equivalents without the final slash worked. Both forms now work. Unknown paths still return 404, and owner authentication remains required.
- If another app or an older AgencyOS copy occupies port 5000, the default launcher now chooses an available loopback port from 5050–5059 and opens/prints the actual dashboard address. Explicit fixed-port conflicts fail with an actionable message; no other process is stopped.

Opening the same workspace launcher again reopens its verified local dashboard rather than starting another instance. Private, bounded metadata records the current URL; external/malformed URLs are rejected, a local health reply is checked, and normal shutdown removes the record. Startup failures remain visible in the launcher window rather than disappearing behind a guessed URL.

Verified on Python 3.13.5/Linux:

- **6 focused automated tests passed**: authenticated dashboard aliases, unknown-route handling, occupied-port selection, metadata constraints and local-health verification.
- Actual server/coordinator test passed with port 5000 occupied, correct alternate URL discovery and repeated launcher opening without duplicate processes.
- Actual owner setup/login and authenticated **`/launch` HTTP 200** smoke test passed after the changes; worker heartbeats and private file permissions verified.
- Bash syntax and Git whitespace checks passed. [Evidence](validation/evidence/startup-recovery).

The original 275-test full-suite result belongs to the first-sale implementation commit `60d366c`; this follow-up used the focused regressions and actual-process checks above. Native macOS/Finder, the owner's installed copy and real Gmail remain unverified.

## Owner action

Use the updated `codex/agencyos-first-sale` folder and open **Launch AgencyOS.command**. Let it open the correct browser address; keep its window open. Download into a new folder if updating manually—do not overwrite old databases. A GitHub repository link does not run AgencyOS on a Mac. A hardcoded localhost address cannot determine which local app/version is listening.

If the owner's page still says “Not Found”, provide the complete address bar text and whether the latest launcher opened it. No passwords, keys or authorisation codes are needed. This is necessary diagnosis, not a request to repeat engineering QA.

We are at a tested local setup stage, not a finished unattended business: Gmail OAuth/client setup and real-account validation, current legal/provider checks, compliant real invoicing and live customer delivery still need attention. See [first-sale readiness](FIRST_SALE_READINESS.md).
