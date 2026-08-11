import { Fragment, useEffect, useRef, useState } from 'react';
import { motion, AnimatePresence, useScroll, useTransform } from 'framer-motion';
import { HERO_PLATES } from './media.js';

/* ═══════════════════════════════════════════════
   Cinematic full-bleed hero.

   A slow crossfading plate carousel with a Ken Burns
   drift underneath one statement headline. The plates
   are stills rather than video: three graded frames
   cost ~400KB against ~20MB for a loop of comparable
   length, and at this pace the read is identical.
   ═══════════════════════════════════════════════ */

const DWELL = 6400;

const WORDS = 'Threat-tested machine learning for systems that cannot fail.'.split(' ');

export default function Hero() {
  const [i, setI] = useState(0);
  const [playing, setPlaying] = useState(true);
  const ref = useRef(null);

  const { scrollYProgress } = useScroll({ target: ref, offset: ['start start', 'end start'] });
  const plateY = useTransform(scrollYProgress, [0, 1], ['0%', '18%']);
  const copyY = useTransform(scrollYProgress, [0, 1], ['0%', '48%']);
  const copyO = useTransform(scrollYProgress, [0, 0.55], [1, 0]);

  useEffect(() => {
    if (!playing) return;
    const t = setTimeout(() => setI((v) => (v + 1) % HERO_PLATES.length), DWELL);
    return () => clearTimeout(t);
  }, [i, playing]);

  /* decode the next plate ahead of its turn so the crossfade
     never lands on a half-painted image */
  useEffect(() => {
    const nxt = new Image();
    nxt.src = HERO_PLATES[(i + 1) % HERO_PLATES.length].src;
  }, [i]);

  const plate = HERO_PLATES[i];

  return (
    <section id="hero" ref={ref}>
      <motion.div className="hero-plates" style={{ y: plateY }}>
        <AnimatePresence initial={false}>
          <motion.div
            key={i}
            className="hero-plate"
            initial={{ opacity: 0, scale: 1.14 }}
            animate={{ opacity: 1, scale: 1.02, transition: { opacity: { duration: 1.5, ease: 'easeInOut' }, scale: { duration: DWELL / 1000 + 1.6, ease: 'linear' } } }}
            exit={{ opacity: 0, transition: { duration: 1.5, ease: 'easeInOut' } }}
          >
            <img src={plate.src} alt={plate.alt} fetchPriority={i === 0 ? 'high' : 'auto'} />
          </motion.div>
        </AnimatePresence>
      </motion.div>

      <div className="hero-scrim" />

      <motion.div className="hero-copy" style={{ y: copyY, opacity: copyO }}>
        <motion.div
          className="hero-eyebrow"
          initial={{ opacity: 0, y: 14 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.25, duration: 0.7 }}
        >
          <span className="he-rule" />
          Pratik More <i>/</i> AI &amp; Security Engineer
        </motion.div>

        {/* each word rides up behind its own mask. The spaces are real
            text nodes between the masks, so the headline still wraps
            naturally and reads as a sentence to a screen reader */}
        <h1 className="hero-h1">
          {WORDS.map((w, n) => (
            <Fragment key={n}>
              <span className="hw">
                <motion.span
                  initial={{ y: '105%' }}
                  animate={{ y: '0%' }}
                  transition={{ delay: 0.4 + n * 0.055, duration: 0.85, ease: [0.16, 1, 0.3, 1] }}
                >
                  {w}
                </motion.span>
              </span>{' '}
            </Fragment>
          ))}
        </h1>

        <motion.div
          className="ai-line"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 1.15, duration: 0.8 }}
        >
          <span id="aiText" /><span className="ai-caret" />
        </motion.div>
      </motion.div>

      {/* a sibling of hero-copy, not a child: it anchors to the section
          so the parallax on the copy cannot drag it over the headline */}
      <motion.div
        className="hero-meta"
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ delay: 1.3, duration: 0.8 }}
      >
        <span><span className="dot" />Available for AI &amp; security roles</span>
        <span>52.40&deg;N 1.51&deg;W <i>/</i> Coventry, UK</span>
      </motion.div>

      <div className="hero-ctrl">
        {HERO_PLATES.map((p, n) => (
          <button
            key={p.id}
            type="button"
            className={'hc-tick' + (n === i ? ' on' : '')}
            aria-label={`Show frame ${n + 1}: ${p.alt}`}
            onClick={() => setI(n)}
          >
            <i style={{ animationDuration: `${DWELL}ms`, animationPlayState: playing ? 'running' : 'paused' }} />
          </button>
        ))}
        <button
          type="button"
          className="hc-pp"
          aria-label={playing ? 'Pause the hero carousel' : 'Play the hero carousel'}
          onClick={() => setPlaying((p) => !p)}
        >
          {playing ? '❙❙' : '▶'}
        </button>
      </div>

      <motion.a
        href="#about"
        className="hero-scroll"
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ delay: 1.5, duration: 0.8 }}
        onClick={(e) => {
          e.preventDefault();
          const el = document.getElementById('about');
          if (el) window.__lenis ? window.__lenis.scrollTo(el, { duration: 1.2 }) : el.scrollIntoView({ behavior: 'smooth' });
        }}
      >
        <span>Scroll</span>
        <motion.i animate={{ y: [0, 7, 0] }} transition={{ duration: 1.9, repeat: Infinity, ease: 'easeInOut' }}>↓</motion.i>
      </motion.a>
    </section>
  );
}
