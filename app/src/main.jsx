import { createRoot } from 'react-dom/client';
import Lenis from 'lenis';
import App from './App.jsx';
import './styles.css';

/* ── Lenis drives the page scroll ──────────────────────────
   This is the single biggest reason a site like williamsgptech
   feels expensive to scroll: wheel input is interpolated rather
   than applied in the browser's discrete jumps. Lenis still
   moves the real scroll position and still emits native scroll
   events, so IntersectionObserver, framer-motion's useScroll and
   the existing engine listeners all keep working unchanged.
   Users who ask for reduced motion get the native scroll back. */
const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;

if (!reduced) {
  const lenis = new Lenis({
    duration: 1.05,
    easing: (t) => Math.min(1, 1.001 - Math.pow(2, -10 * t)),
    smoothWheel: true,
    touchMultiplier: 1.6,
  });
  window.__lenis = lenis;

  const raf = (time) => { lenis.raf(time); requestAnimationFrame(raf); };
  requestAnimationFrame(raf);

  /* the project modal locks the page behind it; Lenis has to be
     told, or the page keeps scrolling underneath the overlay */
  window.__scrollLock = (on) => (on ? lenis.stop() : lenis.start());
}

// no StrictMode: the WebGL engine must initialise exactly once
createRoot(document.getElementById('root')).render(<App />);
