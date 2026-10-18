# Motion kit

Reusable scroll-animation kit for the **Signature** tier, plus three demo sites to sell it.
Plain HTML, CSS and one script. No build step, no monthly fees. Every file works offline.

```
motion-kit/
  index.html            demo picker (open this first)
  kit/motion.css        base styles; re-skin with the variables at the top
  kit/motion.js         every scroll effect, switched on with data attributes
  kit/vendor/           GSAP 3.13 (ScrollTrigger, SplitText) and Lenis 1.3, self-hosted
  kit/fonts/            Inter, Archivo, Fraunces, Cormorant Garamond (self-hosted, OFL)
  demos/builder/        Northline Building Co. (made-up business)
  demos/landscaper/     Greenhaven Landscapes (made-up business)
  demos/salon/          Maison Rosé Hair & Beauty (made-up business)
```

## See it

Open `index.html` through a local web server (fonts and scripts won't load from a double-clicked file in some browsers):

```
cd motion-kit && python3 -m http.server 8765
```

Then go to http://localhost:8765. To try it on a phone on the same Wi-Fi, use the Mac's local IP instead of localhost.

## Effects (data attributes)

| Attribute | What it does |
|---|---|
| `data-hero` | Hero media zooms out on load and as you scroll away; text drifts up |
| `data-reveal` | Fades up into view (`left`, `right`, `scale` for other directions) |
| `data-split` | Headline reveals line by line |
| `data-parallax="0.3"` | Layer moves at a different speed (use inside `data-parallax-scope`) |
| `data-draw` | SVG strokes draw themselves as you scroll (builder blueprint) |
| `data-pin-steps` | Section pins while its `data-step` cards play through (desktop); stacks on phones |
| `data-hscroll` | Scroll down and the `.hscroll-track` row slides sideways |
| `data-counter="250"` | Number counts up (`data-suffix="+"`) |
| `data-marquee="30"` | Endless text band that speeds up with scroll |
| `data-compare` | Before/after drag slider |
| `data-scene="name"` | Full-screen story scene: the section pins and scrolling plays a timeline (see below) |

Smooth scrolling (Lenis), the scroll progress bar, the hide-on-scroll header and the phone call bar come for free.

## Story scenes (the Signature centrepiece)

Each demo has one scroll-driven story, in `demos/<name>/scene.js`:

- **Builder:** blueprint draws itself, excavator and slab, frame and crane-lifted trusses, lock-up, handover at dusk, then an extension is added.
- **Landscaper:** overcast junk-filled yard, dozer levels it, crew builds pool, paving and fence, turf and planting roll in, golden hour.
- **Salon:** hair drawn live from numbers. Scissors cut it, then it waves, curls and changes colour as you scroll.

A scene is an `<svg class="scene-svg">` plus captions marked `data-scene-caption="label"`. The scene script registers `window.MotionScenes[name] = function (tl, section) { ... }` and adds the same labels to the timeline. `data-scene-fit="artW,artH,centreX,groundY,groundAt,minPhoneW,wideAt"` keeps the subject framed on phones and wide screens. With reduced motion on, visitors see the finished picture with all captions listed underneath.

For a client, keep the story and swap the details: their colours, their house style or pool shape, their actual services as captions. Budget roughly a day for a custom scene.

## New client in about an hour

1. Copy the closest demo folder to `clients/<business>/` and fix the `../../kit/` paths if the depth changes.
2. Change the `:root` colours and fonts in the page's `<style>` block.
3. Replace the copy, phone number, email, services and reviews. Use only real reviews and real numbers.
4. Swap the illustrated art for the client's own photos (`<img>` inside `.card-art`, `.compare-layer`, `.hero-media`). Export at 1600px wide, WebP, under 250 KB each.
5. Connect the form (Web3Forms free tier) and change the `onsubmit` demo line.
6. Run the checklist below, then deploy the folder to Cloudflare Pages (free).

## Checklist before a client sees it

- [ ] Phone call button visible on the first screen, no waiting for animation
- [ ] Tested on a real phone (iPhone and a mid-range Android), not just the Mac
- [ ] Turn on Reduce Motion (iPhone: Settings > Accessibility > Motion) and check every section still shows
- [ ] Lighthouse mobile performance 90+ (Chrome DevTools > Lighthouse)
- [ ] No horizontal scrolling on a 360px-wide screen
- [ ] Form sends to the client's email
- [ ] Footer demo note removed, real business details in, ABN where relevant

## Licences

GSAP and all its plugins are free for commercial use under the GSAP standard licence (https://gsap.com/standard-license). Lenis is MIT. Fonts are SIL Open Font License. Demo businesses, reviews, prices and numbers are made up and must be replaced.
