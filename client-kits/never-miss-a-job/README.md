# Never Miss a Job

The first AI service we sell: A$249 a month (A$149 for website clients), no build fee.
It runs inside the client's own Gmail or Google Workspace account as a free Google Apps Script,
so it works 24/7 even when Benji's Mac is asleep, and costs us nothing to run.

Draft only. Nothing here is installed in any account and nothing has been sent.

## What the client gets

| # | Piece | What happens |
|---|-------|--------------|
| 03 | Instant reply | Every new enquiry gets a friendly reply within about 5 minutes, day or night. It asks only for what's missing (suburb, phone, photos). |
| 01 | Lead sorting | Each enquiry is labelled Hot, Warm, Check this one or Spam. Hot leads also trigger an alert email to the owner. Spam and SEO pitches get no reply. |
| 04 | Quote chaser | The owner adds the label **Quote sent**. If the customer goes quiet, a nudge goes out after 2 days, a last check-in 5 days later, then the quote is marked cold. Any reply stops it. |
| 28 + 13 | How did we go + review ask | The owner adds the label **Job done**. The customer gets one email asking for a 1–5 score with the Google review link. |
| 27 | Feedback reader | 4–5 gets a thank-you. 1–3 gets "we'll make it right" and an alert to the owner to call them. Anything unclear is labelled for the owner. |
| 50 (lite) | Monday summary | Enquiries answered, quotes chased, reviews asked, happy and unhappy customers. This is our proof of value each week. |

Every customer gets the review link, whatever their score. Google's review policy bans
"selectively soliciting positive reviews from customers", so the system never holds the
link back from an unhappy customer. It just makes sure the owner hears about them first.

Lead sorting uses rules, not a paid AI model, so there is no running cost. A paid model can
be added later on the client's own key if they want it.

## Setting it up for a client (about 15 minutes, with the client)

1. On the client's computer, signed in to their business Google account, open script.google.com and create a new project called "Never Miss a Job".
2. Copy in `Config.js`, `Logic.js` and `Main.js` as three script files. Under Project Settings, tick "Show appsscript.json" and paste in `appsscript.json`.
3. Fill in `Config.js` with the client: business name, owner, phone, Google review link, services, suburbs and postcodes, website form sender.
4. Leave `mode: 'drafts'`. Select `setup` and press Run. The client approves Google's permission screen. It warns that Google hasn't verified the app; that's normal for a script in their own account.
5. For the first week every email is a Gmail draft the client checks and sends. When they're happy, change `mode` to `'send'`.

Only mail that arrives after setup is answered. Old enquiries are never touched.

## Tests

```
node --test client-kits/never-miss-a-job/test/logic.test.js
```
