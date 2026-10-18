/*
 * Motion kit: one script that wires up every scroll effect from data attributes.
 * Needs gsap, ScrollTrigger, SplitText and Lenis loaded first (see kit/vendor).
 *
 * Attributes (put them on any element):
 *   data-reveal            fade up as it scrolls in ("left", "right", "scale" for other directions)
 *   data-stagger           children with data-reveal inside it come in one after another
 *   data-split             headline reveals line by line
 *   data-parallax="0.3"    moves slower/faster than the page (negative = opposite way)
 *   data-hero              hero: media zooms out, text drifts up as you scroll away
 *   data-draw              SVG strokes inside draw themselves as you scroll
 *   data-pin-steps         section pins while its [data-step] children play through
 *   data-hscroll           horizontal gallery driven by vertical scroll (needs a .hscroll-track child)
 *   data-counter="250"     number counts up (data-suffix="+" optional)
 *   data-marquee           endless text band that speeds up with scroll
 *   data-compare           before/after slider (needs input[type=range] inside)
 *
 * Visitors with "reduce motion" switched on get the same page, fully visible, with no animation.
 * Without JavaScript everything is visible too: initial states are only set from here.
 */
(function () {
  'use strict';

  var reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var root = document.documentElement;

  // Before/after slider works with or without motion.
  document.querySelectorAll('[data-compare]').forEach(function (el) {
    var input = el.querySelector('input[type=range]');
    if (!input) return;
    var set = function () { el.style.setProperty('--pos', input.value + '%'); };
    input.addEventListener('input', set);
    set();
  });

  // Header: solid background once you leave the top, hides when scrolling down.
  var header = document.querySelector('.site-header');
  var lastY = 0;
  function onScrollHeader(y) {
    if (!header) return;
    header.classList.toggle('is-scrolled', y > 40);
    header.classList.toggle('is-hidden', y > lastY && y > 400);
    lastY = y;
  }

  if (reduce || !window.gsap || !window.ScrollTrigger) {
    root.classList.add('motion-off');
    window.addEventListener('scroll', function () { onScrollHeader(window.scrollY); }, { passive: true });
    document.querySelectorAll('[data-counter]').forEach(function (el) {
      el.textContent = Number(el.dataset.counter).toLocaleString('en-AU') + (el.dataset.suffix || '');
    });
    return;
  }

  gsap.registerPlugin(ScrollTrigger);
  if (window.SplitText) gsap.registerPlugin(SplitText);
  root.classList.add('motion-on');

  // Smooth scrolling (desktop wheel/trackpad; phones keep their native feel).
  var lenis = null;
  if (window.Lenis) {
    lenis = new Lenis({ lerp: 0.1, autoRaf: false });
    lenis.on('scroll', function (e) { ScrollTrigger.update(); onScrollHeader(e.scroll); });
    gsap.ticker.add(function (t) { lenis.raf(t * 1000); });
    gsap.ticker.lagSmoothing(0);
  } else {
    window.addEventListener('scroll', function () { onScrollHeader(window.scrollY); }, { passive: true });
  }

  // In-page links glide instead of jumping.
  document.querySelectorAll('a[href^="#"]').forEach(function (a) {
    a.addEventListener('click', function (e) {
      var id = a.getAttribute('href');
      if (id.length < 2) return;
      var target = document.querySelector(id);
      if (!target) return;
      e.preventDefault();
      if (lenis) lenis.scrollTo(target, { offset: -70 });
      else target.scrollIntoView({ behavior: 'smooth' });
    });
  });

  // Scroll progress bar.
  var bar = document.querySelector('.scroll-progress');
  if (bar) {
    gsap.to(bar, { scaleX: 1, ease: 'none', scrollTrigger: { start: 0, end: 'max', scrub: true } });
  }

  // Hero: zoom the media out and lift the text as you scroll away.
  document.querySelectorAll('[data-hero]').forEach(function (hero) {
    var media = hero.querySelector('.hero-media');
    var copy = hero.querySelector('.hero-copy');
    var intro = gsap.timeline({ defaults: { ease: 'power3.out' } });
    if (media) intro.from(media, { scale: 1.15, duration: 1.6 }, 0);
    if (copy) intro.from(copy.children, { y: 40, opacity: 0, duration: 1, stagger: 0.12 }, 0.2);
    var out = gsap.timeline({ scrollTrigger: { trigger: hero, start: 'top top', end: 'bottom top', scrub: true } });
    if (media) out.to(media, { scale: 1.12, yPercent: 12, ease: 'none' }, 0);
    if (copy) out.to(copy, { yPercent: -30, opacity: 0, ease: 'none' }, 0);
  });

  // Reveal on scroll, batched so a row of cards comes in together with a small stagger.
  var offsets = { up: { y: 50 }, left: { x: -60 }, right: { x: 60 }, scale: { scale: 0.9 } };
  var revealEls = gsap.utils.toArray('[data-reveal]');
  revealEls.forEach(function (el) {
    gsap.set(el, Object.assign({ opacity: 0 }, offsets[el.dataset.reveal] || offsets.up));
  });
  ScrollTrigger.batch(revealEls, {
    start: 'top 88%',
    once: true,
    onEnter: function (batch) {
      gsap.to(batch, { opacity: 1, x: 0, y: 0, scale: 1, duration: 0.9, ease: 'power3.out', stagger: 0.12, overwrite: true });
    },
  });

  // Headlines reveal line by line (re-split automatically if the layout changes).
  function splitHeadlines() {
    if (!window.SplitText) return;
    document.querySelectorAll('[data-split]').forEach(function (el) {
      SplitText.create(el, {
        type: 'lines',
        mask: 'lines',
        autoSplit: true,
        onSplit: function (self) {
          return gsap.from(self.lines, {
            yPercent: 110, duration: 1, ease: 'power4.out', stagger: 0.1,
            scrollTrigger: { trigger: el, start: 'top 88%', once: true },
          });
        },
      });
    });
  }
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(splitHeadlines);
  else splitHeadlines();

  // Parallax layers.
  document.querySelectorAll('[data-parallax]').forEach(function (el) {
    var speed = parseFloat(el.dataset.parallax) || 0.2;
    var trigger = el.closest('[data-parallax-scope]') || el;
    gsap.fromTo(el, { yPercent: -speed * 50 }, {
      yPercent: speed * 50, ease: 'none',
      scrollTrigger: { trigger: trigger, start: 'top bottom', end: 'bottom top', scrub: true },
    });
  });

  // SVG line drawing: strokes draw in as the section scrolls through.
  document.querySelectorAll('[data-draw]').forEach(function (svg) {
    var paths = svg.querySelectorAll('path, line, polyline, rect, circle');
    paths.forEach(function (p) {
      var len = p.getTotalLength ? p.getTotalLength() : 1000;
      p.style.strokeDasharray = len;
      p.style.strokeDashoffset = len;
    });
    gsap.to(paths, {
      strokeDashoffset: 0, ease: 'none', stagger: 0.05,
      scrollTrigger: { trigger: svg.closest('section') || svg, start: svg.dataset.drawStart || 'top 70%', end: svg.dataset.drawEnd || 'bottom 40%', scrub: 0.6 },
    });
    var fills = svg.querySelectorAll('[data-fill]');
    if (fills.length) {
      gsap.from(fills, {
        opacity: 0, stagger: 0.1,
        scrollTrigger: { trigger: svg.closest('section') || svg, start: 'center 60%', end: 'bottom 40%', scrub: true },
      });
    }
  });

  var mm = gsap.matchMedia();

  // Pinned steps: the section holds while each step takes its turn.
  document.querySelectorAll('[data-pin-steps]').forEach(function (section) {
    var steps = gsap.utils.toArray(section.querySelectorAll('[data-step]'));
    var dots = section.querySelectorAll('.step-dot');
    var fill = section.querySelector('.steps-fill');
    if (steps.length < 2) return;
    mm.add('(min-width: 800px)', function () {
      gsap.set(steps.slice(1), { opacity: 0, y: 40 });
      var tl = gsap.timeline({
        scrollTrigger: {
          trigger: section, start: 'top top', end: '+=' + steps.length * 70 + '%', pin: true, scrub: 0.5,
          onUpdate: function (self) {
            var i = Math.min(steps.length - 1, Math.floor(self.progress * steps.length));
            dots.forEach(function (d, j) { d.classList.toggle('is-active', j <= i); });
          },
        },
      });
      if (fill) tl.fromTo(fill, { scaleY: 0 }, { scaleY: 1, ease: 'none', duration: steps.length - 1 }, 0);
      steps.forEach(function (step, i) {
        if (i === 0) return;
        tl.to(steps[i - 1], { opacity: 0, y: -40, duration: 0.4 }, i - 0.5)
          .to(step, { opacity: 1, y: 0, duration: 0.4 }, i - 0.3);
      });
      tl.to({}, { duration: 0.4 });
      return function () { gsap.set(steps, { clearProps: 'all' }); };
    });
    mm.add('(max-width: 799px)', function () {
      steps.forEach(function (step) {
        gsap.from(step, { opacity: 0, y: 40, duration: 0.8, ease: 'power3.out', scrollTrigger: { trigger: step, start: 'top 85%', once: true } });
      });
    });
  });

  // Horizontal gallery: scroll down, the row slides sideways.
  document.querySelectorAll('[data-hscroll]').forEach(function (section) {
    var track = section.querySelector('.hscroll-track');
    if (!track) return;
    var distance = function () { return Math.max(0, track.scrollWidth - window.innerWidth); };
    gsap.to(track, {
      x: function () { return -distance(); },
      ease: 'none',
      scrollTrigger: {
        trigger: section, start: 'top top', end: function () { return '+=' + distance(); },
        pin: true, scrub: 0.6, invalidateOnRefresh: true, anticipatePin: 1,
      },
    });
    gsap.utils.toArray(track.children).forEach(function (card) {
      var inner = card.querySelector('.card-art');
      if (inner) gsap.fromTo(inner, { scale: 1.15 }, { scale: 1, ease: 'none', scrollTrigger: { trigger: section, start: 'top top', end: function () { return '+=' + distance(); }, scrub: true } });
    });
  });

  // Counters.
  document.querySelectorAll('[data-counter]').forEach(function (el) {
    var end = Number(el.dataset.counter);
    var suffix = el.dataset.suffix || '';
    var obj = { v: 0 };
    el.textContent = '0' + suffix;
    gsap.to(obj, {
      v: end, duration: 2, ease: 'power2.out',
      scrollTrigger: { trigger: el, start: 'top 90%', once: true },
      onUpdate: function () { el.textContent = Math.round(obj.v).toLocaleString('en-AU') + suffix; },
    });
  });

  // Marquee band that speeds up and flips direction with your scroll.
  document.querySelectorAll('[data-marquee]').forEach(function (band) {
    var row = band.querySelector('.marquee-row');
    if (!row) return;
    row.innerHTML += row.innerHTML; // two copies so it loops seamlessly
    var loop = gsap.to(row, { xPercent: -50, ease: 'none', duration: Number(band.dataset.marquee) || 30, repeat: -1 });
    ScrollTrigger.create({
      trigger: band, start: 'top bottom', end: 'bottom top',
      onUpdate: function (self) {
        var v = self.getVelocity() / 300;
        gsap.to(loop, { timeScale: gsap.utils.clamp(-6, 6, (self.direction || 1) * (1 + Math.abs(v))), duration: 0.2, overwrite: true });
        gsap.to(loop, { timeScale: self.direction || 1, duration: 1.2, delay: 0.2 });
      },
    });
  });

  window.addEventListener('load', function () { ScrollTrigger.refresh(); });
})();
