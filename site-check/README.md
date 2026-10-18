# Free website check page

A public page where any business owner types their web address and gets a score out of 100, then can ask for a free mock-up. Leads come to you instead of you emailing them.

**Not online yet.** Putting it online makes it public, so it waits for Benji's go ("put it online").

## What's here

- `index.html` – the page. The mock-up request form posts to Web3Forms (free), which emails the request to you.
- `functions/api/check.js` – a Cloudflare Pages Function that fetches the homepage once and scores it.
- `functions/_lib/score.js` – the scoring rules (loads, https, fits phones, speed, tap-to-call, freshness, Google description).
- `tests/score.test.mjs` – run with `node tests/score.test.mjs`.

## Going live (about 10 minutes, A$0)

1. Get a free access key at web3forms.com using benji.price.webdesign@gmail.com, and paste it into `WEB3FORMS_KEY` in `index.html`.
2. In Cloudflare (free account): Workers & Pages → Create → Pages → Upload assets, or connect this repo with `site-check` as the root folder. No build command.
3. Optional: point a subdomain such as `check.yourdomain.com.au` at it.

Cloudflare's free plan allows 100,000 function requests a day, far more than this needs.
