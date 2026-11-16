// Builds the mobile frame set + src/data/film.json from public/film/desktop/f_*.webp
import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import sharp from 'sharp';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const desktopDir = path.join(root, 'public', 'film', 'desktop');
const mobileDir = path.join(root, 'public', 'film', 'mobile');
const jsonPath = path.join(root, 'src', 'data', 'film.json');
const MOBILE_WIDTH = 960;
const MOBILE_QUALITY = 78;

const fail = (msg) => { console.error(`frames: ${msg}`); process.exit(1); };
const mb = (n) => (n / 1048576).toFixed(1) + ' MB';

const files = (await fs.readdir(desktopDir).catch(() => []))
  .filter((f) => /^f_\d{4}\.webp$/.test(f))
  .sort();
if (!files.length) fail(`no f_####.webp files in ${desktopDir}`);
files.forEach((f, i) => {
  const want = `f_${String(i + 1).padStart(4, '0')}.webp`;
  if (f !== want) fail(`numbering gap: expected ${want}, found ${f}`);
});

await fs.mkdir(mobileDir, { recursive: true });
for (const f of await fs.readdir(mobileDir)) {
  if (/^f_\d{4}\.webp$/.test(f)) await fs.rm(path.join(mobileDir, f));
}
await fs.mkdir(path.dirname(jsonPath), { recursive: true });

const desktop = await sharp(path.join(desktopDir, files[0])).metadata();
let mobile = null;
let desktopBytes = 0;
let mobileBytes = 0;

const worker = async (queue) => {
  while (queue.length) {
    const f = queue.shift();
    const src = path.join(desktopDir, f);
    const dst = path.join(mobileDir, f);
    const info = await sharp(src)
      .resize({ width: MOBILE_WIDTH, withoutEnlargement: true })
      .webp({ quality: MOBILE_QUALITY })
      .toFile(dst);
    if (f === files[0]) mobile = { width: info.width, height: info.height };
    const srcSize = (await fs.stat(src)).size; // await first: `+=` across an await loses updates
    desktopBytes += srcSize;
    mobileBytes += info.size;
  }
};
const queue = [...files];
await Promise.all(Array.from({ length: 8 }, () => worker(queue)));

const film = {
  count: files.length,
  desktop: { width: desktop.width, height: desktop.height },
  mobile,
};
await fs.writeFile(jsonPath, JSON.stringify(film) + '\n');
console.log(
  `frames: ${files.length} frames, desktop ${desktop.width}x${desktop.height} ${mb(desktopBytes)}, ` +
    `mobile ${mobile.width}x${mobile.height} ${mb(mobileBytes)} -> ${path.relative(root, jsonPath)}`,
);
