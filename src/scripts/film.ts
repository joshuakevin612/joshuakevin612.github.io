import gsap from 'gsap';
import { ScrollTrigger } from 'gsap/ScrollTrigger';
import { SplitText } from 'gsap/SplitText';
import type Lenis from 'lenis';
import filmMeta from '../data/film.json';
import { createFilmGL, type FilmGL, type FrameSource } from './filmgl';

type Meta = { count: number; desktop: { width: number; height: number }; mobile: { width: number; height: number } | null };
const film = filmMeta as Meta;
export const filmState = { progress: 0 };

// ------------------------------------------------------------------ frame store
// Pipeline: network -> Blob (kept for the session) -> ImageBitmap (sliding window, closed on eviction) -> GPU texture (pool).
// After the preload the network is never touched during playback. Coarse frames (every COARSE_STRIDE) also keep a small
// decoded "proxy" bitmap permanently, so a fast jump always has something within half a stride to show.
type Tier = { decAhead: number; decBehind: number; decConc: number; texPool: number; texAhead: number; texBehind: number; proxyW: number };
const TIER_FULL: Tier = { decAhead: 24, decBehind: 12, decConc: 2, texPool: 24, texAhead: 14, texBehind: 6, proxyW: 640 };
const TIER_LITE: Tier = { decAhead: 12, decBehind: 5, decConc: 1, texPool: 12, texAhead: 7, texBehind: 3, proxyW: 320 };
const lowMem = () => matchMedia('(hover: none), (pointer: coarse)').matches || ((navigator as any).deviceMemory ?? 8) <= 4;

const N = film.count;
const pad = (n: number) => String(n).padStart(4, '0');
const BASE = import.meta.env.BASE_URL.replace(/\/$/, "");
const url = (key: string, i: number) => `${BASE}/film/${key}/f_${pad(i + 1)}.webp`;
const dprCap = () => Math.min(devicePixelRatio || 1, 2);
const pickKey = () => (film.mobile && innerWidth * dprCap() <= film.mobile.width ? 'mobile' : 'desktop');
const FETCH_CONC = 6;
const COARSE_STRIDE = 8;
const isCoarse = (i: number) => i % COARSE_STRIDE === 0 || i === N - 1;

// ---- playhead dynamics
/** Seconds for the drawn position to cover 95% of a step in the scroll target (critically damped spring). The one knob for "heaviness". */
const PLAYHEAD_T95 = 0.4;
const MAX_SPEED = 120;      // frames/s, hard ceiling on playhead speed
const MIN_SPEED = 18;       // frames/s floor when the decoded window is empty ahead
const RUNWAY_S = 0.2;       // playhead may not move faster than (decoded frames ahead) / RUNWAY_S
const MAX_GAP = 5;          // widest hole between two GPU-ready frames that is still blended as "exact"
const MAX_DT = 0.05;        // s, clamp after tab-switch / GC stalls
const FADE_TAU = 0.045;     // s, proxy -> exact refinement cross-fade
const START_AHEAD = 6, START_BEHIND = 2;
const OMEGA = 4.7439 / PLAYHEAD_T95; // critically damped: 95% at omega*t = 4.7439

type Store = {
  key: string; w: number; h: number; tier: Tier; only: number;
  blob: (Blob | null)[]; bs: Uint8Array;     // bs: 0 idle, 1 fetching, 2 have, 3 failed
  bmp: (FrameSource | null)[]; ds: Uint8Array; // ds: 0 none, 1 decoding, 2 ready, 3 failed
  proxy: (FrameSource | null)[]; ps: Uint8Array;
  prio: number[]; cur: number; dir: number; inflight: number; decoding: number; idleBlobs: number; alive: number;
  active: boolean; ac: AbortController; onProgress: (() => void) | null; onEvict: ((i: number) => void) | null;
};

const closeSrc = (x: FrameSource | null) => { if (x && 'close' in x) x.close(); };

function createStore(key: string, tier: Tier, only: number): Store {
  const dim = key === 'mobile' && film.mobile ? film.mobile : film.desktop;
  return {
    key, w: dim.width, h: dim.height, tier, only,
    blob: new Array(N).fill(null), bs: new Uint8Array(N), bmp: new Array(N).fill(null), ds: new Uint8Array(N),
    proxy: new Array(N).fill(null), ps: new Uint8Array(N),
    prio: [], cur: 0, dir: 1, inflight: 0, decoding: 0, idleBlobs: N, alive: 0,
    active: true, ac: new AbortController(), onProgress: null, onEvict: null,
  };
}

function destroyStore(s: Store) {
  s.active = false; s.onProgress = null; s.onEvict = null;
  s.ac.abort();
  for (let i = 0; i < N; i++) { closeSrc(s.bmp[i]); closeSrc(s.proxy[i]); }
  s.blob.fill(null); s.bmp.fill(null); s.proxy.fill(null); s.alive = 0;
}

async function decodeBlob(b: Blob, w: number, h: number, resize: boolean): Promise<FrameSource> {
  if (typeof createImageBitmap === 'function') {
    const base = { premultiplyAlpha: 'none', colorSpaceConversion: 'none' } as const;
    return createImageBitmap(b, resize ? { ...base, resizeWidth: w, resizeHeight: h, resizeQuality: 'medium' } : base);
  }
  const u = URL.createObjectURL(b);
  const im = new Image(); im.decoding = 'async'; im.src = u;
  try { await im.decode(); } finally { URL.revokeObjectURL(u); }
  return im;
}

// is frame i inside the decoded window (ahead = along the scroll direction)
const inWindow = (s: Store, i: number, slack: number) => {
  if (s.only >= 0) return true;
  const a = (i - Math.round(s.cur)) * s.dir;
  return a >= 0 ? a <= s.tier.decAhead + slack : -a <= s.tier.decBehind + slack;
};

function fetchPick(s: Store): number {
  for (let k = 0; k < s.prio.length; k++) if (s.bs[s.prio[k]] === 0) return s.prio[k];
  if (s.only >= 0 || s.idleBlobs <= 0) return -1;
  const c = Math.round(s.cur);
  let best = -1, bc = Infinity;
  for (let i = 0; i < N; i++) {
    if (s.bs[i] !== 0) continue;
    const d = i - c, cost = d * s.dir >= 0 ? Math.abs(d) : Math.abs(d) * 3; // ahead of the playhead first
    if (cost < bc) { bc = cost; best = i; }
  }
  return best;
}

function pumpFetch(s: Store) {
  while (s.active && s.inflight < FETCH_CONC) {
    const i = fetchPick(s);
    if (i < 0) break;
    s.bs[i] = 1; s.idleBlobs--; s.inflight++;
    fetchOne(s, i);
  }
}

async function fetchOne(s: Store, i: number) {
  try {
    const r = await fetch(url(s.key, i), { signal: s.ac.signal });
    if (!r.ok) throw new Error('frame ' + i);
    const b = await r.blob();
    if (!s.active) return;
    s.blob[i] = b; s.bs[i] = 2;
    if (s.only < 0 && isCoarse(i)) decodeProxy(s, i, b);
  } catch { if (s.active) s.bs[i] = 3; }
  finally {
    s.inflight--;
    if (s.active) { s.onProgress?.(); pumpFetch(s); pumpDecode(s); }
  }
}

function decodeProxy(s: Store, i: number, b: Blob) {
  s.ps[i] = 1;
  const pw = s.tier.proxyW, ph = Math.round(pw * s.h / s.w);
  decodeBlob(b, pw, ph, true).then(
    (src) => { if (!s.active) { closeSrc(src); return; } s.proxy[i] = src; s.ps[i] = 2; },
    () => { s.ps[i] = 3; },
  ).finally(() => { if (s.active) s.onProgress?.(); });
}

function decodePick(s: Store): number {
  const ok = (i: number) => i >= 0 && i < N && s.bs[i] === 2 && s.ds[i] === 0;
  if (s.only >= 0) return ok(s.only) ? s.only : -1;
  const c = Math.round(s.cur), A = s.tier.decAhead, B = s.tier.decBehind;
  for (let d = 0; d <= Math.max(A, B); d++) {
    if (d <= A && ok(c + s.dir * d)) return c + s.dir * d;
    if (d > 0 && d <= B && ok(c - s.dir * d)) return c - s.dir * d;
  }
  return -1;
}

function pumpDecode(s: Store) {
  while (s.active && s.decoding < s.tier.decConc) {
    const i = decodePick(s);
    if (i < 0) break;
    s.ds[i] = 1; s.decoding++;
    decodeBlob(s.blob[i]!, 0, 0, false).then(
      (src) => {
        if (!s.active || !inWindow(s, i, 2)) { closeSrc(src); s.ds[i] = 0; return; }
        s.bmp[i] = src; s.ds[i] = 2; s.alive++;
      },
      () => { s.ds[i] = 3; },
    ).finally(() => { s.decoding--; if (s.active) { s.onProgress?.(); pumpDecode(s); } });
  }
}

function evict(s: Store) {
  if (s.only >= 0) return;
  for (let i = 0; i < N; i++) {
    if (s.ds[i] !== 2 || inWindow(s, i, 4)) continue;
    s.onEvict?.(i);
    closeSrc(s.bmp[i]); s.bmp[i] = null; s.ds[i] = 0; s.alive--;
  }
}

type Br = { a: number; b: number; mix: number; ok: boolean };

// ------------------------------------------------------------------ theme blend
// Mirrors the token sets in global.css (light = :root, dark = [data-theme=dark]).
const hex = (h: string) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
const LIGHT = { '--bg': hex('#F2EEE6'), '--surface': hex('#E7E1D6'), '--text': hex('#14130F'), '--text-2': hex('#6F6A60'), '--line': hex('#D5CEC1') };
const DARK = { '--bg': hex('#0B0B0C'), '--surface': hex('#161617'), '--text': hex('#ECE8DF'), '--text-2': hex('#8A867E'), '--line': hex('#2A2A2C') };
const THEME_A = 0.075, THEME_B = 0.115;
const clamp01 = (x: number) => Math.max(0, Math.min(1, x));
const smooth = (x: number) => { x = clamp01(x); return x * x * (3 - 2 * x); };
let lastThemeT = -1;

export function setThemeProgress(p: number, html = document.documentElement) {
  const t = smooth((p - THEME_A) / (THEME_B - THEME_A));
  const theme = p >= (THEME_A + THEME_B) / 2 ? 'dark' : 'light';
  if (html.dataset.theme !== theme) html.dataset.theme = theme;
  const q = Math.round(t * 1000) / 1000;
  if (q === lastThemeT) return;
  lastThemeT = q;
  if (q <= 0 || q >= 1) { clearTheme(html, true); return; } // fully light/dark: let the stylesheet tokens apply
  (Object.keys(LIGHT) as Array<keyof typeof LIGHT>).forEach((k) => {
    const c = LIGHT[k].map((v, i) => Math.round(v + (DARK[k][i] - v) * q));
    html.style.setProperty(k, `rgb(${c[0]} ${c[1]} ${c[2]})`);
  });
}
export function clearTheme(html = document.documentElement, keepMemo = false) {
  Object.keys(LIGHT).forEach((k) => html.style.removeProperty(k));
  if (!keepMemo) lastThemeT = -1;
}
/** Hero scroll progress from the DOM only (used before the film is ready, e.g. load at any offset). */
export function heroProgress(root: HTMLElement) {
  const r = root.getBoundingClientRect();
  return toFilm(-r.top / Math.max(1, r.height - innerHeight));
}
/** The film finishes at FILM_END of the pinned scroll; the rest is a dwell on the last frame, so the damped playhead
 *  lands on the final shot before the pin releases (otherwise a fast scroll carries the hero away mid push-in). */
const FILM_END = 0.86;
/** The preloader waits for every frame. It gives up only if loading stalls (no frame arrives for PRELOAD_STALL ms) or
 *  after PRELOAD_CAP ms in total; the playback loop then streams the rest and falls back to proxies. */
const PRELOAD_STALL = 10000, PRELOAD_CAP = 90000; // ms
const toFilm = (scroll: number) => clamp01(scroll / FILM_END);

// ------------------------------------------------------------------ captions
// [start, end] in film progress; beat 1 = workspace, 2 = to the keyboard, (launch has none), 3 = spin, 4 = liquid, 5 = push-in
const BEATS: Array<[number, number]> = [[0, 0.25], [0.25, 0.42], [0.52, 0.69], [0.69, 0.83], [0.83, 1]];
const FADE = 0.03;
const bump = (p: number, a: number, b: number, fa: number, fb: number) => smooth((p - a) / fa) * (1 - smooth((p - b) / fb));

interface Opts { lenis: Lenis | null; reduced: boolean; add: (fn: () => void) => void }

// ------------------------------------------------------------------ dev instrumentation (stripped from production builds)
const RING = 8192;
const makeDev = () => ({
  iv: new Float32Array(RING), n: 0, max: 0, over20: 0, notReady: 0, maxStep: 0,
  reset() { this.n = 0; this.max = 0; this.over20 = 0; this.notReady = 0; this.maxStep = 0; },
  p95() {
    const k = Math.min(this.n, RING);
    if (!k) return 0;
    const a = Array.from(this.iv.subarray(0, k)).sort((x, y) => x - y);
    return a[Math.min(k - 1, Math.floor(k * 0.95))];
  },
});

export async function initFilm({ lenis, reduced }: Opts): Promise<(() => void) | null> {
  const root = document.querySelector<HTMLElement>('[data-film]');
  const canvas = root?.querySelector<HTMLCanvasElement>('[data-film-canvas]');
  if (!root || !canvas) return null;
  const html = document.documentElement;
  let dead = false;
  const cleanups: Array<() => void> = [];
  const pre = document.querySelector<HTMLElement>('[data-preloader]');
  const showPre = !!pre && html.hasAttribute('data-pre') && !reduced;
  const countEl = document.querySelector<HTMLElement>('[data-pre-count]');
  const mark = document.querySelector<HTMLElement>('[data-pre-mark]');
  const logo = document.querySelector<HTMLElement>('[data-logo]');
  const title = root.querySelector<HTMLElement>('[data-hero-title]');
  const role = root.querySelector<HTMLElement>('[data-hero-role]');
  const beats = Array.from(root.querySelectorAll<HTMLElement>('[data-beat]'));
  const touch = matchMedia('(hover: none), (pointer: coarse)').matches;
  const tier = lowMem() ? TIER_LITE : TIER_FULL;

  // ---- progress source (scroll) + initial position
  let target = reduced ? 1 : heroProgress(root);
  let pos = target * (N - 1);       // drawn playhead, in frames
  let vel = 0;                      // frames/s
  let snap = true; // until the intro finishes, follow the scroll exactly (load at any offset / anchor jump)
  const st = reduced ? null : ScrollTrigger.create({
    trigger: root, start: 'top top', end: 'bottom bottom',
    onUpdate: (s) => { target = toFilm(s.progress); },
    onRefresh: (s) => { target = toFilm(s.progress); if (snap) pos = target * (N - 1); },
  });
  if (st) { target = toFilm(st.progress); pos = target * (N - 1); cleanups.push(() => st.kill()); }

  // ---- end gate: scrolling may not carry the page out of the hero until the playhead has landed on the last frame.
  // Wheel/touch input past the end is swallowed while the film is still playing; a wheel delta that already overshot
  // is pulled back to the end. Only applies right after user input, so nav-link jumps are never held.
  const finished = () => pos >= N - 1.01;
  let lastInput = -1e9;
  if (lenis && st) {
    const prevVS = lenis.options.virtualScroll;
    lenis.options.virtualScroll = (d) => {
      lastInput = performance.now();
      const y = lenis.animatedScroll;
      if (d.deltaY > 0 && !finished() && y >= st.end - 2 && y <= st.end + 2) {
        if (d.event.cancelable) d.event.preventDefault();
        return false;
      }
      return typeof prevVS === 'function' ? prevVS(d) : true;
    };
    cleanups.push(() => { lenis.options.virtualScroll = prevVS; });
  }
  const holdAtEnd = () => {
    if (!lenis || !st || finished() || performance.now() - lastInput > 600) return;
    const y = lenis.animatedScroll, end = st.end;
    if (y > end + innerHeight * 0.5) return; // already well past (a jump), leave it
    if (y > end + 0.5) lenis.scrollTo(end, { immediate: true, force: true });
    else if (lenis.targetScroll > end) lenis.scrollTo(end, { force: true });
  };

  // ---- load: every frame's blob (start window + coarse set first), coarse proxies and the start window decode.
  // The preloader counts all of it, so 100 means the whole film is in memory before the desk is shown.
  const s = createStore(pickKey(), tier, reduced ? N - 1 : -1);
  cleanups.push(() => destroyStore(s));
  const abortEarly = () => { dead = true; destroyStore(s); s.onProgress?.(); };
  document.addEventListener('astro:before-swap', abortEarly, { once: true });
  cleanups.push(() => document.removeEventListener('astro:before-swap', abortEarly));

  s.cur = pos;
  const startC = Math.max(0, Math.min(N - 1, Math.round(pos)));
  const startSet: number[] = [];
  const coarse: number[] = [];
  if (reduced) { startSet.push(N - 1); }
  else {
    for (let i = startC - START_BEHIND; i <= startC + START_AHEAD; i++) if (i >= 0 && i < N) startSet.push(i);
    for (let i = 0; i < N; i++) if (isCoarse(i)) coarse.push(i);
    coarse.sort((x, y) => Math.abs(x - s.cur) - Math.abs(y - s.cur));
    startSet.sort((x, y) => Math.abs(x - s.cur) - Math.abs(y - s.cur));
  }
  s.prio = startSet.concat(coarse.filter((i) => !startSet.includes(i)));
  const counter = { v: 0 };
  await new Promise<void>((res) => {
    const all = !reduced; // reduced motion loads only the poster frame
    let lastDone = -1;
    const check = () => {
      let done = 0;
      const total = startSet.length + coarse.length + (all ? N : 0);
      // a frame whose fetch failed (bs 3) counts as done: one 404 must not hold the preloader forever
      for (const i of startSet) if (s.ds[i] >= 2 || s.bs[i] === 3) done++;
      for (const i of coarse) if (s.bs[i] === 3 || (s.bs[i] >= 2 && s.ps[i] >= 2)) done++;
      if (all) for (let i = 0; i < N; i++) if (s.bs[i] >= 2) done++;
      if (done !== lastDone) { lastDone = done; clearTimeout(stall); stall = setTimeout(giveUp, PRELOAD_STALL); }
      // the shown count never claims 100 before everything is in
      if (showPre && countEl) gsap.to(counter, { v: done === total ? 100 : Math.min(99, (done / Math.max(1, total)) * 100), duration: 0.6, ease: 'power2.out', overwrite: true, onUpdate: () => { countEl.textContent = String(Math.floor(counter.v)); } });
      if (done === total || dead || timedOut) { s.onProgress = null; clearTimeout(stall); clearTimeout(cap); res(); }
    };
    let timedOut = false;
    // stalled or very slow network: stop waiting and let the playback loop stream the rest (it falls back to proxies)
    const giveUp = () => { timedOut = true; check(); };
    let stall = setTimeout(giveUp, PRELOAD_STALL);
    const cap = setTimeout(giveUp, PRELOAD_CAP);
    s.onProgress = check;
    pumpFetch(s);
    check();
  });
  if (dead) { cleanups.forEach((c) => c()); return null; }

  // ---- renderer (WebGL, with 2D fallback)
  const ratio = s.w / s.h;
  const gl: FilmGL | null = reduced ? null : createFilmGL(canvas, { lite: touch, imgAspect: ratio, pool: tier.texPool });
  const c2d = gl ? null : canvas.getContext('2d', { alpha: false });
  let dirty = true;
  const size = () => {
    const dpr = dprCap();
    const w = canvas.clientWidth, h = canvas.clientHeight;
    if (gl) gl.resize(w, h, dpr);
    else { canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr); }
    dirty = true;
  };
  size();
  if (gl) {
    // under the preloader: proxies + the start window go to the GPU now so the first frames never upload mid-scroll
    for (const i of coarse) if (s.ps[i] === 2) gl.warmProxy(i, s.proxy[i]!);
    for (const i of startSet) if (s.ds[i] === 2) gl.warm(i, s.bmp[i]!, startC, 1, -1, -1);
    s.onEvict = (i) => gl.drop(i);
  }
  const put2d = (src: FrameSource) => {
    const cw = canvas.width, ch = canvas.height;
    const iw = (src as any).width as number, ih = (src as any).height as number;
    const k = Math.max(cw / iw, ch / ih);
    c2d!.drawImage(src, (cw - iw * k) / 2, (ch - ih * k) / 2, iw * k, ih * k);
  };
  const draw2d = (a: FrameSource, b: FrameSource, mix: number) => {
    if (!c2d) return;
    c2d.imageSmoothingEnabled = true; c2d.imageSmoothingQuality = 'high';
    c2d.globalAlpha = 1; put2d(a);
    if (b !== a && mix > 0.002) { c2d.globalAlpha = mix; put2d(b); c2d.globalAlpha = 1; }
  };
  const onResize = () => { size(); };
  window.addEventListener('resize', onResize);
  cleanups.push(() => window.removeEventListener('resize', onResize));
  const lost = (e: Event) => e.preventDefault();
  const restored = () => { dirty = true; };
  canvas.addEventListener('webglcontextlost', lost);
  canvas.addEventListener('webglcontextrestored', restored);
  cleanups.push(() => { canvas.removeEventListener('webglcontextlost', lost); canvas.removeEventListener('webglcontextrestored', restored); });
  if (gl) cleanups.push(() => gl.dispose());

  if (reduced) {
    html.dataset.theme = 'dark';
    const f = s.bmp[N - 1];
    if (f) draw2d(f, f, 0);
    return () => { dead = true; cleanups.forEach((c) => c()); };
  }

  // ---- hero text
  let titleSplit: SplitText | null = null;
  if (title) {
    titleSplit = SplitText.create(title, { type: 'chars', charsClass: 'char' });
    gsap.set(titleSplit.chars, { yPercent: 120, opacity: 0 });
    title.style.overflow = 'hidden';
  }
  if (role) gsap.set(role, { opacity: 0, y: 20 });

  // ---- pointer: parallax target + fluid splats
  const par = { x: 0, y: 0 }, parT = { x: 0, y: 0 };
  let px = -1, py = -1, visible = true;
  const onMove = (e: PointerEvent) => {
    const W = innerWidth, H = innerHeight;
    parT.x = (e.clientX / W) * 2 - 1; parT.y = (e.clientY / H) * 2 - 1;
    if (!visible) { px = -1; return; }
    if (px >= 0 && gl) gl.splat(e.clientX / W, 1 - e.clientY / H, ((e.clientX - px) / W) * 10, -((e.clientY - py) / H) * 10);
    px = e.clientX; py = e.clientY;
  };
  window.addEventListener('pointermove', onMove, { passive: true });
  cleanups.push(() => window.removeEventListener('pointermove', onMove));

  html.classList.add('film-live');
  cleanups.push(() => { html.classList.remove('film-live'); clearTheme(html); });
  if (logo) cleanups.push(() => { logo.style.opacity = ''; logo.style.visibility = ''; logo.style.transform = ''; logo.style.transformOrigin = ''; });

  // ---- UI driven by the same damped progress as the picture. DOM is written only when a (quantised) value changed.
  const nb = beats.length;
  const bV = new Int32Array(nb).fill(-1), bY = new Int32Array(nb).fill(1 << 30);
  let lastLogoT = -1;
  const applyUI = (p: number) => {
    setThemeProgress(p, html);
    for (let i = 0; i < nb; i++) {
      const b = beats[i];
      const be = BEATS[i] ?? [0, 1];
      const tin = i === 0 ? 1 : smooth((p - (be[0] + 0.004)) / FADE);
      const tout = i === BEATS.length - 1 ? 0 : smooth((p - (be[1] - FADE - 0.004)) / FADE);
      const v = tin * (1 - tout);
      const y = (1 - tin) * 38 - tout * 38;
      if (v < 0.003) {
        if (bV[i] !== -2) { b.style.visibility = 'hidden'; b.style.opacity = '0'; bV[i] = -2; bY[i] = 1 << 30; }
        continue;
      }
      const qv = Math.round(v * 1000), qy = Math.round(y * 10);
      if (qv === bV[i] && qy === bY[i]) continue;
      bV[i] = qv; bY[i] = qy;
      b.style.visibility = 'visible';
      b.style.opacity = (qv / 1000).toFixed(3);
      b.style.transform = `translate3d(0,${(qy / 10).toFixed(1)}px,0)`;
      b.style.filter = v > 0.995 ? '' : `blur(${((1 - v) * 9).toFixed(2)}px)`;
    }
    if (logo) {
      const t = smooth((p - 0.94) / 0.06);
      const qt = Math.round(t * 1000);
      if (qt === lastLogoT) return;
      lastLogoT = qt;
      logo.style.transformOrigin = 'left center';
      logo.style.opacity = t.toFixed(3);
      logo.style.visibility = t < 0.003 ? 'hidden' : 'visible';
      logo.style.transform = `scale(${(2.4 - 1.4 * t).toFixed(3)})`;
    }
  };

  // ---- frame selection (no allocation: results are written into reused objects)
  const ready = (i: number) => i >= 0 && i < N && s.ds[i] === 2 && (!gl || gl.has(i));
  const pReady = (i: number) => s.ps[i] === 2 && (!gl || gl.hasProxy(i));
  const br: Br = { a: -1, b: -1, mix: 0, ok: false };
  const pb: Br = { a: 0, b: 0, mix: 0, ok: true };
  /** Exact frames around f. Normally the two adjacent frames; if the upper/lower one is not on the GPU yet the nearest ready one within MAX_GAP is used. */
  const bracket = (f: number, o: Br) => {
    const fl = Math.floor(f), fr = f - fl;
    let lo = -1, hi = -1;
    for (let d = 0; d <= MAX_GAP; d++) if (ready(fl - d)) { lo = fl - d; break; }
    if (fr < 0.002 && lo === fl) { o.a = fl; o.b = fl; o.mix = 0; o.ok = true; return; }
    for (let d = 0; d <= MAX_GAP; d++) if (ready(fl + 1 + d)) { hi = fl + 1 + d; break; }
    if (fr > 0.998 && hi === fl + 1) { o.a = hi; o.b = hi; o.mix = 0; o.ok = true; return; }
    if (lo < 0 || hi < 0) { o.a = -1; o.b = -1; o.mix = 0; o.ok = false; return; }
    o.a = lo; o.b = hi; o.mix = (f - lo) / (hi - lo); o.ok = true;
  };
  const proxyBracket = (f: number, o: Br) => {
    let a = Math.floor(f / COARSE_STRIDE) * COARSE_STRIDE, b = Math.min(N - 1, a + COARSE_STRIDE);
    while (a > 0 && !pReady(a)) a -= COARSE_STRIDE;
    while (b < N - 1 && !pReady(b)) b = Math.min(N - 1, b + COARSE_STRIDE);
    if (!pReady(b)) b = a;
    if (!pReady(a)) a = b;
    o.a = a; o.b = b; o.mix = b > a ? clamp01((f - a) / (b - a)) : 0; o.ok = true;
  };
  /** Decoded frames in a row ahead of the playhead (in the scroll direction): how long it can run before it outpaces the window. */
  const runway = (c: number) => {
    for (let d = 1; d <= tier.decAhead; d++) {
      const i = c + s.dir * d;
      if (i < 0 || i >= N) return tier.decAhead;
      if (s.ds[i] !== 2) return d - 1;
    }
    return tier.decAhead;
  };
  const tryWarm = (i: number, c: number) => {
    if (i < 0 || i >= N || s.ds[i] !== 2 || gl!.has(i)) return false;
    gl!.warm(i, s.bmp[i]!, c, s.dir, br.a, br.b);
    return true;
  };
  /** At most one GPU upload per tick: frames the current draw needs, then ahead (on a lattice matching the speed), then everything near. */
  const warmOne = (c: number, perTick: number) => {
    const f0 = Math.floor(pos);
    if (tryWarm(f0, c) || tryWarm(f0 + 1, c)) return;
    const stp = Math.max(1, Math.min(3, Math.round(perTick)));
    if (stp > 1) for (let k = 1; k * stp <= tier.texAhead; k++) if (tryWarm(c + s.dir * k * stp, c)) return;
    const m = Math.max(tier.texAhead, tier.texBehind);
    for (let d = 1; d <= m; d++) {
      if (d <= tier.texAhead && tryWarm(c + s.dir * d, c)) return;
      if (d <= tier.texBehind && tryWarm(c - s.dir * d, c)) return;
    }
  };

  // ---- dev instrumentation
  const dev = import.meta.env.DEV ? makeDev() : null;
  if (import.meta.env.DEV && dev) {
    (window as any).__film = {
      get pos() { return pos; }, get target() { return target * (N - 1); }, get speed() { return Math.abs(vel); }, get gl() { return !!gl; }, store: s,
      stats: {
        get maxFrameMs() { return dev.max; }, get p95FrameMs() { return dev.p95(); }, get ticksOver20ms() { return dev.over20; },
        get ticksNotReady() { return dev.notReady; }, get maxStep() { return dev.maxStep; }, get ticks() { return dev.n; },
        get bitmaps() { return s.alive; }, get textures() { return gl ? gl.texCount : 0; },
        reset() { dev.reset(); },
      },
    };
    cleanups.push(() => { delete (window as any).__film; });
  }

  // ---- loop
  const io = new IntersectionObserver(([en]) => { visible = en.isIntersecting; if (visible) dirty = true; });
  io.observe(root);
  cleanups.push(() => io.disconnect());
  const t0 = performance.now();
  let last = t0, dtS = 1 / 60, lastUIp = -1, lastPar = 0, lastRound = -1, lastDir = 0;
  let lastF = -1, lastQ = -1, lastA = -2, lastB = -2, prevPos = pos;
  let prevTgt = target * (N - 1), tSpeed = 0, resting = false, capS = MAX_SPEED, q = 1, wasOk = true;
  const inp = { a: -1, b: -1, mix: 0, pa: 0, pb: 0, pmix: 0, q: 1, fluid: 0, liquid: 0, time: 0, par: [0, 0] as [number, number], dt: 0 };
  const tick = () => {
    const now = performance.now();
    const raw = now - last;
    last = now;
    const dt = Math.min(MAX_DT, Math.max(0.0005, raw / 1000));
    dtS += (Math.min(dt, 0.05) - dtS) * 0.05;
    if (import.meta.env.DEV && dev) {
      dev.iv[dev.n % RING] = raw; dev.n++;
      if (raw > dev.max) dev.max = raw;
      if (raw > 20) dev.over20++;
    }
    const tgtF = target * (N - 1);
    if (!visible) {
      // offscreen: no drawing, but keep theme/logo correct for wherever we are
      pos = tgtF; vel = 0; prevTgt = tgtF; prevPos = pos;
      const p = pos / (N - 1);
      if (p !== lastUIp) { lastUIp = p; filmState.progress = p; applyUI(p); }
      return;
    }

    // ---- playhead: one critically damped spring toward the scroll target (exact solution, so frame-rate independent)
    if (snap) { pos = tgtF; vel = 0; prevTgt = tgtF; resting = false; }
    else {
      // scroll speed in frames/s (low-passed). At rest the spring's destination becomes the nearest WHOLE frame: the same
      // glide continues onto it (no snap), and blending between neighbours only happens while the picture is moving.
      const spd = Math.abs(tgtF - prevTgt) / dt;
      prevTgt = tgtF;
      tSpeed += (spd - tSpeed) * (1 - Math.exp(-dt * 20));
      if (resting) { if (tSpeed > 4) resting = false; } else if (tSpeed < 1.5) resting = true;
      const dest = resting ? Math.round(tgtF) : tgtF;
      const dd = dest - pos;
      if (dd > 0.5) s.dir = 1; else if (dd < -0.5) s.dir = -1;
      // speed limit: never faster than MAX_SPEED, nor than the decoded window can feed
      const allowed = Math.max(MIN_SPEED, Math.min(MAX_SPEED, runway(Math.round(pos)) / RUNWAY_S));
      capS += (allowed - capS) * (1 - Math.exp(-dt * (allowed < capS ? 12 : 4)));
      const e = Math.exp(-OMEGA * dt);
      const c = pos - dest, t = (vel + OMEGA * c) * dt;
      let np = dest + (c + t) * e, nv = (vel - OMEGA * t) * e;
      const mx = capS * dt;
      if (np - pos > mx) np = pos + mx; else if (np - pos < -mx) np = pos - mx;
      if (nv > capS) nv = capS; else if (nv < -capS) nv = -capS;
      if ((dest - pos > 0) === (np > dest) && Math.abs(dest - pos) > 1e-9) { np = dest; nv = 0; } // crossed the destination
      if (Math.abs(np - dest) < 1e-4 && Math.abs(nv) < 1e-2) { np = dest; nv = 0; }
      pos = np; vel = nv;
    }
    if (pos < 0) { pos = 0; vel = 0; } else if (pos > N - 1) { pos = N - 1; vel = 0; }
    const p = pos / (N - 1);
    filmState.progress = p;
    if (p !== lastUIp) { lastUIp = p; applyUI(p); }
    holdAtEnd();
    if (import.meta.env.DEV && dev) { const d = Math.abs(pos - prevPos); if (d > dev.maxStep) dev.maxStep = d; }
    prevPos = pos;

    // ---- stream bookkeeping
    s.cur = pos;
    const fr = Math.round(pos);
    if (fr !== lastRound || s.dir !== lastDir) { lastRound = fr; lastDir = s.dir; evict(s); pumpFetch(s); pumpDecode(s); }

    // ---- what to draw
    bracket(pos, br);
    if (br.ok) { if (!wasOk) q = 0; q += (1 - q) * (1 - Math.exp(-dt / FADE_TAU)); if (q > 0.995) q = 1; }
    else q = 0;
    wasOk = br.ok;
    if (import.meta.env.DEV && dev && !br.ok) dev.notReady++;
    if (!br.ok || q < 1) proxyBracket(pos, pb);

    par.x += (parT.x - par.x) * (1 - Math.exp(-dt * 4)); par.y += (parT.y - par.y) * (1 - Math.exp(-dt * 4));
    const parMoved = Math.abs(par.x - parT.x) + Math.abs(par.y - parT.y) > 0.001 || lastPar !== par.x + par.y;
    lastPar = par.x + par.y;
    const liq = bump(p, 0.66, 0.84, 0.05, 0.05);
    const needDraw = dirty || pos !== lastF || q !== lastQ || br.a !== lastA || br.b !== lastB || parMoved || !!gl?.active || liq > 0.01;
    if (needDraw) {
      dirty = false; lastF = pos; lastQ = q; lastA = br.a; lastB = br.b;
      if (gl) {
        inp.a = br.a; inp.b = br.b; inp.mix = br.mix;
        inp.pa = pb.a; inp.pb = pb.b; inp.pmix = pb.mix; inp.q = q;
        inp.fluid = (touch ? 0.3 : 0.4) + 0.6 * liq; inp.liquid = touch ? liq * 0.6 : liq;
        inp.time = (now - t0) / 1000; inp.par[0] = par.x; inp.par[1] = par.y; inp.dt = dt;
        gl.render(inp);
      } else if (br.ok) draw2d(s.bmp[br.a]!, s.bmp[br.b]!, br.mix);
      else { const a = s.proxy[pb.a], b = s.proxy[pb.b]; if (a && b) draw2d(a, b, pb.mix); }
    }
    // one GPU upload per tick, after drawing, ahead of need
    if (gl) warmOne(fr, Math.abs(vel) * dtS);
  };
  gsap.ticker.add(tick);
  cleanups.push(() => gsap.ticker.remove(tick));
  applyUI(pos / (N - 1));

  // ---- preloader resolve
  const reveal = () => {
    if (dead) return;
    html.removeAttribute('data-pre');
    lenis?.start();
    snap = false; // from here on the playhead is damped
    const tl = gsap.timeline({ delay: 0.1 });
    if (titleSplit) tl.to(titleSplit.chars, { yPercent: 0, opacity: 1, duration: 1.1, ease: 'power4.out', stagger: 0.035 }, 0);
    if (role) tl.to(role, { opacity: 1, y: 0, duration: 0.9, ease: 'power3.out' }, 0.5);
  };
  if (showPre && pre && countEl && mark) {
    pre.style.display = 'grid';
    await new Promise<void>((res) => gsap.delayedCall(0.2, res));
    if (dead) return null;
    await new Promise<void>((res) => {
      gsap.timeline({ onComplete: res })
        .to(counter, { v: 100, duration: 0.4, onUpdate: () => { countEl.textContent = String(Math.round(counter.v)); } })
        .to(countEl, { yPercent: -120, opacity: 0, duration: 0.5, ease: 'power3.in' }, '+=0.15')
        .fromTo(mark, { scale: 0.6, opacity: 0 }, { scale: 1, opacity: 1, duration: 0.7, ease: 'power4.out' }, '<0.2')
        .to(mark, { scale: 0.9, opacity: 0, duration: 0.45, ease: 'power3.in' }, '+=0.45')
        .to(pre, { yPercent: -100, duration: 0.9, ease: 'power4.inOut' }, '-=0.1');
    });
    pre.style.display = '';
    gsap.set(pre, { clearProps: 'all' });
  }
  reveal();
  ScrollTrigger.refresh();

  return () => {
    dead = true;
    cleanups.forEach((c) => c());
    titleSplit?.revert();
    if (title) title.style.overflow = '';
    beats.forEach((b) => { b.style.opacity = ''; b.style.visibility = ''; b.style.transform = ''; b.style.filter = ''; });
  };
}
