// Title-less abstract placeholder covers, only for projects that have no cover yet (real screenshots are never overwritten). Token colours only; geometry differs per project and is seeded from the slug.
import sharp from 'sharp';
import { existsSync, readdirSync } from 'node:fs';

// One cover per project file, so new projects get a cover without editing this script.
const SLUGS = readdirSync('src/content/projects').filter((f) => f.endsWith('.md')).map((f) => f.slice(0, -3)).sort();
const W = 1600, H = 1000;
const SURF = '#161617', LINE = '#2A2A2C', DIM = '#8A867E', ACC = '#FF4A1C';

const rng = (str) => {
  let h = 2166136261;
  for (const c of str) h = Math.imul(h ^ c.charCodeAt(0), 16777619);
  return () => ((h = Math.imul(h ^ (h >>> 15), 2246822519) + 0x6d2b79f5), ((h >>> 0) % 10000) / 10000);
};

const compose = {
  // concentric arcs around an off-centre origin
  0(r) {
    const cx = 500 + r() * 600, cy = 300 + r() * 400, n = 9 + Math.floor(r() * 5), step = 70 + r() * 30;
    let s = '';
    for (let i = 1; i <= n; i++) s += `<circle cx="${cx}" cy="${cy}" r="${i * step}" fill="none" stroke="${i % 4 === 0 ? DIM : LINE}" stroke-width="${i % 4 === 0 ? 2 : 1.5}"/>`;
    return { s, mx: cx, my: cy };
  },
  // skewed grid with a diagonal
  1(r) {
    const gap = 80 + Math.floor(r() * 3) * 20, sk = 0.2 + r() * 0.3;
    let s = '';
    for (let x = -400; x < W + 400; x += gap) s += `<line x1="${x}" y1="0" x2="${x + H * sk}" y2="${H}" stroke="${LINE}" stroke-width="1.5"/>`;
    for (let y = gap; y < H; y += gap) s += `<line x1="0" y1="${y}" x2="${W}" y2="${y}" stroke="${LINE}" stroke-width="1.5"/>`;
    const x1 = 200 + r() * 300, y1 = 700 - r() * 200;
    s += `<line x1="${x1}" y1="${y1}" x2="${x1 + 800}" y2="${y1 - 500}" stroke="${DIM}" stroke-width="2"/>`;
    return { s, mx: x1 + 800, my: y1 - 500 };
  },
  // stacked bars of varying length
  2(r) {
    let s = '', y = 110, mx = 0, my = 0;
    while (y < H - 100) {
      const h = 14 + r() * 34, x = 90 + r() * 260, w = 300 + r() * 1000;
      s += `<rect x="${x}" y="${y}" width="${w}" height="${h}" fill="${r() > 0.75 ? DIM : LINE}"/>`;
      if (r() > 0.9 || (!mx && y > 600)) { mx = x + w + 30; my = y + h / 2; }
      y += h + 22 + r() * 40;
    }
    return { s, mx: mx || 1200, my: my || 600 };
  },
};

for (let i = 0; i < SLUGS.length; i++) {
  const slug = SLUGS[i];
  if (existsSync(`src/content/projects/${slug}.webp`) || existsSync(`src/content/projects/${slug}-hero.webp`)) continue;
  const r = rng(slug);
  const { s, mx, my } = compose[i % 3](r);
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}"><rect width="100%" height="100%" fill="${SURF}"/>${s}
<rect x="48" y="48" width="${W - 96}" height="${H - 96}" fill="none" stroke="${LINE}" stroke-width="1.5"/>
<circle cx="${Math.min(W - 100, Math.max(100, mx))}" cy="${Math.min(H - 100, Math.max(100, my))}" r="14" fill="${ACC}"/></svg>`;
  await sharp(Buffer.from(svg)).webp({ quality: 84 }).toFile(`src/content/projects/${slug}.webp`);
}
console.log('covers done');
