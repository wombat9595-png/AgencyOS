---
version: alpha
name: AgencyOS house style
description: The rules every AgencyOS client website follows so it looks hand-made for that business, never like a generic AI template. Niche looks live in design/niches/. Craft references (84 real-brand DESIGN.md files, MIT) live in design/references/awesome-design-md/.
---

# AgencyOS house style

Read this file before building or changing any client website, mock-up or demo.
Then read the niche file for the trade (design/niches/). The niche file's tokens
are what website_builder.py renders, so change the look there, not in Python.

## The one-line test

A tradie's customer should look at the site and think "these people are good at
their job", not "this was made by a computer". If a section could sit on any
business's site unchanged, rewrite it or cut it.

## Layout

- One clear job per page: get the visitor to call or ask for a quote.
- The phone number is a real `tel:` link in the hero and the footer when we have one.
- Big, confident headline (the business name or what they do and where), one short
  sentence under it, one main button. Never three equal buttons.
- Plenty of space. Sections breathe (64-120px top and bottom on desktop).
- Max line length about 70 characters for body text.
- Mobile first: everything readable and tappable at 375px wide, buttons at least 44px tall.
- Real photos of their work beat any illustration. Until we have theirs, say plainly
  that photos are placeholders. Never use stock photos of smiling people in hard hats.

## Type

- Two typefaces at most: one display face with character, one plain body face.
- Body text 16-18px, line height 1.5-1.7.
- Headings get tight letter spacing; body text never does.
- Never centre long paragraphs.

## Colour

- One brand colour used sparingly (buttons, small accents). Everything else is ink,
  paper and one muted grey.
- Every text colour passes WCAG AA (4.5:1) on its background. AgencyOS checks this
  automatically before a site can be approved.
- No purple-to-blue gradients, no glowing blobs, no glassmorphism, no rainbow icons.
  These are the fastest tell of an AI-made site.

## Words (the anti-slop list)

Write like the owner talks: plain Australian English, short sentences, specific to
their suburb and their work. AgencyOS refuses a site or email that contains any of
these phrases (see design_system.SLOP_PHRASES):

"welcome to our website", "look no further", "one-stop shop", "elevate", "unlock",
"unleash", "seamless", "cutting-edge", "state-of-the-art", "next level",
"game-changer", "revolutionise", "in today's fast-paced world", "we pride ourselves",
"passionate about", "tailored solutions", "your vision, our mission",
"bring your vision to life", "delve", "nestled", "lorem ipsum".

Also never invent facts: no made-up reviews, awards, years in business, licences,
"fully insured" or "family owned" unless the client told us in writing.

## Things that make a site feel hand-made

- The suburb and service area named in plain words.
- Services written as the jobs customers actually ask for ("deck repairs",
  "bathroom renovations"), not categories ("Construction Solutions").
- A short honest "how it works" (call, quote, job done) instead of a mission statement.
- Small details that match the trade: ruler lines for builders, soft organic shapes
  for landscapers, fine serif type for salons.

## Using the reference library

design/references/awesome-design-md/ has 84 DESIGN.md files written about real
brands' websites (Airbnb, Apple, Stripe, Nike and more), from
github.com/VoltAgent/awesome-design-md (MIT licence, copied 2026-10-22 at commit
3b60532). Use them to learn craft: spacing scales, type ramps, how restraint looks.
Never copy a brand's colours, fonts, logo or wording onto a client's site; that is
their trade dress and it would make our client look like a knock-off.

Best ones for local-business sites: airbnb (warm, photo-first), apple (restraint),
starbucks (warm brand colour used sparingly), stripe (type and spacing),
notion (calm, plain words), nike (bold display type), webflow and framer (layout).
