/* ════════════════════════════════════════════════
   MAGNETIC JARVIS CURSOR dot + trailing ring that
   morphs by context and magnetizes onto targets
════════════════════════════════════════════════ */
let inited = false;

export function initCursor() {
  if (inited || matchMedia('(hover:none)').matches) return;
  inited = true;
  document.documentElement.classList.add('has-cursor');

  const dot = document.createElement('div'); dot.id = 'cDot';
  const ring = document.createElement('div'); ring.id = 'cRing';
  ring.innerHTML = '<span class="cr-label"></span>';
  document.body.append(ring, dot);
  const label = ring.querySelector('.cr-label');

  let mx = innerWidth / 2, my = innerHeight / 2, rx = mx, ry = my;
  let mode = '', tgt = null, tgtRect = null, tgtAt = 0;
  let raf = null;
  const wake = () => { if (!raf) raf = requestAnimationFrame(frame); };

  addEventListener('mousemove', (e) => {
    mx = e.clientX; my = e.clientY;
    wake();
    const el = e.target;
    const link = el.closest && el.closest('a,button');
    const row = !link && el.closest && el.closest('.work-row');
    const hero = !link && !row && el.closest && el.closest('#hero');
    let m = '', t = null, lab = '';
    if (link) { m = 'link'; t = link; }
    else if (row) { m = 'open'; lab = 'OPEN ⌖'; }
    else if (hero) { m = 'aim'; }
    if (m !== mode || t !== tgt) {
      mode = m; tgt = t; tgtRect = null;
      label.textContent = lab;
      ring.className = m ? 'm-' + m : '';
    }
  }, { passive: true });
  addEventListener('mousedown', () => { ring.classList.add('down'); wake(); }, { passive: true });
  addEventListener('mouseup', () => { ring.classList.remove('down'); wake(); }, { passive: true });

  function frame() {
    raf = null;
    let ax = mx, ay = my;
    if (mode === 'link' && tgt) {
      const now = performance.now();
      if (!tgtRect || now - tgtAt > 250) { tgtRect = tgt.getBoundingClientRect(); tgtAt = now; }
      const cx = tgtRect.left + tgtRect.width / 2, cy = tgtRect.top + tgtRect.height / 2;
      ax = mx + (cx - mx) * 0.35; ay = my + (cy - my) * 0.35; // magnetic pull
    }
    rx += (ax - rx) * 0.18; ry += (ay - ry) * 0.18;
    dot.style.transform = `translate(${mx}px,${my}px)`;
    ring.style.transform = `translate(${rx}px,${ry}px)`;
    // keep animating only until the ring settles onto the target
    if (Math.abs(ax - rx) > 0.3 || Math.abs(ay - ry) > 0.3) wake();
  }
  frame();
}
