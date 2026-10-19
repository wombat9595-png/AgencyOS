/* Salon story scene: hair drawn live from numbers, so scrolling cuts it, waves it, curls it and colours it. */
(function () {
  var NS = 'http://www.w3.org/2000/svg';

  // Root and tip colours for each look; the timeline blends between them.
  var PALETTES = [
    ['#2b1a12', '#4a2e1f'], // natural brunette
    ['#3a2216', '#d9a66b'], // honey balayage
    ['#5e2412', '#e8874a'], // copper
  ];
  function mix(a, b, t) {
    var pa = parseInt(a.slice(1), 16), pb = parseInt(b.slice(1), 16);
    var r = Math.round(((pa >> 16) & 255) * (1 - t) + ((pb >> 16) & 255) * t);
    var g = Math.round(((pa >> 8) & 255) * (1 - t) + ((pb >> 8) & 255) * t);
    var bl = Math.round((pa & 255) * (1 - t) + (pb & 255) * t);
    return '#' + ((1 << 24) | (r << 16) | (g << 8) | bl).toString(16).slice(1);
  }
  function palette(c, end) {
    var i = Math.min(PALETTES.length - 2, Math.floor(c));
    return mix(PALETTES[i][end], PALETTES[i + 1][end], Math.min(1, c - i));
  }

  window.MotionScenes = window.MotionScenes || {};
  window.MotionScenes.hair = function (tl, section) {
    var svg = section.querySelector('.scene-svg');
    var group = section.querySelector('#strands');
    var stops = section.querySelectorAll('#hair-grad stop');
    var shineStops = section.querySelectorAll('#hair-shine stop');
    var darkStops = section.querySelectorAll('#hair-dark stop');
    var small = window.matchMedia('(max-width: 799px)').matches;
    var COUNT = small ? 70 : 120, POINTS = small ? 110 : 150;

    // Hair shape, all tweened by the timeline.
    // Roots sit above the top of the screen, so the hair pours in like a curtain.
    var H = { len: 1420, amp: 6, freq: 2, curl: 0, phase: 0, volume: 0.08, colour: 0, sway: 1 };

    var strands = [];
    function rand(i, k) { var v = Math.sin(i * 12.9898 + k * 78.233) * 43758.5453; return v - Math.floor(v); }
    var TONES = ['url(#hair-grad)', 'url(#hair-dark)', 'url(#hair-grad)', 'url(#hair-shine)'];
    for (var i = 0; i < COUNT; i++) {
      var p = document.createElementNS(NS, 'path');
      var tone = i % 4;
      p.setAttribute('stroke', TONES[tone]);
      p.setAttribute('stroke-width', [4.6, 5.6, 3.8, 2.6][tone]);
      p.setAttribute('opacity', [0.95, 0.8, 0.95, 0.9][tone]);
      group.appendChild(p);
      strands.push({
        el: p,
        x0: 100 + 1000 * (i + rand(i, 3) * 0.8) / COUNT, // evenly spread, slightly irregular
        y0: -720,
        seed: rand(i, 1) * Math.PI * 2, // independent offsets so neighbours never move in step
        lenJitter: 0.9 + rand(i, 2) * 0.16,
      });
    }

    function draw() {
      var c = H.colour;
      stops[0].setAttribute('stop-color', palette(c, 0));
      stops[1].setAttribute('stop-color', palette(c, 1));
      shineStops[0].setAttribute('stop-color', mix(palette(c, 0), '#ffffff', 0.25));
      shineStops[1].setAttribute('stop-color', mix(palette(c, 1), '#fff4e0', 0.45));
      darkStops[0].setAttribute('stop-color', mix(palette(c, 0), '#000000', 0.35));
      darkStops[1].setAttribute('stop-color', mix(palette(c, 1), '#1a0d08', 0.35));
      strands.forEach(function (s) {
        var len = H.len * s.lenJitter, d = '';
        var spread = (s.x0 - 600) * H.volume;
        for (var k = 0; k <= POINTS; k++) {
          var t = k / POINTS;
          var theta = Math.PI * 2 * H.freq * t * (len / 600) + H.phase + s.seed;
          var growth = t * t; // roots stay put, ends move most
          var x = s.x0 + spread * t + H.amp * Math.sin(theta) * growth + Math.sin(H.phase * 0.5 + s.seed) * 16 * H.sway * t * t;
          var y = s.y0 + len * t + H.curl * Math.cos(theta) * growth;
          d += (k ? 'L' : 'M') + x.toFixed(1) + ' ' + y.toFixed(1);
        }
        s.el.setAttribute('d', d);
      });
    }

    var sparkles = section.querySelectorAll('#sparkles path');

    // The phase runs through the whole scene so the hair is always moving while you scroll.
    tl.to(H, { phase: Math.PI * 10, duration: 14, ease: 'none' }, 0);

    tl.addLabel('flow', 0)
      .to(H, { sway: 2.2, duration: 1.6, ease: 'sine.inOut' }, 0)
      .to(H, { sway: 1, duration: 1, ease: 'sine.inOut' }, 1.6)

      .addLabel('cut', 2.6)
      .fromTo('#scissors', { x: -400 }, { x: 1700, duration: 2, ease: 'power1.inOut' }, 2.6)
      .to('#blade-a', { rotation: -16, transformOrigin: '50% 50%', duration: 0.16, yoyo: true, repeat: 11, ease: 'power1.inOut' }, 2.6)
      .to('#blade-b', { rotation: 16, transformOrigin: '50% 50%', duration: 0.16, yoyo: true, repeat: 11, ease: 'power1.inOut' }, 2.6)
      .to(H, { len: 1180, duration: 2, ease: 'power1.inOut' }, 2.6)
      .fromTo('#snips path', { y: 0, opacity: 0, rotation: 0 }, { y: 360, opacity: 1, rotation: 70, transformOrigin: '50% 50%', duration: 1.4, stagger: 0.06, ease: 'power1.in' }, 2.8)
      .to('#snips path', { opacity: 0, duration: 0.4, stagger: 0.06 }, 3.9)

      .addLabel('waves', 5)
      .to(H, { amp: 34, freq: 3.2, volume: 0.14, duration: 2, ease: 'power2.inOut' }, 5)

      .addLabel('curls', 7.4)
      .to(H, { curl: 28, freq: 6, amp: 26, len: 1200, volume: 0.2, duration: 2.2, ease: 'power2.inOut' }, 7.4)

      .addLabel('colour', 10)
      .to(H, { colour: 2, duration: 2.4, ease: 'power1.inOut' }, 10)
      .fromTo(sparkles, { scale: 0, opacity: 0, transformOrigin: '50% 50%' }, { scale: 1, opacity: 1, duration: 0.4, stagger: 0.12, yoyo: true, repeat: 1 }, 10.4)
      .to({}, { duration: 1.2 }, 12.4);

    tl.eventCallback('onUpdate', draw);
    draw();
  };
})();
