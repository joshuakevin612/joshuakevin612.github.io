import gsap from 'gsap';
import { ScrollTrigger } from 'gsap/ScrollTrigger';
import { SplitText } from 'gsap/SplitText';
import * as THREE from 'three';
import type Lenis from 'lenis';
import { fillAndGo } from './open';

interface Item { slug: string; title: string; year: number; role: string; stack: string[]; img: string }
interface Opts { lenis: Lenis | null; reduced: boolean; add: (fn: () => void) => void }

const clamp = (v: number, a: number, b: number) => Math.max(a, Math.min(b, v));
const pad = (n: number) => String(n).padStart(2, '0');

const VERT = `
  uniform float uVel; varying vec2 vUv;
  void main() {
    vUv = uv; vec3 p = position;
    float b = clamp(uVel, -1., 1.);
    p.z -= p.x * p.x * abs(b) * 2.2;       // bend along the arc with speed
    p.y += p.x * b * 0.18;                  // lean
    p.x *= 1. + abs(b) * 0.16;              // stretch
    gl_Position = projectionMatrix * modelViewMatrix * vec4(p, 1.);
  }`;
const FRAG = `
  uniform sampler2D uTex; uniform float uVel, uPlane, uImg, uDim, uFade; varying vec2 vUv;
  void main() {
    vec2 uv = (vUv - .5) * vec2(min(1., uPlane / uImg), min(1., uImg / uPlane)) + .5;
    float s = clamp(uVel, -1., 1.) * 0.022;
    float r = texture2D(uTex, uv + vec2(s, 0.)).r;
    float g = texture2D(uTex, uv).g;
    float b = texture2D(uTex, uv - vec2(s, 0.)).b;
    gl_FragColor = vec4(vec3(r, g, b) * (1. - uDim * 0.35), uFade * (1. - uDim * 0.7));
  }`;

export function initWork({ lenis, reduced, add }: Opts): (() => void) | null {
  const section = document.querySelector<HTMLElement>('[data-work]');
  if (!section) return null;
  const items: Item[] = JSON.parse(section.dataset.items || '[]');
  const N = items.length;
  if (!N) return null;
  const canvas = section.querySelector<HTMLCanvasElement>('[data-work-canvas]')!;
  const pin = section.querySelector<HTMLElement>('[data-work-pin]')!;
  const links = Array.from(section.querySelectorAll<HTMLAnchorElement>('[data-work-list] a'));

  const makeStatic = () => {
    section.classList.add('work--static');
    const cards = Array.from(section.querySelectorAll('[data-work-list] li'));
    if (!reduced) add(() => { gsap.from(cards, { autoAlpha: 0, y: 40, duration: 0.9, ease: 'power3.out', stagger: 0.12, scrollTrigger: { trigger: section.querySelector('[data-work-list]'), start: 'top 85%' } }); });
    return null;
  };
  if (reduced) return makeStatic();

  let renderer: THREE.WebGLRenderer;
  try {
    renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true, powerPreference: 'high-performance' });
  } catch { return makeStatic(); }
  renderer.setClearColor(0x000000, 0);
  section.classList.add('work--gl');
  // page scroll only walks the first `scrolled` projects; the rest are reached by drag/keys/clicks (offset)
  const cap = Math.max(2, Number(section.dataset.scrollCap) || 5);
  const scrolled = Math.min(N, cap);
  section.style.setProperty('--n', String(Math.max(scrolled, 2)));

  // ---------- scene
  const scene = new THREE.Scene();
  const FOV = 36, CAMZ = 7;
  const cam = new THREE.PerspectiveCamera(FOV, 1, 0.1, 50);
  cam.position.z = CAMZ;
  const geo = new THREE.PlaneGeometry(1, 1, 24, 1);
  const blank = new THREE.DataTexture(new Uint8Array([22, 22, 23, 255]), 1, 1);
  blank.needsUpdate = true;
  const textures: THREE.Texture[] = [];
  const meshes = items.map((it, i) => {
    const mat = new THREE.ShaderMaterial({
      transparent: true, depthTest: false, depthWrite: false,
      uniforms: { uTex: { value: blank }, uVel: { value: 0 }, uPlane: { value: 1.6 }, uImg: { value: 1.6 }, uDim: { value: 0 }, uFade: { value: 1 } },
      vertexShader: VERT, fragmentShader: FRAG,
    });
    const m = new THREE.Mesh(geo, mat);
    scene.add(m);
    if (it.img) {
      new THREE.TextureLoader().load(it.img, (t) => {
        textures[i] = t; t.anisotropy = 4;
        renderer.initTexture(t); // upload now, so the first frame a card comes into view does not hitch
        mat.uniforms.uTex.value = t; mat.uniforms.uImg.value = t.image.width / t.image.height;
      });
    }
    return m;
  });

  let vw = 1, vh = 1, cardW = 1, cardH = 1, unitPx = 300, W = 1, H = 1, yC = 0;
  const resize = () => {
    W = pin.clientWidth; H = pin.clientHeight;
    renderer.setPixelRatio(Math.min(devicePixelRatio || 1, 2));
    renderer.setSize(W, H, false);
    cam.aspect = W / H; cam.updateProjectionMatrix();
    vh = 2 * CAMZ * Math.tan((FOV * Math.PI) / 360); vw = vh * cam.aspect;
    // Card is anchored to the title: its lower edge stops just above the title's top edge, so light screenshots never sit behind the title text.
    const titleEl = section.querySelector<HTMLElement>('[data-work-title]')!;
    const fs = parseFloat(getComputedStyle(titleEl).fontSize) || 100;
    const lineH = fs * 0.92;
    const pr = pin.getBoundingClientRect(), tr = titleEl.getBoundingClientRect();
    const bottomPx = tr.bottom - pr.top - lineH - lineH * 0.12;
    const topLimit = Math.max(72, 4.75 * 16);
    const avail = Math.max(120, bottomPx - topLimit);
    const portrait = W / H < 1;
    // Covers are 16:10 app screenshots, so portrait viewports get a wide 5:4 card that keeps most of the frame instead of a tall crop.
    const hpx = Math.min(avail, portrait ? W * 0.84 * 0.8 : H * 0.5);
    const wpx = portrait ? W * 0.84 : Math.min(W * 0.74, hpx * 1.6);
    const k = vh / H;
    cardW = wpx * k; cardH = hpx * k;
    yC = (H / 2 - (bottomPx - hpx / 2)) * k;
    unitPx = wpx * 1.15;
  };
  resize();

  // ---------- DOM overlay
  const titleEl = section.querySelector<HTMLElement>('[data-work-title]')!;
  const countEl = section.querySelector<HTMLElement>('[data-work-count]')!;
  const metaEl = section.querySelector<HTMLElement>('[data-work-meta]')!;
  const ui = section.querySelector<HTMLElement>('[data-work-ui]')!;
  const bar = section.querySelector<HTMLElement>('[data-work-bar]')!;
  const segs = items.map(() => { const s = document.createElement('span'); s.appendChild(document.createElement('i')); bar.appendChild(s); return s.firstElementChild as HTMLElement; });
  let split: SplitText | null = null;
  let tw: gsap.core.Tween | null = null;
  // Long titles are scaled down to the available width. A transform (not font-size) so the card geometry, which is anchored to the title's font size, stays put.
  const fitTitle = () => {
    titleEl.style.transform = '';
    const avail = titleEl.parentElement!.clientWidth, w = titleEl.scrollWidth;
    if (w > avail + 1) titleEl.style.transform = `scale(${avail / w})`;
  };
  countEl.innerHTML = `<b></b> / ${pad(N)}`;
  const countB = countEl.firstElementChild as HTMLElement;
  metaEl.innerHTML = '<span></span><span></span>';
  const metaLines = Array.from(metaEl.children) as HTMLElement[];
  // Title and meta swaps are coalesced. A change hides the current title once; the new one is only built (SplitText is a DOM
  // rebuild) after the carousel has stayed on one project for a moment, so flying past several projects costs one swap, not one each.
  let phase: 'empty' | 'idle' | 'out' | 'hidden' | 'in' = 'empty';
  let want = 0, wantDir = 1, wantAt = 0, titleIdx = -1;
  const SETTLE = 110;
  const showTitle = () => {
    const it = items[want], dir = wantDir;
    tw?.kill(); split?.revert();
    titleEl.textContent = it.title;
    split = SplitText.create(titleEl, { type: 'chars', mask: 'chars', maskClass: 'wmask' });
    fitTitle();
    metaLines[0].textContent = `${it.year} — ${it.role}`;
    metaLines[1].textContent = it.stack.join(' · ');
    phase = 'in';
    gsap.set(split.chars, { yPercent: 110 * dir });
    tw = gsap.to(split.chars, { yPercent: 0, duration: 0.7, ease: 'power4.out', stagger: 0.03, onComplete: () => { phase = 'idle'; } });
    gsap.fromTo(metaLines, { opacity: 0, y: 10 * dir }, { opacity: 1, y: 0, duration: 0.5, ease: 'power3.out', stagger: 0.05, overwrite: true });
  };
  const hideTitle = () => {
    tw?.kill(); phase = 'out';
    tw = gsap.to(split!.chars, { yPercent: -110 * wantDir, duration: 0.22, ease: 'power3.in', stagger: 0.01, onComplete: () => { phase = 'hidden'; } });
    gsap.to(metaLines, { opacity: 0, duration: 0.2, overwrite: true });
  };
  const requestTitle = (i: number, dir: number) => {
    want = i; wantDir = dir; wantAt = performance.now();
    countB.textContent = pad(i + 1);
    if (phase === 'idle' || phase === 'in') hideTitle();
  };

  // ---------- state
  // The carousel is a loop. Its position is the page scroll through the stage plus `offset`, which drag, arrow keys, clicks
  // and the resting snap move. Scroll still drives it (and is re-read every frame); the page itself is never scrolled from here.
  let cur = 0, target = 0, vel = 0, active = -1, offset = 0;
  let dragging = false, opening = false, visible = false, lastY = -1;
  let lastInput = performance.now();
  const open = { k: 0, fade: 0 };
  let openIdx = -1;
  const ptr = { x: 0, y: 0 };
  const mod = (i: number) => ((i % N) + N) % N;
  /** shortest signed distance on the loop, in [-N/2, N/2) */
  const wrap = (d: number) => (N > 1 ? (((d % N) + N * 1.5) % N) - N / 2 : d);

  // start/end only; position is derived from the live scroll offset every frame (see tick)
  const st = ScrollTrigger.create({ trigger: section, start: 'top top', end: 'bottom bottom', invalidateOnRefresh: true });
  const scrollPos = () => (N > 1 && st.end > st.start ? clamp((scrollY - st.start) / (st.end - st.start), 0, 1) * (scrolled - 1) : 0);
  const total = () => scrollPos() + offset;
  /** rest on whole position `whole` (any integer; it is taken round the loop) */
  const settleOn = (whole: number) => { offset += whole - total(); lastInput = performance.now(); };
  const step = (dir: number) => { if (N > 1) settleOn(Math.round(total()) + dir); };
  const goTo = (i: number) => { if (N > 1) { const r = Math.round(total()); settleOn(r + wrap(i - r)); } };

  const openProject = (i: number) => {
    if (opening) return;
    opening = true; openIdx = i;
    lenis?.stop();
    const tl = gsap.timeline({ onComplete: () => fillAndGo(items[i].img, items[i].slug) });
    if (split) tl.to(split.chars, { yPercent: -110, duration: 0.4, ease: 'power3.in', stagger: 0.015 }, 0);
    tl.to(ui, { opacity: 0, duration: 0.4 }, 0)
      .to(open, { fade: 1, duration: 0.6, ease: 'power3.in' }, 0)
      .to(open, { k: 1, duration: 1, ease: 'power4.inOut' }, 0.15);
  };

  // ---------- input
  const ray = new THREE.Raycaster();
  const hit = (e: PointerEvent, onlyActive: boolean) => {
    const r = canvas.getBoundingClientRect();
    ray.setFromCamera(new THREE.Vector2(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1), cam);
    const list = onlyActive ? [meshes[active]] : meshes.filter((m) => m.visible);
    const h = ray.intersectObjects(list, false)[0];
    return h ? meshes.indexOf(h.object as THREE.Mesh) : -1;
  };
  let down: { x: number; t: number; start: number; id: number } | null = null;
  let samples: Array<{ x: number; t: number }> = [];
  const onDown = (e: PointerEvent) => {
    if (opening || (e.pointerType === 'mouse' && e.button !== 0)) return;
    down = { x: e.clientX, t: performance.now(), start: offset, id: e.pointerId };
    samples = [{ x: e.clientX, t: performance.now() }];
  };
  const onMove = (e: PointerEvent) => {
    const r = canvas.getBoundingClientRect();
    ptr.x = ((e.clientX - r.left) / r.width) * 2 - 1; ptr.y = -(((e.clientY - r.top) / r.height) * 2 - 1);
    if (down && e.pointerId === down.id) {
      const dx = e.clientX - down.x;
      if (!dragging && Math.abs(dx) > 6) { dragging = true; canvas.classList.add('is-drag'); try { canvas.setPointerCapture(e.pointerId); } catch {} }
      if (dragging) {
        offset = down.start - dx / unitPx;
        lastInput = performance.now();
        samples.push({ x: e.clientX, t: performance.now() });
        if (samples.length > 6) samples.shift();
      }
    }
    if (!dragging && !opening && e.target === canvas && active >= 0) {
      canvas.dataset.cursorLabel = hit(e, true) === active ? 'Open' : 'Drag';
    }
  };
  const endDrag = (e: PointerEvent, cancelled: boolean) => {
    if (!down || e.pointerId !== down.id) return;
    const d = down; down = null;
    if (dragging) {
      dragging = false; canvas.classList.remove('is-drag');
      const a = samples[0], b = samples[samples.length - 1];
      const v = b && a && b.t > a.t ? -((b.x - a.x) / (b.t - a.t)) * 1000 / unitPx : 0; // units / s
      if (N > 1) settleOn(Math.round(total() + v * 0.25));
      return;
    }
    if (cancelled || opening || Math.abs(e.clientX - d.x) > 6) return;
    const i = hit(e, false);
    if (i < 0) return;
    if (i === active && Math.abs(wrap(cur - i)) < 0.2) openProject(i); else goTo(i);
  };
  const onUp = (e: PointerEvent) => endDrag(e, false);
  const onCancel = (e: PointerEvent) => endDrag(e, true);
  const onLeave = () => { canvas.dataset.cursorLabel = 'Drag'; };
  const onWheel = () => { lastInput = performance.now(); };
  const inStage = () => { const r = section.getBoundingClientRect(); return r.top <= innerHeight * 0.5 && r.bottom >= innerHeight * 0.5; };
  const onKey = (e: KeyboardEvent) => {
    if (opening || !inStage()) return;
    const ae = document.activeElement as HTMLElement | null;
    if (ae && ae !== document.body && !section.contains(ae)) return;
    if (e.key === 'ArrowRight') { e.preventDefault(); step(1); }
    else if (e.key === 'ArrowLeft') { e.preventDefault(); step(-1); }
    else if (e.key === 'Enter' && (!ae || ae === document.body)) { openProject(active); }
  };
  canvas.dataset.cursorLabel = 'Drag';
  canvas.addEventListener('pointerdown', onDown);
  canvas.addEventListener('pointermove', onMove);
  canvas.addEventListener('pointerup', onUp);
  canvas.addEventListener('pointercancel', onCancel);
  canvas.addEventListener('pointerleave', onLeave);
  window.addEventListener('wheel', onWheel, { passive: true });
  window.addEventListener('touchmove', onWheel, { passive: true });
  window.addEventListener('keydown', onKey);
  const onResize = () => { resize(); fitTitle(); };
  window.addEventListener('resize', onResize);
  const linkHandlers = links.map((a, i) => {
    const f = () => { if (!opening) goTo(i); };
    const c = (e: MouseEvent) => { if (e.metaKey || e.ctrlKey || e.shiftKey || opening) return; e.preventDefault(); if (i === active) openProject(i); else goTo(i); };
    a.addEventListener('focus', f); a.addEventListener('click', c);
    return () => { a.removeEventListener('focus', f); a.removeEventListener('click', c); };
  });

  // ---------- frame
  let prev = performance.now();
  const tick = () => {
    const now = performance.now();
    const dt = Math.min((now - prev) / 1000, 0.1) || 0.016; prev = now;
    if (!opening) target = total();
    if (scrollY !== lastY) { lastY = scrollY; lastInput = now; }
    const rc = section.getBoundingClientRect();
    visible = rc.bottom > 0 && rc.top < innerHeight;
    if (!visible) { cur = target; return; }
    // at rest, settle on the nearest project by moving the offset (never the page scroll, so it cannot fight the user's scrolling)
    if (!dragging && !opening && N > 1 && now - lastInput > 180) {
      const r = Math.round(target);
      if (Math.abs(target - r) > 0.003) { offset += r - target; target = r; }
    }
    const before = cur;
    cur += (target - cur) * (1 - Math.exp(-dt * (dragging ? 14 : 7)));
    const v = (cur - before) / dt;
    vel += (v - vel) * 0.2;
    const uVel = clamp(vel * 0.45, -1, 1);
    // The title follows where the carousel is heading (target), the cards follow the eased position (cur): a jump of
    // several projects then swaps the title once, straight to its destination, instead of once per project passed.
    const ti = mod(Math.round(target));
    if (ti !== titleIdx) {
      requestTitle(ti, titleIdx < 0 || wrap(ti - titleIdx) > 0 ? 1 : -1);
      titleIdx = ti;
    }
    const a = mod(Math.round(cur));
    if (a !== active) {
      active = a;
      segs.forEach((s, j) => s.parentElement!.classList.toggle('on', j === a));
    }
    if (phase === 'empty' || (phase === 'hidden' && now - wantAt > SETTLE)) showTitle();
    const R = cardW * 2.6, yOff = yC;
    meshes.forEach((m, i) => {
      const d = wrap(i - cur);
      const u = (m.material as THREE.ShaderMaterial).uniforms;
      m.visible = Math.abs(d) < 3.3;
      if (!m.visible) return;
      const th = d * 0.46;
      let x = R * Math.sin(th), y = yOff, z = R * (Math.cos(th) - 1);
      let ry = -th * 0.85, rx = 0, sx = cardW, sy = cardH;
      const w = Math.max(0, 1 - Math.abs(d));
      ry += ptr.x * 0.12 * w; rx = -ptr.y * 0.08 * w;
      // with few projects a card changes side at the far point of the loop; fade it out there so it does not pop
      let fade = N < 7 ? clamp((N / 2 - Math.abs(d)) * 4, 0, 1) : 1;
      if (opening) {
        if (i === openIdx) {
          const k = open.k;
          x *= 1 - k; y *= 1 - k; z *= 1 - k; ry *= 1 - k; rx *= 1 - k;
          sx = cardW + (vw - cardW) * k; sy = cardH + (vh - cardH) * k;
        } else { x += Math.sign(d || 1) * open.fade * vw * 0.7; fade *= 1 - open.fade; }
      }
      m.position.set(x, y, z); m.rotation.set(rx, ry, 0); m.scale.set(sx, sy, 1);
      m.renderOrder = 10 - Math.abs(d);
      u.uVel.value = opening ? 0 : uVel;
      u.uPlane.value = sx / sy;
      u.uDim.value = Math.min(Math.abs(d), 1);
      u.uFade.value = fade;
    });
    segs.forEach((s, j) => { s.style.transform = `scaleX(${clamp(1 - Math.abs(wrap(cur - j)), 0, 1).toFixed(3)})`; });
    renderer.render(scene, cam);
  };
  gsap.ticker.add(tick);

  // initial position from current scroll (e.g. reload / back / anchor jump)
  target = cur = scrollPos();
  const onRefresh = () => { resize(); fitTitle(); };
  ScrollTrigger.addEventListener('refresh', onRefresh);

  return () => {
    gsap.ticker.remove(tick);
    tw?.kill(); gsap.killTweensOf([open, ui, ...metaLines]);
    split?.revert();
    ScrollTrigger.removeEventListener('refresh', onRefresh);
    st.kill();
    canvas.removeEventListener('pointerdown', onDown);
    canvas.removeEventListener('pointermove', onMove);
    canvas.removeEventListener('pointerup', onUp);
    canvas.removeEventListener('pointercancel', onCancel);
    canvas.removeEventListener('pointerleave', onLeave);
    window.removeEventListener('wheel', onWheel);
    window.removeEventListener('touchmove', onWheel);
    window.removeEventListener('keydown', onKey);
    window.removeEventListener('resize', onResize);
    linkHandlers.forEach((h) => h());
    textures.forEach((t) => t?.dispose());
    blank.dispose(); geo.dispose();
    meshes.forEach((m) => (m.material as THREE.Material).dispose());
    renderer.dispose(); renderer.forceContextLoss();
    delete canvas.dataset.cursorLabel;
    bar.innerHTML = '';
    section.classList.remove('work--gl');
  };
}
