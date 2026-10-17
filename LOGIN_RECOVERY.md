# Recover an existing AgencyOS login

17 October 2026

This tool resets an **existing owner account in the database you select**. It does not create an account, create a business database, rename users, delete records, migrate old business tables or contact Gmail. A saved login in a password manager does not identify which database is running on a particular local URL.

## On your Mac

1. Download the updated `codex/agencyos-first-sale` project and extract it into a **new folder**. Keep every old AgencyOS folder/database. Opening the recovery helper from this folder does not start a new workspace.
2. Double-click **Recover AgencyOS Login.command**. It uses the existing pinned Python environment or installs its free dependencies. The official python.org macOS Python installer includes the Tk library needed for the local window. No Terminal commands or password sharing are required.
3. Select the existing workspace containing your records. The window lists its actual owner username, database path, and lead/project counts. It searches the helper's project, nearby AgencyOS folders and the standard private data directory; **Browse** can select a database elsewhere. This is a bounded local inventory, not a search of every document on your Mac.
4. Enter a new password of at least 16 characters twice and confirm the selected owner/database. Save that password in your password manager against the appropriate AgencyOS address. Use the exact username shown by recovery, including capitals. If `CEO` is the owner, its existing account is reset; if `CEO` is a different stored account, the tool identifies the original owner rather than creating/promoting another user.
5. Return to the sign-in page for that same workspace and use the displayed username and your new password. Keep its existing server running for that login. Recovery itself does not know which browser tab/port belongs to each old database and does not switch, replace or start those apps. If there are several databases with the same username and similar records, stop before resetting and identify the one in use. No remote inspection of Benji's Mac has occurred.

Do not try account setup again for a database that already has an owner. Do not send passwords, password hashes, encryption keys, or database copies through chat.

## Safeguards

Before modifying the account, the tool makes and verifies an encrypted SQLite snapshot. By default, backups and the private `recovery-backup.secret` key are stored in `~/Library/Application Support/AgencyOS-Recovery/`, outside the project. Files are restricted to the Mac user. Keep encrypted copies and the matching key securely on owner-controlled external storage; same-disk storage does not protect against a lost Mac. The key can decrypt snapshots containing historical password hashes and customer records, so do not publish it or put it in Git. The snapshot is a Fernet-encrypted raw SQLite file, not the ZIP archive used by the production backup command. Restore only into a new location after integrity checking; never overwrite a live database.

Only the first existing owner password hash is replaced. Account IDs, usernames, other accounts, lead/project/financial records, Gmail tokens and application encryption keys remain intact. New additive recovery metadata records the reset time and encrypted-backup digest, without storing the new password. Failed backups, invalid passwords, wrong/missing/unrelated databases or changed owner selections do not reset the password. Inventory uses SQLite read-only access; missing filenames do not become new databases. Symlink files are refused.

Current AgencyOS invalidates the owner's earlier sessions and clears sign-in throttling after local recovery. Recovery does not automatically revoke sessions inside an **old Phase 2 server**, whose code does not read the new metadata: restart that old app to discard its earlier sessions. No reset route or unauthenticated web backdoor is installed. Recovery requires local filesystem access and explicit confirmation on the owner's computer.

## Verification

- **292 automated tests passed** on Python **3.13.5**, 103.272 seconds, no failures or skips. Includes **11 new recovery regressions**: original record/account preservation, existing `CEO`, encrypted pre-reset snapshot, password/selection/backup failure handling, legacy Phase 2 compatibility, stale/foreign sessions, throttling and read-only workspace inventory.
- Actual HTTP server recovery passed: existing fictional `CEO` retained the same ID; no new accounts; business records preserved; old password/session rejected; recovered owner loaded **`/launch` with HTTP 200**.
- Both Mac command files passed Bash syntax checks; Git whitespace checks passed. Native Finder/Tk execution was not tested.
- [Full-suite log](validation/evidence/login-recovery/full-suite.log), [real-process result](validation/evidence/login-recovery/http-recovery.log), and [source hashes](validation/evidence/login-recovery/source-manifest.json).

The tests use fictional credentials and temporary databases only. The native Mac/Tk window and the owner's real database/login have **not** been executed or changed from this cloud workspace. Python recovery logic, encrypted snapshots, session handling and real local HTTP sign-in are tested. The owner must perform the local selection and enter the new password; that action cannot be completed remotely through this chat.
