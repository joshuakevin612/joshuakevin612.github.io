import sharp from 'sharp';
import fs from 'node:fs/promises';
import path from 'node:path';

const N = 120, W = 1280, H = 720;
const out = path.resolve('public/film/desktop');
await fs.mkdir(out, { recursive: true });
const hex = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
const L = hex('#F2EEE6'), D = hex('#0B0B0C');
const mix = (t) => '#' + L.map((v, i) => Math.round(v + (D[i] - v) * t).toString(16).padStart(2, '0')).join('');
const ease = (t) => t * t * (3 - 2 * t);

for (let f = 1; f <= N; f++) {
  const p = (f - 1) / (N - 1);
  const bg = f <= 45 ? '#F2EEE6' : f <= 60 ? mix((f - 45) / 15) : '#0B0B0C';
  const size = 140 + ease(Math.max(0, (p - 0.55) / 0.45)) * 1900 + Math.sin(p * Math.PI) * 60;
  const rot = ease(p) * 360 * 0.5 - 20 + Math.sin(p * 6) * 8;
  const cx = W / 2 + Math.sin(p * Math.PI * 2) * 160 * (1 - p), cy = H / 2 + Math.cos(p * Math.PI * 2) * 40 * (1 - p);
  const r = size * 0.22;
  const showJK = p > 0.7;
  const fs = size * 0.38;
  const jkOpacity = Math.min(1, (p - 0.7) / 0.2);
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}"><rect width="100%" height="100%" fill="${bg}"/>
<g transform="translate(${cx} ${cy}) rotate(${p > 0.85 ? 0 : rot})"><rect x="${-size / 2}" y="${-size / 2}" width="${size}" height="${size}" rx="${r}" fill="#FF4A1C"/>
${showJK ? `<text x="0" y="${fs * 0.35}" text-anchor="middle" font-family="Arial, sans-serif" font-weight="700" font-size="${fs}" fill="#0B0B0C" opacity="${jkOpacity}">JK</text>` : ''}</g>
<text x="24" y="${H - 24}" font-family="monospace" font-size="16" fill="#8A867E">${String(f).padStart(4, '0')}</text></svg>`;
  await sharp(Buffer.from(svg)).webp({ quality: 80 }).toFile(path.join(out, `f_${String(f).padStart(4, '0')}.webp`));
}
await fs.mkdir('src/data', { recursive: true });
await fs.writeFile('src/data/film.json', JSON.stringify({ count: N, desktop: { width: W, height: H }, mobile: null }, null, 2) + '\n');
console.log(`wrote ${N} frames + src/data/film.json`);
