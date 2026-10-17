# First-sale owner decisions, provider boundaries and costs

Prepared 16 October 2026 (Australia/Sydney). **Current policies are not independently verified.** This environment's HTTPS proxy returned `Tunnel connection failed: 403 Forbidden` for the official government, Google, hosting and model documentation below. The attempted URLs/results are retained in `validation/evidence/first-sale/policy-fetch-attempts.json`. No verification attestation or discovery/sending activation was fabricated. The following is general guidance and a checklist for the owner to confirm against current official sources, not a legal clearance.

## A sole trader need not create a company

| Decision | General position to check | AgencyOS action |
|---|---|---|
| Legal identity | A sole trader is an individual, not a separate company. Confirm that **Benji Price is the full legal name** you may trade under; supplied identity is not independent identity verification. | Uses Benji Price as supplied; invents no qualifications, offices or credentials. |
| Company | Incorporating a company is separate from being a sole trader and normally is not needed just to offer web design. | No application, company claim, incorporation cost or legal declaration. |
| Trading name | Generally, trading under your exact personal legal name does not require ASIC business-name registration. A different customer-facing trading name normally does. Keeping AgencyOS as a private tool does not itself make it your trading name. Confirm your actual name/use. | Customer-facing identity remains Benji Price; do not advertise AgencyOS as an independently registered agency. |
| ABN | An eligible sole trader carrying on/starting an enterprise may obtain an ABN through the Australian Business Register **without a government application fee**. Eligibility and the actual facts still matter. An ABN is not a company. | Owner decides/applies directly; no invented ABN. Do not pay a third-party application service merely for convenience. |
| No ABN | An ABN is not automatically compulsory in every circumstance, but business customers may have **no-ABN withholding obligations**, commonly 47% subject to exceptions. This is material for a A$600–A$1,000 business invoice; resolve before requesting payment. | Live invoice issuance remains gated; do not assume the first sale can ignore ABN rules. |
| GST | The usual business registration threshold is **A$75,000 GST turnover** (special rules/exceptions apply). Check current and projected rolling turnover, timing and other activities. Cumulative A$100,000 lifetime revenue is **not** the GST test; profit is not turnover. Voluntary registration has obligations. | GST starts `unset`; owner confirms actual status. Not registered means no GST charged and no “tax invoice” claim. Registered setting adds 10% to saved ex-GST package prices and discloses the total. Existing verified owner settings are preserved. |
| Tax and records | Sole-trader business income generally goes in the individual's tax return; preserve income, expense and business records (commonly at least five years, with exceptions), and consider PAYG/recordkeeping obligations. | Cash receipts/expenses are separate from profit/tax advice. No tax returns or declarations filed. |
| Invoice details | Ordinary invoices and GST tax invoices have different requirements. Confirm accurate seller/customer identity, ABN where required, description, amounts, dates/terms and GST disclosures. Bank details must be owner-provided and private. | Creates **unissued draft PDFs**, not real invoice issuance. Synthetic invoice tests cannot authorise a customer charge. |

Owner checklist before the first transaction:

- [ ] Confirm full legal name, eligible sole-trader circumstances and whether an ABN is required/appropriate; obtain/confirm it directly if appropriate.
- [ ] Confirm actual GST status and rolling turnover obligations; update Sales and Billing consistently.
- [ ] Supply accurate customer-facing contact and invoice details. Do not use fictional fixture details.
- [ ] Agree written package scope, exclusions, third-party costs, payment terms, revisions, ownership/asset licences and delivery assumptions with the customer.
- [ ] Choose an appropriate compliant invoice process; real issuance is not implemented in this change.
- [ ] Use only your verified bank details; independently verify receipts before recording them. No bank feed is installed.

Official references to review:

- [Business.gov.au — sole trader](https://business.gov.au/planning/business-structures-and-types/business-structures/sole-trader)
- [ASIC — registering a business name](https://www.asic.gov.au/for-business-and-companies/business-names/register-a-business-name/)
- [ABR — applying for an ABN](https://www.abr.gov.au/business-super-funds-charities/applying-abn)
- [ATO — GST registration](https://www.ato.gov.au/businesses-and-organisations/gst-excise-and-indirect-taxes/gst/registering-for-gst)
- [ATO](https://www.ato.gov.au/) — confirm current no-ABN withholding, invoices and recordkeeping requirements directly.

## Email and privacy: separate permission boundaries

A public business email address is **not automatic marketing consent**. Commercial electronic messages generally need appropriate consent, accurate identification/contact information and a functional unsubscribe facility. Inferred consent is contextual and narrow, not a generic permission to scrape and email businesses. Do not assume a request for one quote authorises indefinite marketing. Record the exact evidence, purpose, recipient, expiry where relevant and reviewed basis. Stop on opt-outs promptly (the software suppresses immediately; applicable legal time limits still require owner confirmation). Provider rules can be stricter than the law.

The installed Gmail reply policy is deliberately conservative: current **explicit consent** evidence in the existing contact-basis table, a recent owner policy attestation (30 days), one-message owner approval, suppression recheck, correct account/thread, separately granted `gmail.send`, an external activation flag and a 1–10/day ceiling. The private launcher overrides that flag to **off**. It supports replies only, not live unsolicited outreach. A policy checkbox records the owner's attestation; it is not legal verification.

Unsubscribe is by replying to the dedicated Gmail. Polling suppresses detected requests; this is not a public one-click unsubscribe service. Since the local Mac can sleep/offline and classification is rule-based, the owner must monitor Gmail and process requests that automation misses. Do not enable sending until this operational gap is addressed for the intended usage. No large campaigns, deletion or arbitrary forwarding are implemented. Consumer Gmail limits are ceilings, not permission or deliverability guarantees. Formal Google abuse/bounce/complaint webhooks and automated DSN analysis are not implemented; the owner must monitor them and suppress affected contacts.

A small Australian business may be exempt from some Privacy Act obligations (often a A$3 million annual-turnover threshold), **but important exceptions apply**, including some activities involving personal-information trading, health, credit, government contracts and other covered businesses. Do not assume all small businesses are exempt. Spam rules, contractual confidentiality, data security and other applicable laws still matter. Review actual activity and minimise retention/access. Google stores mailbox data on its infrastructure; local AgencyOS is not a promise that Gmail data never leaves Australia. No mailbox data is sent to an AI service by this integration.

- [ACMA — avoid sending spam](https://www.acma.gov.au/avoid-sending-spam)
- [OAIC — small business](https://www.oaic.gov.au/privacy/your-privacy-rights/small-business)
- [Gmail API scopes](https://developers.google.com/workspace/gmail/api/auth/scopes)
- [Google native-app OAuth](https://developers.google.com/identity/protocols/oauth2/native-app)
- [Google OAuth overview/testing](https://developers.google.com/identity/protocols/oauth2)
- [Gmail developer policy](https://developers.google.com/workspace/gmail/api/policy)
- [Google API user-data/Limited Use policy](https://developers.google.com/terms/api-services-user-data-policy)
- [Consumer Gmail sending limits](https://support.google.com/mail/answer/22839)

`gmail.readonly` is restricted; `gmail.send` is separately requested. Do not request unrestricted mailbox modification for convenience. Labels, server-side draft writes and deleting mail are omitted. Confirm Google's current personal-use/testing/verification rules, refresh-token expiry, quota and any assessment requirements for the actual configuration. Do not enable billing or purchase verification. OAuth JSON and refresh tokens are not Gmail passwords, but they still need protection. OAuth codes/state are omitted from the private server access logs. Google profile verification proves the connected account, **not the identity or honesty of people emailing it**.

## Nationwide leads without buying data

New plans include ACT, NSW, NT, QLD, SA, TAS, VIC and WA, with no city restriction. Saved owner restrictions are kept; review them if you previously saved Canberra. City/town filters remain configurable. No businesses or contact details have been acquired by this work.

The working zero-cost input is owner-authorised manual/CSV intake, including source URL, observed time, source identity and explicit permission review/expiry. Qualified referrals and inbound enquiries are the shortest route. Source-data licensing, website-inspection permission and consent to contact are **three different questions**. Deduplication and evidence-backed triage do not establish purchase intent or budget.

Sources to investigate, **not approved or activated**:

| Source | Potential use | Unresolved boundary |
|---|---|---|
| Customer/referral information | Owner records a genuine enquiry or referral with permission | Permission purpose, identity, accuracy and consent still recorded; no blanket referral marketing consent. |
| Authorised CSV/export | Existing import, licence/attribution/expiry checks and duplicate review | Actual rights to collect, store and use commercially must cover that specific dataset. Never import restricted platform scraping. |
| [ABN bulk extract](https://data.gov.au/data/dataset/abn-bulk-extract) | Existing offline fragment parser can supplement entity/state/postcode facts | Review current licence/access requirements. It does not provide reliable marketing email, street location, website quality, purchase intent or consent. |
| OSM | Existing bounded interactive adapter may be useful under approved terms | [Nominatim policy](https://operations.osmfoundation.org/policies/nominatim/), instance permissions and [ODbL attribution](https://www.openstreetmap.org/copyright) need current review. Public endpoints are not a free nationwide scraping service. Remains disabled. |

No paid lead database, Google Maps scrape or new crawling system is introduced. The existing website audit is bounded static HTML checking, with owner permission, robots handling, public-destination/SSRF checks and separate activation. It does not measure visual quality, live mobile usability, performance or full accessibility. Recommendations remain separate from observed findings.

## Delivery and unavoidable costs

| Capability | Immediate software spend | Practical limit |
|---|---:|---|
| Private Flask/SQLite, local jobs, templates, QA, exports, backups | A$0 additional subscription | Uses existing Mac, storage, electricity/internet; sleep/offline pauses work. External backup storage may require an already owned device or later approved cost. |
| Gmail OAuth/API architecture | No new paid email platform installed | Requires owner's Google project, free account authorisation and current quota/policy checks. No assumption of unverified provider access or paid verification. |
| ChatGPT/Codex | Existing subscriptions only | **Not free API credits.** No API billing enabled. |
| Customer static export | A$0 generation/export charge | Delivery/public hosting/domain/assets/forms are separate from AgencyOS hosting. |
| Domain/hosting/forms | Customer-funded if needed | Quote actual current prices before commitment; do not promise they are free or included. Customer owns accounts. No provider purchased/activated. |
| Bank transfer | No processor subscription installed | Actual bank/account fees depend on the customer's/owner's bank; receipt confirmation is manual owner attestation, not an API verification. |

Review [Cloudflare Pages limits](https://developers.cloudflare.com/pages/platform/limits/), applicable Cloudflare terms, and [Netlify pricing/terms](https://www.netlify.com/pricing/) before suggesting a customer-owned free static plan. No current commercial-use clearance was obtained here, so neither is a verified recommendation. **Do not assume GitHub Pages is suitable for a commercial business site**; its [limits/use restrictions](https://docs.github.com/en/pages/getting-started-with-github-pages/github-pages-limits) need particular care. Static contact details do not need a paid backend; actual enquiry submission needs a tested, approved destination. Prefer an already owned customer host or export first; resolve real costs after written scope and before publication.

## Local AI assessment — no model downloaded

A local model can avoid token charges but is not costless in RAM, disk, power or judgement. This Linux workspace cannot inspect Benji's MacBook's chip/RAM/free disk. No model or runtime was downloaded, installed or claimed tested on the Mac. Keep templates/rules usable and label them accurately.

A small quantised 1–3B model can be a starting experiment on some 8 GB machines, typically using several GB of disk/RAM; 7–8B models generally need substantially more headroom and may be impractical alongside a browser on an 8 GB Mac. Apple silicon with Metal and 16 GB+ is generally more promising; Intel/CPU-only operation can be slow. These are rough planning estimates, not measured performance or a purchase recommendation. Verify actual hardware, free disk and runtime compatibility first. Review the **specific model** licence as well as runtime terms; an open-source runner does not grant all model rights. [Ollama FAQ](https://docs.ollama.com/faq) is a starting reference, not a verified compatibility result.

Local models may help draft copy and summarise conversations but still hallucinate and obey malicious-looking text unpredictably. No model may approve scope, acceptance, payment or sending. A future controlled loopback adapter should require explicit owner installation/model selection, bounded input/output, no automatic downloads, no shell tools, no public model server and the same approval gates. A model integration is **not implemented** here because hardware suitability and licences remain unverified; deterministic functionality is real and tested, not labelled genuine LLM execution.
