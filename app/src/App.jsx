import { useEffect, useRef, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { startEngine } from './engine.js';

/* ── framer-motion variants: springy scroll reveals ── */
const rise = {
  hidden: { opacity: 0, y: 36 },
  show: { opacity: 1, y: 0, transition: { type: 'spring', stiffness: 90, damping: 16 } },
};
const riseSoft = {
  hidden: { opacity: 0, y: 24 },
  show: { opacity: 1, y: 0, transition: { type: 'spring', stiffness: 70, damping: 15 } },
};
const stagger = { hidden: {}, show: { transition: { staggerChildren: 0.12 } } };
const inView = { once: true, amount: 0.25 };

/* ── project data (drives cards AND the summary modal) ── */
const PROJECTS = {
  soar: {
    num: '01', title: 'Cloud-Native SOAR Engine', type: 'MSc Dissertation · 2026',
    modalType: 'MSc Dissertation · Microsoft Sentinel',
    blurb: '"Zero-Touch" automated containment with Microsoft Sentinel & Azure Logic Apps to mitigate high-velocity ransomware.',
    desc: 'A "zero-touch" security orchestration engine that detects and contains high-velocity ransomware without a human in the loop, built on Microsoft Sentinel and Azure Logic Apps.',
    points: [
      'Benchmarked automated containment vs manual triage — Mean-Time-to-Contain cut from 380s to 41s',
      'Logic Apps playbooks isolate VMs, disable accounts and ban attacker IPs automatically',
      'Dissertation research on cloud-native SOAR architecture (2026)',
    ],
    tags: ['Sentinel', 'Azure', 'SOAR'], modalTags: ['Sentinel', 'Azure', 'Logic Apps', 'SOAR', 'KQL'],
    img: 'soar.jpg.jpeg', impact: '↯ MTTC 380s → 41s',
    links: [['GitHub ↗', 'https://github.com/Pratikm7073/Azure-Sentinel-SOAR-Automation']],
  },
  wazuh: {
    num: '02', title: 'Enterprise SIEM & Incident Response Lab', type: 'Wazuh · Home Lab',
    modalType: 'Wazuh · Multi-OS Home Lab',
    blurb: 'Multi-OS SIEM lab ingesting Windows & Linux endpoint logs. Detected simulated SSH brute-force (MITRE ATT&CK T1110) and fired an Active Response that auto-banned the attacker’s IP at the firewall.',
    desc: 'A local SIEM environment simulating real-world cyber threats: a Wazuh manager aggregating endpoint logs from Windows 10 and Ubuntu VMs over encrypted tunnels, with automated active response.',
    points: [
      'Wazuh agents deployed across Windows & Linux with secure agent-to-manager communication',
      'Simulated SSH brute-force attack, hunted IoCs and mapped them to MITRE ATT&CK T1110',
      'Custom Active Response (rules 5710/5712) auto-modifies the endpoint firewall to ban the attacker IP',
    ],
    tags: ['Wazuh', 'MITRE ATT&CK', 'VirtualBox', 'Bash'], modalTags: ['Wazuh', 'MITRE ATT&CK', 'VirtualBox', 'PowerShell', 'Bash'],
    img: 'https://raw.githubusercontent.com/pratikm7073/wazuh-siem-home-lab/main/dashboard.PNG', impact: '↯ Auto IP ban on attack',
    links: [['GitHub ↗', 'https://github.com/Pratikm7073/Wazuh-SIEM-Home-Lab']],
  },
  wfm: {
    num: '03', title: 'AI-Enhanced WFM Capacity Planning Engine', type: 'Python · ML Forecasting',
    modalType: 'Python · ML Forecasting · Power BI',
    blurb: 'Random Forest demand forecaster over 12 months of multi-site contact-centre data, cutting forecast error from ~15.5% to ~4.6% MAPE vs the traditional method — plus Erlang C capacity model and an interactive dashboard.',
    desc: 'An end-to-end workforce management engine: machine-learning demand forecasting, Erlang C capacity modelling, and stakeholder-ready dashboards across a multi-site, multi-channel contact-centre operation.',
    points: [
      'Random Forest with engineered time/lag features beats the day-of-week baseline: ~15.5% → ~4.6% MAPE',
      '4,380 rows · 4 UK sites · 3 channels · 12 months, with storm events & chatbot deflection built in',
      'Erlang C Excel model converts forecast volume into FTE requirements with shrinkage & SLA targets',
      'Self-contained interactive dashboard in raw SVG + vanilla JS — runs offline in any browser',
    ],
    tags: ['scikit-learn', 'Pandas', 'Erlang C', 'Power BI'], modalTags: ['scikit-learn', 'Pandas', 'Erlang C', 'Power BI', 'Feature Engineering'],
    img: 'https://raw.githubusercontent.com/pratikm7073/ai-wfm-capacity-planning-engine/main/ai_forecast_comparison.png', impact: '↯ MAPE 15.5% → 4.6%',
    links: [['GitHub ↗', 'https://github.com/Pratikm7073/ai-wfm-capacity-planning-engine'], ['Live Dashboard ↗', 'https://pratikm7073.github.io/WFM_Dashboard.html']],
  },
  jarvis: {
    num: '04', title: 'Jarvis-AI — Offline Voice Assistant', type: 'Local LLM · Zero-Trust',
    modalType: 'Local LLM · Zero-Trust Architecture',
    blurb: 'Fully offline voice assistant: Vosk speech recognition, Microsoft Phi-3 reasoning via Ollama, and native text-to-speech — not a single byte leaves the machine. Voice kill-switch included.',
    desc: 'A completely offline, zero-trust voice assistant: it listens, reasons with a locally hosted LLM, and speaks back — without sending a single byte to the cloud.',
    points: [
      'Vosk transcribes speech locally; Microsoft Phi-3 reasons via Ollama; pyttsx3 speaks the reply natively',
      'Zero-trust: fully functional with the network cable unplugged',
      'Voice kill-switch — saying "stop" or "shut down" terminates the assistant instantly',
    ],
    tags: ['Python', 'Ollama', 'Phi-3', 'Vosk'], modalTags: ['Python', 'Ollama', 'Phi-3', 'Vosk', 'pyttsx3'],
    img: 'https://images.unsplash.com/photo-1589254065878-42c9da997008?auto=format&fit=crop&w=900&q=80', impact: '↯ 100% offline LLM',
    links: [['GitHub ↗', 'https://github.com/Pratikm7073/Jarvis-AI']],
  },
  vendor: {
    num: '05', title: 'Vendor Risk & Governance Pipeline', type: 'Independent · ML',
    modalType: 'Independent · ML Analytics',
    blurb: 'Analysed a 167MB dataset to surface compliance risks & vendor fraud, with custom behavioural tripwires flagging high-risk accounts.',
    desc: 'A data pipeline that surfaces compliance risks and vendor fraud in e-commerce marketplace data, with behavioural tripwires that flag high-risk accounts the moment they deviate.',
    points: [
      'Processed a 167MB e-commerce dataset with Pandas for compliance & fraud signals',
      'Custom behavioural tripwires score and flag high-risk vendor accounts',
      'Governance-ready outputs for risk review and escalation',
    ],
    tags: ['Python', 'Pandas', 'ML'], modalTags: ['Python', 'Pandas', 'Jupyter', 'ML'],
    img: 'https://images.unsplash.com/photo-1460925895917-afdab827c52f?auto=format&fit=crop&w=900&q=80', impact: '↯ 167MB processed',
    links: [['GitHub ↗', 'https://github.com/Pratikm7073/ecommerce-vendor-risk-pipeline']],
  },
  ids: {
    num: '06', title: 'Secure Web App + ML IDS', type: 'Academic · 2026',
    modalType: 'Academic · 2026',
    blurb: 'Strict RBAC with MFA via Microsoft Authenticator, paired with an ML-powered intrusion detection system mapping live attack vectors.',
    desc: 'A hardened web application with strict role-based access control and multi-factor authentication, paired with a machine-learning IDS that maps live attack vectors.',
    points: [
      'Strict RBAC with MFA enforced through Microsoft Authenticator',
      'ML-powered intrusion detection classifying and mapping live attack vectors',
      '3-tier isolation between presentation, logic and data layers',
    ],
    tags: ['RBAC', 'MFA', 'ML-IDS'], modalTags: ['RBAC', 'MFA', 'ML-IDS', 'Python'],
    img: 'https://images.unsplash.com/photo-1555066931-4365d14bab8c?auto=format&fit=crop&w=900&q=80', impact: '↯ 3-tier isolation',
    links: [['GitHub ↗', 'https://github.com/Pratikm7073/secure-login-system-MFA']],
  },
};

const CAREER = [
  { yr: '2022', role: 'Lead WFM Analyst', sub: 'Concentrix Daksh',
    desc: <>Led business-process analysis across <strong>4 global sites</strong> (India, Vietnam, Egypt, Poland), driving a <strong>15%</strong> resource-utilisation lift. Coordinated <strong>20+ analysts</strong> across time zones and built Python &amp; Excel reporting dashboards for senior leadership.</> },
  { yr: '2019', role: 'Content Moderator & AI Policy Evaluator', sub: 'Concentrix · ByteDance (TikTok)',
    desc: <>Reviewed high-volume content across <strong>EU, MENA &amp; Bangladesh</strong> markets supporting internet governance. Sustained a <strong>95% accuracy</strong> rate via the TCS tool, documenting risk trends and refining detection with global teams.</> },
  { yr: 'NOW', role: 'MSc Cybersecurity', sub: 'United Kingdom · 2026',
    desc: <>Dissertation on <strong>cloud-native SOAR architecture</strong> benchmarking automated containment against manual triage, cutting Mean-Time-to-Contain from 380s to 41s. Focus on AI ethics, threat analysis &amp; secure programming.</> },
];

const METRICS = [
  { label: '// Quality Accuracy', t: 95, pct: true, det: 'Content moderation across EU, MENA & Bangladesh TikTok project.' },
  { label: '// MTTC Reduction', t: 89, pct: true, det: 'Mean Time-to-Contain: 380s → 41s via zero-touch SOAR.' },
  { label: '// Global Sites', t: 4, pct: false, det: 'India · Vietnam · Egypt · Poland 20+ analysts cross-timezone.' },
];

/* ── project summary modal (React + framer-motion springs) ── */
function ProjectModal() {
  const [key, setKey] = useState(null);
  const keyRef = useRef(null);
  const bodyRef = useRef(null);
  keyRef.current = key;

  useEffect(() => {
    window.projModalApi = {
      open: (k) => PROJECTS[k] && setKey(k),
      close: () => setKey(null),
      isOpen: () => keyRef.current != null,
      scrollBody: (dy) => { if (bodyRef.current) bodyRef.current.scrollTop += dy; },
    };
    const esc = (e) => { if (e.key === 'Escape') setKey(null); };
    addEventListener('keydown', esc);
    return () => removeEventListener('keydown', esc);
  }, []);

  useEffect(() => {
    document.body.style.overflow = key ? 'hidden' : '';
    return () => { document.body.style.overflow = ''; };
  }, [key]);

  const p = key ? PROJECTS[key] : null;
  return (
    <AnimatePresence>
      {p && (
        <div id="projModal" className="open" aria-hidden={!p}>
          <motion.div className="pm-backdrop" onClick={() => setKey(null)}
            initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: 0.3 }} />
          <motion.div className="pm-card"
            initial={{ opacity: 0, y: 40, scale: 0.94 }}
            animate={{ opacity: 1, y: 0, scale: 1, transition: { type: 'spring', stiffness: 210, damping: 22 } }}
            exit={{ opacity: 0, y: 24, scale: 0.96, transition: { duration: 0.22 } }}>
            <button className="pm-close" type="button" aria-label="Close" onClick={() => setKey(null)}>×</button>
            <div className="pm-media"><img src={p.img} alt={p.title} /><div className="pm-impact">{p.impact}</div></div>
            <motion.div className="pm-body" ref={bodyRef} variants={stagger} initial="hidden" animate="show">
              <motion.div className="pm-type" variants={riseSoft}>{p.modalType}</motion.div>
              <motion.h3 className="pm-title" variants={riseSoft}>{p.title}</motion.h3>
              <motion.p className="pm-desc" variants={riseSoft}>{p.desc}</motion.p>
              <motion.ul className="pm-points" variants={riseSoft}>
                {p.points.map((pt, i) => <li key={i}>{pt}</li>)}
              </motion.ul>
              <motion.div className="pm-tags" variants={riseSoft}>
                {p.modalTags.map((t) => <span key={t}>{t}</span>)}
              </motion.div>
              <motion.div className="pm-links" variants={riseSoft}>
                {p.links.map(([l, h], i) => (
                  <a key={h} href={h} target="_blank" rel="noopener noreferrer" className={i ? 'ghost' : ''}>{l}</a>
                ))}
              </motion.div>
            </motion.div>
          </motion.div>
        </div>
      )}
    </AnimatePresence>
  );
}

export default function App() {
  useEffect(() => { startEngine(); }, []);
  const open = (k) => window.projModalApi && window.projModalApi.open(k);

  return (
    <>
      <div className="grain"></div>
      <div className="vignette"></div>
      <div className="bg-layer"><canvas id="bg3d"></canvas></div>

      <button id="gestureBtn" type="button"><span className="gb-dot"></span>✋ Gesture Control</button>
      <div id="gestureHud">
        <div className="g-view">
          <video id="gestureCam" playsInline muted></video>
          <canvas id="gestureOverlay"></canvas>
        </div>
        <div className="g-status" id="gStatus">Starting camera…</div>
        <div className="g-priv">⛨ 100% in-browser · nothing uploaded</div>
      </div>
      <div id="handCursor"><div className="hc-ring"></div><div className="hc-core"></div><div className="hc-pulse"></div><div className="hc-arr u">▲</div><div className="hc-arr d">▼</div></div>

      <ProjectModal />

      <div id="preloader">
        <div className="pre-logo"><span>PM</span><span className="dot">.</span></div>
        <div className="pre-sub">Booting portfolio intelligence</div>
        <div className="pre-bar"><div className="fill"></div></div>
        <div className="pre-pct">0%</div>
      </div>

      <nav>
        <a href="mailto:morepratik77@gmail.com" className="nav-mail">morepratik77@gmail.com</a>
        <ul className="nav-links">
          <li><a href="#about">About</a></li>
          <li><a href="#work">Work</a></li>
          <li><a href="#contact">Contact</a></li>
        </ul>
      </nav>

      {/* HERO */}
      <section id="hero">
        <canvas id="hero-canvas"></canvas>
        <div className="hero-grid">
          <div className="hero-side left">
            <div className="small">Hello! I'm</div>
            <div className="big">PRATIK<br />MORE</div>
          </div>
          <div className="hero-side right">
            <div className="small">A Machine Learning</div>
            <div className="big"><span className="ghost">ML</span><br />ENGINEER</div>
          </div>
        </div>
        <div className="hero-meta">
          <span><span className="dot"></span>SecOps · Trust &amp; Safety</span>
          <span>52.40 N · 1.51 W // Coventry, UK</span>
        </div>
        <div className="ai-line"><span id="aiText"></span><span className="ai-caret"></span></div>
        <div className="scroll-hint"><div className="mouse"></div></div>
      </section>

      {/* ABOUT */}
      <section className="section-pad" id="about">
        <div className="about-split">
          <canvas id="about-canvas"></canvas>
          <motion.div className="about-copy" variants={rise} initial="hidden" whileInView="show" viewport={inView}>
            <img className="about-photo" src="download.jfif" alt="Pratik More in Coventry, UK" />
            <div className="eyebrow">About Me</div>
            <h2>Cybersecurity analyst building <em>secure systems</em> at scale.</h2>
            <p>I'm <strong>Pratik More</strong> a SecOps &amp; Trust-and-Safety specialist with <strong>4.5+ years</strong> protecting platforms, automating incident response, and hunting threats. Currently completing an <strong>MSc Cybersecurity</strong> in the UK.</p>
            <p>From moderating millions of data points at TikTok to engineering zero-touch ransomware kill-switches I build secure perimeters, automate the response, and protect the user experience.</p>
            <div className="about-stats">
              <div className="about-stat"><div className="k">Experience</div><div className="v">4.5+ Years</div></div>
              <div className="about-stat"><div className="k">Location</div><div className="v">Coventry, UK</div></div>
              <div className="about-stat"><div className="k">Status</div><div className="v" style={{ color: 'var(--cyan)' }}>● Available</div></div>
            </div>
          </motion.div>
        </div>
      </section>

      {/* WHAT I DO (SOC scene) */}
      <section className="whatido" id="work">
        <div id="socStatus">● SOC LIVE — ALL SYSTEMS NOMINAL</div>
        <canvas id="desk-canvas"></canvas>
        <div className="whatido-title">WHAT<br /><em>I DO</em></div>
        <motion.div className="do-cards" variants={stagger} initial="hidden" whileInView="show" viewport={inView}>
          <motion.div className="do-card" variants={rise}>
            <div className="role">Security Operations</div>
            <h3>Detection &amp; Response</h3>
            <p>Engineering zero-touch SOAR workflows with Microsoft Sentinel &amp; Azure Logic Apps. Every alert contained without a human in the loop.</p>
            <div className="tags"><span className="tag">Sentinel</span><span className="tag">SOAR</span><span className="tag">SIEM</span><span className="tag">Azure</span></div>
          </motion.div>
          <motion.div className="do-card" variants={rise}>
            <div className="role">Risk &amp; Governance</div>
            <h3>Threat Hunting</h3>
            <p>Real-time anomaly detection across cloud and on-prem. Behavioural tripwires and ML-driven intrusion detection that flag risk the moment it moves.</p>
            <div className="tags"><span className="tag">Python</span><span className="tag">ML-IDS</span><span className="tag">RBAC</span><span className="tag">MFA</span></div>
          </motion.div>
        </motion.div>
      </section>

      {/* CAREER */}
      <section className="section-pad">
        <motion.div variants={stagger} initial="hidden" whileInView="show" viewport={{ once: true, amount: 0.4 }}>
          <motion.div className="section-eyebrow" variants={riseSoft}>Career &amp; Experience</motion.div>
          <motion.h2 className="section-title" variants={riseSoft}>My career &amp; <em>experience</em></motion.h2>
        </motion.div>
        <div className="career-split">
          <div className="career-list">
            {CAREER.map((c) => (
              <motion.div key={c.yr} variants={rise} initial="hidden" whileInView="show" viewport={inView}>
                <div className="career-row">
                  <div className="yr">{c.yr}</div>
                  <div className="role">{c.role}<span className="sub">{c.sub}</span></div>
                  <div className="desc">{c.desc}</div>
                </div>
              </motion.div>
            ))}
          </div>
          <div id="careerViz" aria-hidden="true">
            <svg id="cvSvg" viewBox="0 0 400 640" preserveAspectRatio="xMidYMid meet">
              <defs>
                <linearGradient id="cvGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0" stopColor="#5ce1e6" /><stop offset=".55" stopColor="#8b6dff" /><stop offset="1" stopColor="#e0457b" />
                </linearGradient>
                <filter id="cvGlow" x="-60%" y="-60%" width="220%" height="220%">
                  <feGaussianBlur stdDeviation="4" result="b" />
                  <feMerge><feMergeNode in="b" /><feMergeNode in="SourceGraphic" /></feMerge>
                </filter>
              </defs>
              <path id="cvTrack" d="M200,34 C70,130 330,214 200,320 C70,426 330,510 200,606" fill="none" stroke="rgba(255,255,255,.09)" strokeWidth="2" />
              <path id="cvFlow" d="M200,34 C70,130 330,214 200,320 C70,426 330,510 200,606" fill="none" stroke="rgba(92,225,230,.22)" strokeWidth="2" strokeDasharray="3 14" strokeLinecap="round" />
              <path id="cvProg" d="M200,34 C70,130 330,214 200,320 C70,426 330,510 200,606" fill="none" stroke="url(#cvGrad)" strokeWidth="3.5" strokeLinecap="round" filter="url(#cvGlow)" />
              <circle id="cvComet" r="6.5" fill="#eafeff" filter="url(#cvGlow)" />
            </svg>
            <div className="cv-node" data-i="0"><i></i><div className="cv-card"><span className="cv-year">2022</span><span className="cv-role">Lead WFM Analyst</span><span className="cv-org">Concentrix Daksh</span></div></div>
            <div className="cv-node alt" data-i="1"><i></i><div className="cv-card"><span className="cv-year">2019</span><span className="cv-role">Trust &amp; Safety · AI Policy</span><span className="cv-org">TikTok · ByteDance</span></div></div>
            <div className="cv-node" data-i="2"><i></i><div className="cv-card"><span className="cv-year">NOW</span><span className="cv-role">MSc Cybersecurity</span><span className="cv-org">United Kingdom · 2026</span></div></div>
            <div className="cv-next">NEXT ▸ ML ENGINEER · <em>open to work</em></div>
          </div>
        </div>
      </section>

      {/* METRICS */}
      <section className="section-pad" style={{ paddingTop: 0 }}>
        <motion.div className="metrics" variants={stagger} initial="hidden" whileInView="show" viewport={inView}>
          {METRICS.map((m) => (
            <motion.div className="metric" key={m.label} variants={rise}>
              <div className="label">{m.label}</div>
              <div className="val"><span className="count" data-t={m.t}>0</span>{m.pct && <span className="pct">%</span>}</div>
              <div className="det">{m.det}</div>
            </motion.div>
          ))}
        </motion.div>
      </section>

      {/* WORK / PROJECTS */}
      <section className="section-pad">
        <motion.div variants={stagger} initial="hidden" whileInView="show" viewport={{ once: true, amount: 0.4 }}>
          <motion.div className="section-eyebrow" variants={riseSoft}>Selected Projects</motion.div>
          <motion.h2 className="section-title" variants={riseSoft}>My <em>Work</em></motion.h2>
        </motion.div>
        <div className="work-list">
          {Object.entries(PROJECTS).map(([k, p]) => (
            <motion.div key={k} variants={rise} initial="hidden" whileInView="show" viewport={{ once: true, amount: 0.2 }}>
              <div className="work-row" data-proj={k}
                onClick={(e) => { if (!e.target.closest('a')) open(k); }}>
                <div className="wnum">{p.num}</div>
                <div className="winfo">
                  <h3>{p.title}</h3>
                  <div className="wtype">{p.type}</div>
                  <p>{p.blurb}</p>
                  <div className="wtags">{p.tags.map((t) => <span className="wtag" key={t}>{t}</span>)}</div>
                  <div className="wlinks">
                    {p.links.map(([l, h]) => (
                      <a className="wlink" key={h} href={h} target="_blank" rel="noopener noreferrer">{l}</a>
                    ))}
                  </div>
                </div>
                <div className="wimg"><div className="wimpact">{p.impact}</div><img src={p.img} alt={p.title} loading="lazy" /></div>
              </div>
            </motion.div>
          ))}
        </div>
      </section>

      {/* TECHSTACK */}
      <section className="techstack">
        <canvas id="tech-canvas"></canvas>
        <div className="tech-title">MY TECHSTACK</div>
        <div className="tech-hint">Drag to explore · Scroll to continue</div>
      </section>

      {/* CONTACT */}
      <section id="contact">
        <motion.div variants={stagger} initial="hidden" whileInView="show" viewport={inView}>
          <motion.div className="contact-eyebrow" variants={riseSoft}>{'// Get in touch'}</motion.div>
          <motion.h2 variants={rise}>Let's build something <em>secure.</em></motion.h2>
          <motion.div className="contact-grid" variants={riseSoft}>
            <div className="contact-links">
              <div className="clabel">Reach me</div>
              <a href="mailto:morepratik77@gmail.com">Email <span className="arr">↗</span></a>
              <a href="https://github.com/Pratikm7073" target="_blank" rel="noopener noreferrer">GitHub <span className="arr">↗</span></a>
              <a href="https://linkedin.com/in/pratik-more-969749249" target="_blank" rel="noopener noreferrer">LinkedIn <span className="arr">↗</span></a>
            </div>
            <div className="contact-right">
              <div className="credit">Designed &amp; developed by<br /><strong>Pratik More</strong></div>
              <div className="yr">© 2026 · Coventry, UK</div>
            </div>
          </motion.div>
        </motion.div>
      </section>

      <footer>
        <span>© 2026 Pratik More</span>
        <span><span className="l">PM·SECOPS</span> // All rights reserved</span>
        <span>Coventry, UK</span>
      </footer>
    </>
  );
}
