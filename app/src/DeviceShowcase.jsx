import { useRef } from 'react';
import { motion, useScroll, useTransform, useSpring, useMotionValueEvent } from 'framer-motion';

/* ═══════════════════════════════════════════════
   Apple-style product showcase.
   framer-motion's useScroll drives a spring, and the
   spring value is pushed into the three.js module so
   the gadget rotates, tilts and separates in lockstep
   with the scroll instead of on a timer.
   ═══════════════════════════════════════════════ */

const SPECS = [
  { at: 0.10, k: 'INFER', t: 'Models at line rate',
    d: 'Random Forest and anomaly detectors score every event as it lands, not in tomorrow’s batch.' },
  { at: 0.45, k: 'DECIDE', t: 'Policy in silicon',
    d: 'Risk thresholds, RBAC and MFA gates resolve in milliseconds, fully auditable.' },
  { at: 0.78, k: 'CONTAIN', t: 'Zero-touch response',
    d: 'Playbooks isolate the host and ban the source. Mean time to contain: 41 seconds.' },
];

export default function DeviceShowcase() {
  const ref = useRef(null);
  const { scrollYProgress } = useScroll({ target: ref, offset: ['start end', 'end start'] });
  const smooth = useSpring(scrollYProgress, { stiffness: 70, damping: 24, mass: 0.4 });

  // framer-motion is the source of truth; three.js just follows it
  useMotionValueEvent(smooth, 'change', (v) => {
    if (window.__device) window.__device.setProgress(v);
  });

  const headY = useTransform(smooth, [0, 1], [40, -40]);
  const headO = useTransform(smooth, [0, 0.12, 0.9, 1], [0, 1, 1, 0]);

  return (
    <section className="device" ref={ref} id="module">
      <div className="dv-sticky">
        <canvas id="device-canvas"></canvas>

        <motion.div className="dv-head" style={{ y: headY, opacity: headO }}>
          <div className="section-eyebrow">NSM-100 AI Accelerator</div>
          <h2 className="section-title">Intelligence and defence,<br />on one card.</h2>
        </motion.div>

        {SPECS.map((s) => (
          <Spec key={s.k} spec={s} p={smooth} />
        ))}

        <motion.div className="dv-hint"
          style={{ opacity: useTransform(smooth, [0, 0.08, 0.2], [0, 1, 0]) }}>
          scroll to disassemble
        </motion.div>
      </div>
    </section>
  );
}

function Spec({ spec, p }) {
  const o = useTransform(p, [spec.at - 0.13, spec.at, spec.at + 0.13], [0, 1, 0]);
  const x = useTransform(p, [spec.at - 0.13, spec.at, spec.at + 0.13], [46, 0, -46]);
  return (
    <motion.div className="dv-spec" style={{ opacity: o, x }}>
      <span className="dv-k">{spec.k}</span>
      <h3>{spec.t}</h3>
      <p>{spec.d}</p>
    </motion.div>
  );
}
