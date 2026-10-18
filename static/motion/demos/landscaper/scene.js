/* Landscaper story scene: messy yard, dozer levels it, pool and paving go in, turf and planting, golden hour. */
(function () {
  var NS = 'http://www.w3.org/2000/svg';
  function el(tag, attrs, parent) {
    var n = document.createElementNS(NS, tag);
    for (var k in attrs) n.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(n);
    return n;
  }
  var G = 560; // ground line

  window.MotionScenes = window.MotionScenes || {};
  window.MotionScenes.yard = function (tl, section) {
    var q = function (s) { return section.querySelector(s); };

    // Generated parts.
    var oldFence = q('#old-fence'), newFence = q('#new-fence'), weeds = q('#weeds');
    var pavers = q('#pavers'), bricks = q('#bricks'), planks = q('#planks'), flowers = q('#flowers');
    for (var x = 210, i = 0; x < 1200; x += 34, i++) {
      if (i % 4 !== 2) el('rect', { x: x, y: 470 + (i % 3) * 6, width: 26, height: 90, fill: '#9a958c', transform: 'rotate(' + ((i * 37) % 9 - 4) + ' ' + (x + 13) + ' 560)' }, oldFence);
      el('rect', { x: x, y: 462, width: 30, height: 98, fill: i % 2 ? '#b98a5a' : '#c4956a' }, newFence);
    }
    for (var w = 0; w < 22; w++) {
      var wx = 230 + w * 43 + (w * 17) % 20;
      el('path', { d: 'M' + wx + ' ' + G + 'l-6 -22l9 14l2 -26l5 24l7 -16l-3 26z', fill: w % 2 ? '#7b8a3e' : '#93a04a' }, weeds);
    }
    [[430, 520], [860, 950]].forEach(function (r) {
      for (var px = r[0]; px < r[1]; px += 30) el('rect', { x: px + 1, y: G - 8, width: 28, height: 8, rx: 1.5, fill: '#e2d9c8' }, pavers);
    });
    for (var row = 0; row < 4; row++) {
      for (var bx = 975 + (row % 2) * 14; bx < 1160; bx += 28) el('rect', { x: bx, y: G - 16 - row * 16, width: 26, height: 14, rx: 2, fill: row % 2 ? '#a65e3f' : '#b56a48' }, bricks);
    }
    for (var dx = 210; dx < 410; dx += 20) el('rect', { x: dx, y: G - 18, width: 18, height: 10, rx: 1, fill: dx % 40 ? '#9c6b43' : '#a8774c' }, planks);
    for (var f = 0; f < 18; f++) {
      var fx = 985 + (f % 9) * 20, fy = G - 72 - Math.floor(f / 9) * 14;
      el('circle', { cx: fx, cy: fy, r: 7, fill: ['#f28c8c', '#f2c14e', '#ffffff', '#c58cf2'][f % 4] }, flowers);
    }

    // 01 Before: the overcast, messy yard is the opening frame.
    tl.addLabel('before')
      .to('#rain line', { y: 30, duration: 1, stagger: 0.02 })
      .to({}, { duration: 0.4 })

    // 02 Clear: the dozer pushes everything off and levels the ground behind it.
      .addLabel('clear')
      .fromTo('#dozer', { x: -420 }, { x: 1500, duration: 4 })
      .fromTo('#mound-clip', { attr: { x: -220 } }, { attr: { x: 1700 }, duration: 4 }, '<');
    // each piece of junk gets picked up by the blade when the dozer reaches it
    var t0 = tl.labels.clear;
    section.querySelectorAll('#mess > *').forEach(function (item) {
      var ix = Number(item.dataset.x), at = t0 + 4 * (ix - 200 + 420) / 1920;
      tl.to(item, { x: 1500 - ix + 200, rotation: 20, transformOrigin: '50% 100%', duration: t0 + 4 - at }, at)
        .to(item, { opacity: 0, duration: 0.2 }, t0 + 3.8);
    });
    tl
      .to('#old-fence', { y: 140, opacity: 0, duration: 0.8, ease: 'power2.in' }, t0 + 3.2)
      .to('#rain', { opacity: 0, duration: 1 }, '<')

    // 03 Pool and paving: crew digs, pool shell, water fills, pavers laid.
      .addLabel('pool')
      .to('#sunny', { opacity: 1, duration: 1.2 })
      .from('#crew > *', { x: -700, duration: 1.4, stagger: 0.2, ease: 'power1.out' }, '<')
      .from('#pool-hole', { scaleY: 0, transformOrigin: '50% 0%', duration: 0.8 })
      .from('#pool-shell', { opacity: 0, duration: 0.5 })
      .fromTo('#water-clip', { attr: { y: 640, height: 0 } }, { attr: { y: G + 6, height: 84 }, duration: 1.2 })
      .from('#pavers rect', { y: -60, opacity: 0, duration: 0.3, stagger: 0.04, ease: 'power2.out' }, '>-0.4')
      .from('#new-fence rect', { scaleY: 0, transformOrigin: '50% 100%', duration: 0.3, stagger: 0.02 }, '<')

    // 04 Turf and planting: lawn rolls out, deck, garden beds, trees grow.
      .addLabel('plant')
      .from('#turf', { scaleX: 0, transformOrigin: '0% 50%', duration: 1.2 })
      .from('#planks rect', { scaleY: 0, transformOrigin: '50% 100%', duration: 0.25, stagger: 0.04 }, '<')
      .from('#bricks rect', { y: -40, opacity: 0, duration: 0.25, stagger: 0.02 }, '<0.3')
      .from('#trees > *', { scale: 0, transformOrigin: '50% 100%', duration: 0.8, stagger: 0.15, ease: 'back.out(1.6)' }, '>-0.3')
      .from('#shrubs > *', { scale: 0, transformOrigin: '50% 100%', duration: 0.4, stagger: 0.06, ease: 'back.out(2)' }, '<0.2')
      .from('#flowers circle', { scale: 0, transformOrigin: '50% 50%', duration: 0.25, stagger: 0.03, ease: 'back.out(3)' }, '<0.3')
      .from('#lights > *', { scaleY: 0, transformOrigin: '50% 100%', duration: 0.3, stagger: 0.08 }, '<')
      .to('#crew > *', { x: 1400, duration: 1.4, stagger: 0.15, ease: 'power1.in' }, '<')

    // 05 Enjoy: golden hour, lights on, people in the garden.
      .addLabel('enjoy')
      .to('#golden', { opacity: 1, duration: 1.4 })
      .from('#umbrella', { scaleX: 0, transformOrigin: '50% 100%', duration: 0.6, ease: 'back.out(2)' }, '<0.2')
      .from('#people > *', { opacity: 0, y: 20, duration: 0.6, stagger: 0.2 }, '<')
      .to('#lamp-glow', { opacity: 1, duration: 0.8 }, '>-0.3')
      .to('#pool-glow', { opacity: 0.55, duration: 0.8 }, '<')
      .fromTo('#ripples path', { x: -10 }, { x: 10, duration: 1.4, ease: 'sine.inOut' }, '<')
      .to({}, { duration: 0.8 });
  };
})();
