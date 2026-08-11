/* ════════════════════════════════════════════════
   Curated dark-industrial photography.

   Every frame below was pulled down and inspected before
   being chosen: mean luminance measured, subject checked.
   Anything bright, corporate-stock or cliche (padlocks,
   matrix rain, humanoid robots) was rejected.

   Served straight off the Unsplash CDN, which negotiates
   WebP/AVIF via auto=format, so nothing heavy lands in
   the repo and the grading is done in CSS.
   ════════════════════════════════════════════════ */

const U = (id, w, q = 72) =>
  `https://images.unsplash.com/photo-${id}?auto=format&fit=crop&w=${w}&q=${q}`;

/* hero: three cinematic plates, escalating in scale
   rack room -> data hall -> the planet at night */
export const HERO_PLATES = [
  { id: '1558494949-ef010cbdcc31', alt: 'Server racks threaded with amber patch cabling' },
  { id: '1573164713988-8665fc963095', alt: 'Data hall aisle under blue light' },
  { id: '1451187580459-43490279c0fa', alt: 'Earth at night from orbit, city lights across the dark side' },
].map((p) => ({ ...p, src: U(p.id, 2000, 76), low: U(p.id, 32, 30) }));

/* sector cards */
export const SECTOR_IMG = {
  detect: U('1520869562399-e772f042f422', 1200),
  ml: U('1550751827-4bd374c3f58b', 1200),
  intel: U('1526666923127-b2970f64b422', 1200),
  govern: U('1547394765-185e1e68f34e', 1200),
  respond: U('1518770660439-4636190af475', 1200),
};
