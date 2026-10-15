# Phase 3 provider review status

**Status: UNVERIFIED. Live OSM discovery must remain disabled until a current operator review confirms permitted use.**

On 15 October 2026 the development environment returned `Tunnel connection failed: 403 Forbidden` for the official Nominatim, Overpass and OSM copyright pages. This is a network-policy observation, not proof that providers denied AgencyOS or that their policies allow its intended use. No live discovery request was made.

Required review sources:

- Nominatim usage: https://operations.osmfoundation.org/policies/nominatim/
- Selected Overpass instance and usage guidance: https://overpass-api.de/
- OSM licence/attribution: https://www.openstreetmap.org/copyright
- Further technical background (not a replacement for instance permission): https://wiki.openstreetmap.org/wiki/Overpass_API

Fixed endpoints in this adapter:

- `https://nominatim.openstreetmap.org/search`
- `https://overpass-api.de/api/interpreter`

Before enabling, verify that the intended interactive, small-scale business research and stored candidate/lead data comply with the current terms. Review query burden, identification/contact rules, request limits, cache/storage permissions, attribution, licence/share-alike requirements, privacy obligations and any commercial-use restrictions. Public data is not marketing consent.

Do not assume a rate limit alone grants permission. This implementation does no Nominatim autocomplete, bulk geocoding, unrestricted Overpass query execution or recursive website scraping. Its own conservative ceilings are described in README; stricter provider requirements take precedence. If requirements cannot be satisfied, do not record an enabling review for this adapter. Public service availability/SLA is not guaranteed.

`manage.py policy-review` records the operator's explicit attestation, contact and review time in an ignored local file. It does **not** independently access or interpret these policies. It refuses to overwrite existing review records. Records expire after 30 days, bind to these endpoints/policy URLs and invalidate queued approvals when changed. Never treat a mocked test review as a real policy confirmation.

Optional website inspection is separately disabled by default. The owner must confirm permitted access for the exact public business website. Robots.txt is respected but is not a legal permission grant. The fetcher refuses proxy-mode inspection rather than bypassing egress controls or weakening destination checks.

AI access requires the operator's own provider account, key, approved model, current pricing review and approval of each chargeable task. No production credentials or paid calls are needed for tests.
