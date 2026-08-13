import { useEffect, useRef, useState, useCallback } from 'react';
import { motion } from 'framer-motion';
import { SECTOR_IMG } from './media.js';

/* ═══════════════════════════════════════════════
   Sector carousel.

   Full-bleed photographic cards on a draggable track,
   with arrows and keyboard control. Card width is
   measured rather than assumed so the same component
   works from a phone to an ultrawide.
   ═══════════════════════════════════════════════ */

const SECTORS = [
  { k: 'detect', n: 'Detection', img: SECTOR_IMG.detect,
    d: 'Multi-OS telemetry into one pane. Wazuh agents across Windows and Linux, hunted against MITRE ATT&CK.',
    stat: 'T1110 caught and banned', proj: 'wazuh' },
  { k: 'respond', n: 'Response', img: SECTOR_IMG.respond,
    d: 'Zero-touch containment. Sentinel and Logic Apps isolate the host and ban the source with no human in the loop.',
    stat: 'MTTC 380s → 41s', proj: 'soar' },
  { k: 'ml', n: 'Applied ML', img: SECTOR_IMG.ml,
    d: 'Forecasting that holds up in production. Engineered time and lag features over twelve months of live demand.',
    stat: 'MAPE 15.5% → 4.6%', proj: 'wfm' },
  /* this plate is a dusk exterior and sits brighter than the rest of the
     set, so it carries an extra grade to keep the row even */
  { k: 'intel', n: 'Intelligence', img: SECTOR_IMG.intel, dim: true,
    d: 'Reasoning that never leaves the building. Local LLM inference with the network cable unplugged.',
    stat: '100% offline', proj: 'jarvis' },
  { k: 'govern', n: 'Governance', img: SECTOR_IMG.govern,
    d: 'Risk surfaced before it lands. Behavioural tripwires score vendor accounts the moment they deviate.',
    stat: '167MB pipeline', proj: 'vendor' },
];

export default function Sectors() {
  const [i, setI] = useState(0);
  const [step, setStep] = useState(0);
  const trackRef = useRef(null);
  const cardRef = useRef(null);

  /* measure once and on resize: the track translates by a real
     pixel step, so no CSS/JS width assumption can drift apart */
  useEffect(() => {
    const measure = () => {
      if (!cardRef.current) return;
      const el = cardRef.current;
      const gap = parseFloat(getComputedStyle(el.parentElement).columnGap || 0) || 0;
      setStep(el.getBoundingClientRect().width + gap);
    };
    measure();
    const ro = new ResizeObserver(measure);
    if (cardRef.current) ro.observe(cardRef.current);
    addEventListener('resize', measure);
    return () => { ro.disconnect(); removeEventListener('resize', measure); };
  }, []);

  const go = useCallback((d) => setI((v) => Math.min(SECTORS.length - 1, Math.max(0, v + d))), []);

  const onKey = (e) => {
    if (e.key === 'ArrowRight') { e.preventDefault(); go(1); }
    if (e.key === 'ArrowLeft') { e.preventDefault(); go(-1); }
  };

  const open = (p) => window.projModalApi && window.projModalApi.open(p);

  return (
    <section className="sectors" id="sectors">
      <div className="sec-head">
        <motion.div className="section-eyebrow"
          initial={{ opacity: 0, y: 18 }} whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, amount: 0.6 }} transition={{ duration: 0.7 }}>
          Where I work
        </motion.div>
        <motion.h2 className="section-title"
          initial={{ opacity: 0, y: 26 }} whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, amount: 0.6 }} transition={{ duration: 0.8, delay: 0.08 }}>
          I build for systems where a missed signal is measured in downtime.
        </motion.h2>

        <div className="sec-nav">
          <button type="button" onClick={() => go(-1)} disabled={i === 0} aria-label="Previous sector">←</button>
          <span className="sec-count">{String(i + 1).padStart(2, '0')} <i>/</i> {String(SECTORS.length).padStart(2, '0')}</span>
          <button type="button" onClick={() => go(1)} disabled={i === SECTORS.length - 1} aria-label="Next sector">→</button>
        </div>
      </div>

      <div className="sec-viewport" ref={trackRef} tabIndex={0} onKeyDown={onKey}
        role="group" aria-roledescription="carousel" aria-label="Sectors">
        <motion.div className="sec-track"
          drag="x"
          dragConstraints={{ left: -step * (SECTORS.length - 1), right: 0 }}
          dragElastic={0.08}
          animate={{ x: -i * step }}
          transition={{ type: 'spring', stiffness: 260, damping: 34, mass: 0.7 }}
          onDragEnd={(e, info) => {
            const thrown = info.velocity.x < -260 || info.offset.x < -step * 0.3;
            const back = info.velocity.x > 260 || info.offset.x > step * 0.3;
            if (thrown) go(1); else if (back) go(-1); else setI((v) => v);
          }}
        >
          {SECTORS.map((s, n) => (
            <motion.article
              key={s.k}
              ref={n === 0 ? cardRef : null}
              className={'sec-card' + (n === i ? ' on' : '')}
              onClick={() => (n === i ? open(s.proj) : setI(n))}
              initial={{ opacity: 0, y: 40 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true, amount: 0.2 }}
              transition={{ duration: 0.7, delay: Math.min(n, 3) * 0.07 }}
            >
              <div className={'sc-media' + (s.dim ? ' dim' : '')}>
                <img src={s.img} alt="" loading={n < 2 ? 'eager' : 'lazy'} draggable={false} />
                <span className="sc-idx">{String(n + 1).padStart(2, '0')}</span>
              </div>
              <div className="sc-body">
                <h3>{s.n}</h3>
                <p>{s.d}</p>
                <div className="sc-foot">
                  <span className="sc-stat">{s.stat}</span>
                  <span className="sc-go">View project →</span>
                </div>
              </div>
            </motion.article>
          ))}
        </motion.div>
      </div>

      <div className="sec-bar" aria-hidden="true">
        <motion.i animate={{ scaleX: (i + 1) / SECTORS.length }}
          transition={{ type: 'spring', stiffness: 180, damping: 30 }} />
      </div>
    </section>
  );
}
