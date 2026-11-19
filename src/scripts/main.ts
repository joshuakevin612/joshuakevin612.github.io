import gsap from 'gsap';
import { ScrollTrigger } from 'gsap/ScrollTrigger';
import { SplitText } from 'gsap/SplitText';
import Lenis from 'lenis';
import { initFilm, setThemeProgress, heroProgress } from './film';
import { initWork } from './work';
import { initNext } from './next';

gsap.registerPlugin(ScrollTrigger, SplitText);
if (import.meta.env.DEV) (window as any).__ST = ScrollTrigger;

let active = false;
let gen = 0; // bumped by dispose(); an init() that awaited across a page swap sees a newer generation and bails
let lenis: Lenis | null = null;
let ctx: gsap.Context | null = null;
let disposers: Array<() => void> = [];
const mouse = { x: -100, y: -100 };
window.addEventListener('pointermove', (e) => { mouse.x = e.clientX; mouse.y = e.clientY; }, { passive: true });

const $ = <T extends Element = HTMLElement>(s: string) => document.querySelector<T>(s);
const $$ = <T extends Element = HTMLElement>(s: string) => Array.from(document.querySelectorAll<T>(s));
const on = (t: EventTarget, ev: string, fn: any, o?: any) => { t.addEventListener(ev, fn, o); disposers.push(() => t.removeEventListener(ev, fn, o)); };

// A reload starts at the top (the film is meant to be watched from its first frame). Astro's router restores the old
// offset from history.state before this module runs, so clear that too. Back/forward keeps its position.
const navType = (performance.getEntriesByType('navigation')[0] as PerformanceNavigationTiming | undefined)?.type;
if (navType === 'reload' && !location.hash) {
  history.scrollRestoration = 'manual';
  history.replaceState({ ...history.state, scrollX: 0, scrollY: 0 }, '');
  window.scrollTo(0, 0);
}

async function init() {
  if (active) return;
  active = true;
  const my = gen;
  const dead = () => my !== gen;
  const root = document.documentElement;
  const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const fine = matchMedia('(hover: hover) and (pointer: fine)').matches;
  const isHome = !!$('[data-film]');
  root.classList.toggle('reduced', reduced);
  root.dataset.theme = isHome && !reduced ? 'light' : 'dark';
  if (!isHome) root.removeAttribute('data-pre');
  window.scrollTo(0, isHome ? window.scrollY : 0);

  ctx = gsap.context(() => {});
  // Theme derives from the scroll offset on load / jumps / back-nav; once the film runs it drives the blend from its damped progress.
  const heroEl = $('[data-film]');
  if (heroEl && !reduced) setThemeProgress(heroProgress(heroEl));
  const add = (fn: () => void) => ctx!.add(fn);

  // Lenis <-> ScrollTrigger
  if (!reduced) {
    // Light smoothing only (time constant ~67 ms, dt-corrected in Lenis 1.3): it turns wheel notches into a continuous
    // scroll, while the film playhead (film.ts, PLAYHEAD_T95) supplies the long glide. Stacking a heavy Lenis lerp on top
    // of the playhead spring would add ~0.6 s of lag and feel like mush.
    lenis = new Lenis({ lerp: 0.25, wheelMultiplier: 0.95 });
    if (import.meta.env.DEV) (window as any).__lenis = lenis;
    lenis.on('scroll', ScrollTrigger.update);
    const tick = (t: number) => lenis?.raf(t * 1000);
    gsap.ticker.add(tick);
    gsap.ticker.lagSmoothing(0);
    disposers.push(() => gsap.ticker.remove(tick));
    if (isHome && root.hasAttribute('data-pre')) lenis.stop();
  }

  // anchors with Lenis
  on(document, 'click', (e: MouseEvent) => {
    const a = (e.target as HTMLElement).closest<HTMLAnchorElement>('a[href*="#"]');
    if (!a) return;
    const u = new URL(a.href, location.href);
    if (u.pathname !== location.pathname || !u.hash) return;
    let el: Element | null = null;
    try { el = document.querySelector(u.hash); } catch { return; }
    if (!el) return;
    e.preventDefault();
    e.stopPropagation(); // keep ClientRouter out of same-page anchors
    history.replaceState(history.state, '', u.hash);
    if (lenis) lenis.scrollTo(el as HTMLElement, { offset: 0, duration: 1.4 });
    else el.scrollIntoView();
  }, true);

  // cursor
  const cur = $('[data-cursor]');
  if (cur && fine) {
    root.classList.add('has-cursor');
    disposers.push(() => root.classList.remove('has-cursor'));
    const qx = gsap.quickTo(cur, 'x', { duration: 0.25, ease: 'power3' });
    const qy = gsap.quickTo(cur, 'y', { duration: 0.25, ease: 'power3' });
    qx(mouse.x); qy(mouse.y);
    on(window, 'pointermove', (e: PointerEvent) => { cur.classList.add('on'); qx(e.clientX); qy(e.clientY); });
    on(document, 'pointerover', (e: Event) => {
      cur.classList.toggle('big', !!(e.target as HTMLElement).closest('a, button, [data-magnetic]'));
    });
    let label = '';
    on(window, 'pointermove', (e: PointerEvent) => {
      const l = (e.target as HTMLElement).closest?.('[data-cursor-label]')?.getAttribute('data-cursor-label') ?? '';
      if (l !== label) { label = l; cur.textContent = l; cur.classList.toggle('label', !!l); }
    });
    on(document, 'pointerleave', () => cur.classList.remove('on'));
  }

  // progress bar
  const bar = $('[data-progress]');
  if (bar) add(() => { gsap.to(bar, { scaleX: 1, ease: 'none', scrollTrigger: { start: 0, end: 'max', scrub: 0 } }); });

  // magnetic
  if (fine && !reduced) {
    $$('[data-magnetic]').forEach((el) => {
      const move = (e: PointerEvent) => {
        const r = el.getBoundingClientRect();
        gsap.to(el, { x: (e.clientX - r.left - r.width / 2) * 0.25, y: (e.clientY - r.top - r.height / 2) * 0.25, duration: 0.5, ease: 'power3.out' });
      };
      const leave = () => gsap.to(el, { x: 0, y: 0, duration: 1, ease: 'elastic.out(1, 0.4)' });
      on(el, 'pointermove', move); on(el, 'pointerleave', leave);
      disposers.push(() => gsap.killTweensOf(el));
    });
  }

  // local time
  const t = $('[data-time]');
  if (t) {
    const fmt = new Intl.DateTimeFormat('en-GB', { timeZone: 'Asia/Kolkata', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });
    const upd = () => { t.textContent = fmt.format(new Date()); };
    upd();
    const id = setInterval(upd, 1000);
    disposers.push(() => clearInterval(id));
  }

  // generic reveals
  $$('[data-reveal]').forEach((el) => {
    add(() => { gsap.from(el, { autoAlpha: 0, y: reduced ? 0 : 40, duration: reduced ? 0.4 : 1, ease: 'power3.out', scrollTrigger: { trigger: el, start: 'top 90%' } }); });
  });
  $$('[data-prose] > *').forEach((el) => {
    add(() => { gsap.from(el, { autoAlpha: 0, y: reduced ? 0 : 30, duration: reduced ? 0.4 : 0.9, ease: 'power3.out', scrollTrigger: { trigger: el, start: 'top 90%' } }); });
  });

  // parallax cover
  const cover = $('[data-parallax] img');
  if (cover && !reduced) add(() => { gsap.fromTo(cover, { yPercent: -7 }, { yPercent: 7, ease: 'none', scrollTrigger: { trigger: '[data-parallax]', scrub: true, start: 'top bottom', end: 'bottom top' } }); });

  await document.fonts.ready;
  if (dead()) return;

  // split text (lines on scroll, project title chars on load)
  if (!reduced) {
    $$('[data-lines]').forEach((el) => {
      add(() => {
        SplitText.create(el, {
          type: 'lines', mask: 'lines', autoSplit: true,
          onSplit: (self) => gsap.from(self.lines, { yPercent: 110, duration: 1.2, ease: 'power4.out', stagger: 0.12, scrollTrigger: { trigger: el, start: 'top 85%' } }),
        });
      });
    });
    const pt = $('[data-proj-title]');
    if (pt) add(() => {
      // Split by word as well so titles only wrap between words, then shrink the title until its longest word fits the column.
      const s = SplitText.create(pt, { type: 'words,chars', mask: 'chars' });
      s.words.forEach((w) => { (w as HTMLElement).style.whiteSpace = 'nowrap'; });
      const fit = () => {
        pt.style.fontSize = '';
        const max = Math.max(...s.words.map((w) => (w as HTMLElement).offsetWidth)), cw = pt.clientWidth;
        if (max > cw) pt.style.fontSize = `${(parseFloat(getComputedStyle(pt).fontSize) * cw / max) * 0.98}px`;
      };
      fit(); on(window, 'resize', fit);
      gsap.from(s.chars, { yPercent: 110, duration: 1, ease: 'power4.out', stagger: 0.04, delay: 0.2 });
    });
  }

  // marquee reacting to scroll velocity
  const track = $('[data-marquee-track]');
  if (track && !reduced) {
    let x = 0, dir = -1, boost = 0;
    const tick = () => {
      const dt = Math.min(gsap.ticker.deltaRatio(60), 3);
      const v = lenis?.velocity ?? 0;
      if (Math.abs(v) > 0.4) dir = v > 0 ? -1 : 1;
      boost += (Math.min(Math.abs(v), 40) - boost) * 0.08;
      const w = track.scrollWidth / 2;
      x += dir * (1.1 + boost * 0.6) * dt;
      if (x <= -w) x += w; if (x > 0) x -= w;
      track.style.transform = `translate3d(${x}px,0,0)`;
    };
    gsap.ticker.add(tick);
    disposers.push(() => gsap.ticker.remove(tick));
  }

  // projects stage (three) + next-project footer
  { const d = initWork({ lenis, reduced, add }); if (d) disposers.push(d); }
  { const d = initNext(reduced, add); if (d) disposers.push(d); }

  // film
  if (isHome) {
    const d = await initFilm({ lenis, reduced, add });
    if (dead()) { d?.(); return; }
    if (d) disposers.push(d);
  }

  ScrollTrigger.refresh();
}

function dispose() {
  if (!active) return;
  active = false; gen++;
  disposers.forEach((d) => { try { d(); } catch {} });
  disposers = [];
  ScrollTrigger.getAll().forEach((s) => s.kill());
  ctx?.revert(); ctx = null;
  lenis?.destroy(); lenis = null;
  document.documentElement.classList.remove('lenis', 'lenis-smooth', 'lenis-stopped');
}

document.addEventListener('astro:page-load', init);
document.addEventListener('astro:before-swap', (e: any) => {
  dispose();
  const nd: Document = e.newDocument;
  if (nd.documentElement.dataset.pre !== undefined) nd.documentElement.removeAttribute('data-pre');
});
if (document.readyState !== 'loading') init();
