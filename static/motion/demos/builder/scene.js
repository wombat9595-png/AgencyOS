/* Builder story scene: blueprint, slab, frame, lock-up, handover, then an extension. */
(function () {
  var NS = 'http://www.w3.org/2000/svg';
  function el(tag, attrs, parent) {
    var n = document.createElementNS(NS, tag);
    for (var k in attrs) n.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(n);
    return n;
  }

  window.MotionScenes = window.MotionScenes || {};
  window.MotionScenes.build = function (tl, section) {
    var q = function (s) { return section.querySelector(s); };
    var qa = function (s) { return section.querySelectorAll(s); };

    // Repetitive parts are generated so the markup stays readable.
    var studs = q('#studs'), extStuds = q('#ext-studs'), boards = q('#boards'), extBoards = q('#ext-boards');
    for (var x = 392; x <= 808; x += 26) el('rect', { x: x - 3, y: 420, width: 6, height: 168, rx: 1 }, studs);
    for (var ex = 836; ex <= 996; ex += 26) el('rect', { x: ex - 3, y: 470, width: 6, height: 118, rx: 1 }, extStuds);
    for (var y = 432; y < 588; y += 13) el('line', { x1: 380, x2: 820, y1: y, y2: y }, boards);
    for (var ey = 482; ey < 588; ey += 13) el('line', { x1: 820, x2: 1000, y1: ey, y2: ey }, extBoards);

    var bpLines = qa('#bp [data-line]');
    bpLines.forEach(function (p) {
      var len = p.getTotalLength();
      p.style.strokeDasharray = len;
      p.style.strokeDashoffset = len;
    });

    // 01 Plans: blueprint draws itself.
    tl.addLabel('plans')
      .to(bpLines, { strokeDashoffset: 0, duration: 2, stagger: 0.08 })
      .from('#bp-notes text', { opacity: 0, duration: 0.5, stagger: 0.15 }, '-=0.8')
      .to({}, { duration: 0.6 })

    // 02 Slab: the blueprint lifts away to reveal the site.
      .addLabel('slab')
      .to('#blueprint', { opacity: 0, duration: 1 })
      .to('#bp', { opacity: 0.22, duration: 1 }, '<')
      .from('#ground', { yPercent: 40, duration: 1 }, '<')
      .from('#excavator', { x: -700, duration: 1.4, ease: 'power1.out' }, '<0.3')
      .to('#excavator .arm', { rotation: -18, transformOrigin: '20% 80%', duration: 0.4, yoyo: true, repeat: 3 }, '>-0.2')
      .from('#slab', { scaleY: 0, transformOrigin: '50% 100%', duration: 0.8 }, '>-0.4')
      .to('#excavator', { x: 1700, duration: 1.4, ease: 'power1.in' })

    // 03 Frame: studs rise, crane lowers the roof trusses.
      .addLabel('frame')
      .from('#crane', { y: 1500, duration: 1, ease: 'power2.out' }, '<0.2')
      .from('#studs rect', { scaleY: 0, transformOrigin: '50% 100%', duration: 0.5, stagger: 0.05 }, '<0.4')
      .from('#top-plate', { scaleX: 0, transformOrigin: '0% 50%', duration: 0.5 }, '>-0.2')
      .from('#tradie-a', { x: -500, duration: 1.6 }, '<-0.6')
      .to('#trolley', { x: -380, duration: 1 })
      .fromTo('#hook-line', { attr: { y2: 130 } }, { attr: { y2: 300 }, duration: 1 })
      .fromTo('#trusses', { y: -170, opacity: 0 }, { y: 0, opacity: 1, duration: 1 }, '<')
      .to('#hook-line', { attr: { y2: 130 }, duration: 0.6 })
      .to('#trolley', { x: 0, duration: 0.6 }, '<')

    // 04 Lock-up: walls clad from the ground up, windows in, roof sheeted.
      .addLabel('lockup')
      .fromTo('#wall-clip', { attr: { y: 588, height: 0 } }, { attr: { y: 420, height: 168 }, duration: 1.4 })
      .from('#windows > *', { scale: 0, transformOrigin: '50% 50%', duration: 0.4, stagger: 0.15 }, '>-0.3')
      .fromTo('#roof-clip', { attr: { width: 0 } }, { attr: { width: 520 }, duration: 1.2 })
      .from('#gutter', { scaleX: 0, transformOrigin: '0% 50%', duration: 0.5 }, '>-0.3')
      .to('#crane', { y: 1500, duration: 1, ease: 'power2.in' }, '<')
      .to('#tradie-a', { x: 520, duration: 1.4 }, '<')

    // 05 Handover: paint, garden, lights on at dusk.
      .addLabel('handover')
      .to('#paint', { opacity: 1, duration: 0.8 })
      .to('#bp', { opacity: 0, duration: 0.8 }, '<')
      .from('#door', { scaleY: 0, transformOrigin: '50% 100%', duration: 0.5 }, '<0.3')
      .from('#lawn', { scaleX: 0, transformOrigin: '50% 50%', duration: 1 }, '<')
      .from('#path', { scaleY: 0, transformOrigin: '50% 0%', duration: 0.6 }, '>-0.4')
      .from('#garden > *', { scale: 0, transformOrigin: '50% 100%', duration: 0.5, stagger: 0.08, ease: 'back.out(2)' }, '<')
      .to('#dusk', { opacity: 1, duration: 1.2 }, '<')
      .to('#glow', { opacity: 1, duration: 0.8 }, '>-0.6')
      .from('#family', { opacity: 0, x: -40, duration: 0.8 }, '<')
      .to({}, { duration: 0.6 })

    // 06 Extension: the same house grows a new living room.
      .addLabel('extension')
      .to('#dusk', { opacity: 0, duration: 0.8 })
      .to('#glow', { opacity: 0.35, duration: 0.8 }, '<')
      .from('#ext-slab', { scaleX: 0, transformOrigin: '0% 50%', duration: 0.6 }, '<')
      .from('#ext-studs rect', { scaleY: 0, transformOrigin: '50% 100%', duration: 0.4, stagger: 0.05 })
      .fromTo('#ext-wall-clip', { attr: { y: 588, height: 0 } }, { attr: { y: 470, height: 118 }, duration: 1 })
      .from('#ext-roof', { y: -220, opacity: 0, duration: 0.8, ease: 'power2.out' })
      .from('#ext-glass', { scaleX: 0, transformOrigin: '0% 50%', duration: 0.6 })
      .to('#ext-paint', { opacity: 1, duration: 0.6 })
      .from('#ext-garden > *', { scale: 0, transformOrigin: '50% 100%', duration: 0.4, stagger: 0.08, ease: 'back.out(2)' }, '<')
      .to('#dusk', { opacity: 1, duration: 1 })
      .to('#glow, #ext-glow', { opacity: 1, duration: 0.8 }, '<0.3')
      .to({}, { duration: 0.8 });
  };
})();
