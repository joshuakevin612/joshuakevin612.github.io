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
type Store = {
  key: string; w: number; h: number;
  src: (FrameSource | null)[]; st: Uint8Array; // 0 idle, 1 inflight, 2 done, 3 failed
  coarse: number[]; coarseOnly: boolean; inflight: number; cur: number; active: boolean; onProgress: (() => void) | null;
};
let store: Store | null = null;
const N = film.count;
const pad = (n: number) => String(n).padStart(4, '0');
const url = (key: string, i: number) => `/film/${key}/f_${pad(i + 1)}.webp`;
const dprCap = () => Math.min(devicePixelRatio || 1, 2);
const pickKey = () => (film.mobile && innerWidth * dprCap() <= film.mobile.width ? 'mobile' : 'desktop');
const MAX_INFLIGHT = 6;

function getStore(key: string): Store {
  if (store && store.key === key) return store;
  store?.src.forEach((s) => { if (s && 'close' in s) s.close(); });
  const dim = key === 'mobile' && film.mobile ? film.mobile : film.desktop;
  store = { key, w: dim.width, h: dim.height, src: new Array(N).fill(null), st: new Uint8Array(N), coarse: [], coarseOnly: false, inflight: 0, cur: 0, active: true, onProgress: null };
  return store;
}

async function fetchFrame(key: string, i: number): Promise<FrameSource> {
  if (typeof createImageBitmap === 'function') {
    const r = await fetch(url(key, i));
    if (!r.ok) throw new Error('frame ' + i);
    return createImageBitmap(await r.blob(), { premultiplyAlpha: 'none', colorSpaceConversion: 'none' });
  }
  const im = new Image(); im.decoding = 'async'; im.src = url(key, i);
  await im.decode();
  return im;
}

function pick(s: Store): number {
  for (const i of s.coarse) if (s.st[i] === 0) return i;
  if (s.coarseOnly) return -1;
  const c = Math.max(0, Math.min(N - 1, Math.round(s.cur)));
  for (let d = 0; d < N; d++) {
    if (c + d < N && s.st[c + d] === 0) return c + d;
    if (c - d >= 0 && s.st[c - d] === 0) return c - d;
  }
  return -1;
}

function pump(s: Store) {
  if (!s.active) return;
  while (s.inflight < MAX_INFLIGHT) {
    const i = pick(s);
    if (i < 0) break;
    s.st[i] = 1; s.inflight++;
    fetchFrame(s.key, i).then((src) => { s.src[i] = src; s.st[i] = 2; }, () => { s.st[i] = 3; }).finally(() => {
      s.inflight--; s.onProgress?.(); pump(s);
    });
  }
}

const loaded = (s: Store, i: number) => s.st[i] === 2;
const below = (s: Store, i: number) => { for (let k = i; k >= 0; k--) if (loaded(s, k)) return k; return -1; };
const above = (s: Store, i: number) => { for (let k = i; k < N; k++) if (loaded(s, k)) return k; return -1; };

/** Neighbouring loaded frames around float position f, plus blend factor. Never returns "nothing" once any frame exists. */
function neighbours(s: Store, f: number): { a: number; b: number; mix: number } | null {
  const fl = Math.max(0, Math.min(N - 1, Math.floor(f)));
  const ce = Math.min(N - 1, fl + 1);
  let lo = below(s, fl), hi = above(s, ce);
  if (lo < 0) lo = hi;
  if (hi < 0) hi = lo;
  if (lo < 0) return null;
  const mix = hi > lo ? Math.max(0, Math.min(1, (f - lo) / (hi - lo))) : 0;
  return { a: lo, b: hi, mix };
}

// ------------------------------------------------------------------ theme blend
// Mirrors the token sets in global.css (light = :root, dark = [data-theme=dark]).
const hex = (h: string) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
const LIGHT = { '--bg': hex('#F2EEE6'), '--surface': hex('#E7E1D6'), '--text': hex('#14130F'), '--text-2': hex('#6F6A60'), '--line': hex('#D5CEC1') };
const DARK = { '--bg': hex('#0B0B0C'), '--surface': hex('#161617'), '--text': hex('#ECE8DF'), '--text-2': hex('#8A867E'), '--line': hex('#2A2A2C') };
const THEME_A = 0.44, THEME_B = 0.52;
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
  return clamp01(-r.top / Math.max(1, r.height - innerHeight));
}

// ------------------------------------------------------------------ captions
// [start, end] in film progress; beat 1 = workspace, 2 = to the keyboard, (launch has none), 3 = spin, 4 = liquid, 5 = push-in
const BEATS: Array<[number, number]> = [[0, 0.25], [0.25, 0.42], [0.52, 0.69], [0.69, 0.83], [0.83, 1]];
const FADE = 0.03;
const bump = (p: number, a: number, b: number, fa: number, fb: number) => smooth((p - a) / fa) * (1 - smooth((p - b) / fb));

interface Opts { lenis: Lenis | null; reduced: boolean; add: (fn: () => void) => void }

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

  // ---- progress source (scroll) + initial position
  let target = reduced ? 1 : heroProgress(root);
  let cur = target;
  const vel = { v: 0 };
  let snap = true; // until the intro finishes, follow the scroll exactly (load at any offset / anchor jump)
  const st = reduced ? null : ScrollTrigger.create({
    trigger: root, start: 'top top', end: 'bottom bottom',
    onUpdate: (s) => { target = s.progress; },
    onRefresh: (s) => { target = s.progress; if (snap) cur = target; },
  });
  if (st) { target = st.progress; cur = target; cleanups.push(() => st.kill()); }

  // ---- load: coarse set first (preloader), then stream the rest around the playhead
  const s = getStore(pickKey());
  s.active = true;
  s.cur = cur * (N - 1);
  s.coarseOnly = reduced;
  const want = new Set<number>(reduced ? [N - 1] : [0, N - 1]);
  if (!reduced) {
    for (let i = 0; i < N; i += 10) want.add(i);
    const c = Math.round(s.cur);
    for (let d = -6; d <= 6; d++) if (c + d >= 0 && c + d < N) want.add(c + d);
  }
  s.coarse = Array.from(want).sort((x, y) => Math.abs(x - s.cur) - Math.abs(y - s.cur));
  const counter = { v: 0 };
  await new Promise<void>((res) => {
    const check = () => {
      const done = s.coarse.filter((i) => s.st[i] >= 2).length;
      const p = done / s.coarse.length;
      if (showPre && countEl) gsap.to(counter, { v: p * 100, duration: 0.6, ease: 'power2.out', overwrite: true, onUpdate: () => { countEl.textContent = String(Math.round(counter.v)); } });
      if (done === s.coarse.length || dead) { s.onProgress = null; res(); }
    };
    s.onProgress = check;
    pump(s);
    check();
  });
  if (dead) { s.active = false; return null; }
  cleanups.push(() => { s.active = false; s.onProgress = null; });

  // ---- renderer (WebGL, with 2D fallback)
  const ratio = s.w / s.h;
  const gl: FilmGL | null = reduced ? null : createFilmGL(canvas, { lite: touch, imgAspect: ratio });
  const c2d = gl ? null : canvas.getContext('2d', { alpha: false });
  let dirty = true;
  let lastRes = '';
  const size = () => {
    const dpr = dprCap();
    const w = canvas.clientWidth, h = canvas.clientHeight;
    if (gl) gl.resize(w, h, dpr);
    else { canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr); }
    lastRes = `${w}x${h}x${dpr}`;
    dirty = true;
  };
  size();
  const draw2d = (n: { a: number; b: number; mix: number }) => {
    if (!c2d) return;
    const cw = canvas.width, ch = canvas.height;
    c2d.imageSmoothingEnabled = true; c2d.imageSmoothingQuality = 'high';
    const put = (src: FrameSource) => {
      const iw = (src as any).width as number, ih = (src as any).height as number;
      const k = Math.max(cw / iw, ch / ih);
      c2d.drawImage(src, (cw - iw * k) / 2, (ch - ih * k) / 2, iw * k, ih * k);
    };
    c2d.globalAlpha = 1; put(s.src[n.a]!);
    if (n.b !== n.a && n.mix > 0.002) { c2d.globalAlpha = n.mix; put(s.src[n.b]!); c2d.globalAlpha = 1; }
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
    const n = neighbours(s, N - 1);
    if (n) draw2d({ a: n.a, b: n.a, mix: 0 });
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

  // ---- UI driven by the same damped progress as the picture
  const applyUI = (p: number) => {
    setThemeProgress(p, html);
    beats.forEach((b, i) => {
      const [a, e] = BEATS[i] ?? [0, 1];
      const tin = i === 0 ? 1 : smooth((p - (a + 0.004)) / FADE);
      const tout = i === BEATS.length - 1 ? 0 : smooth((p - (e - FADE - 0.004)) / FADE);
      const v = tin * (1 - tout);
      const y = (1 - tin) * 38 - tout * 38;
      if (v < 0.003) { if (b.style.visibility !== 'hidden') { b.style.visibility = 'hidden'; b.style.opacity = '0'; } return; }
      b.style.visibility = 'visible';
      b.style.opacity = v.toFixed(3);
      b.style.transform = `translate3d(0,${y.toFixed(2)}px,0)`;
      b.style.filter = v > 0.995 ? '' : `blur(${((1 - v) * 9).toFixed(2)}px)`;
    });
    if (logo) {
      const t = smooth((p - 0.94) / 0.06);
      logo.style.transformOrigin = 'left center';
      logo.style.opacity = t.toFixed(3);
      logo.style.visibility = t < 0.003 ? 'hidden' : 'visible';
      logo.style.transform = `scale(${(2.4 - 1.4 * t).toFixed(3)})`;
    }
  };

  // ---- loop
  const io = new IntersectionObserver(([en]) => { visible = en.isIntersecting; if (visible) dirty = true; });
  io.observe(root);
  cleanups.push(() => io.disconnect());
  const t0 = performance.now();
  let last = t0, lastGrain = -1, lastF = -1, lastUIp = -1, lastPar = 0;
  const tick = () => {
    const now = performance.now();
    const dt = Math.min(0.05, Math.max(0.001, (now - last) / 1000));
    last = now;
    if (!visible) {
      // offscreen: no drawing, but keep theme/logo correct for wherever we are
      if (cur !== target) { cur = target; vel.v = 0; }
      if (cur !== lastUIp) { lastUIp = cur; filmState.progress = cur; applyUI(cur); }
      return;
    }
    // critically damped follow (smooth-damp), frame-rate independent
    if (snap) { cur = target; vel.v = 0; }
    else {
      const om = 2 / 0.17, x = om * dt, ex = 1 / (1 + x + 0.48 * x * x + 0.235 * x * x * x);
      const ch = cur - target, tmp = (vel.v + om * ch) * dt;
      vel.v = (vel.v - om * tmp) * ex;
      let out = target + (ch + tmp) * ex;
      if ((target - cur > 0) === (out > target)) { out = target; vel.v = 0; }
      if (Math.abs(out - target) < 1e-6 && Math.abs(vel.v) < 1e-5) { out = target; vel.v = 0; }
      cur = out;
    }
    filmState.progress = cur;
    if (cur !== lastUIp) { lastUIp = cur; applyUI(cur); }

    const f = cur * (N - 1);
    s.cur = f;
    if (Math.abs(f - lastF) > 0.5) pump(s);
    const n = neighbours(s, f);
    if (!n) return; // nothing loaded (cannot happen after preload); canvas keeps its last picture, never blanked

    par.x += (parT.x - par.x) * (1 - Math.exp(-dt * 4)); par.y += (parT.y - par.y) * (1 - Math.exp(-dt * 4));
    const parMoved = Math.abs(par.x - parT.x) + Math.abs(par.y - parT.y) > 0.001 || lastPar !== par.x + par.y;
    lastPar = par.x + par.y;

    const liq = bump(cur, 0.66, 0.84, 0.05, 0.05);
    const gT = Math.floor(((now - t0) / 1000) * 24);
    if (!(dirty || f !== lastF || parMoved || gl?.active || liq > 0.01 || gT !== lastGrain)) return;
    dirty = false; lastF = f; lastGrain = gT;
    if (gl) {
      gl.render({
        a: n.a, aSrc: s.src[n.a]!, b: n.b, bSrc: s.src[n.b]!, mix: n.mix,
        fluid: (touch ? 0.3 : 0.4) + 0.6 * liq, liquid: touch ? liq * 0.6 : liq,
        time: (now - t0) / 1000, par: [par.x, par.y], dt,
      });
    } else draw2d(n);
  };
  gsap.ticker.add(tick);
  cleanups.push(() => gsap.ticker.remove(tick));
  applyUI(cur);
  if (import.meta.env.DEV) (window as any).__film = { get cur() { return cur; }, get target() { return target; }, get gl() { return !!gl; }, store: s };

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
