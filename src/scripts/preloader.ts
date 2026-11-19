import gsap from 'gsap';

/** The home preloader: a slow 3D starfield behind an orbit ring that fills with real load progress. On finish the stars
 *  go to warp and an iris opens from the centre (the ring riding its edge) onto the first film frame. */
export interface Preloader {
  /** f: 0..1 of everything being loaded; frames: film frames in memory of `total` */
  progress(f: number, frames: number, total: number): void;
  finish(): Promise<void>;
  dispose(): void;
}

const BG = '#0B0B0C';
/** a cached load would otherwise finish before the entrance animation has played */
const MIN_SHOWN = 1.6; // s

export function startPreloader(pre: HTMLElement): Preloader {
  const canvas = pre.querySelector<HTMLCanvasElement>('[data-pre-sky]');
  const countEl = pre.querySelector<HTMLElement>('[data-pre-count]');
  const framesEl = pre.querySelector<HTMLElement>('[data-pre-frames]');
  const arc = pre.querySelector<SVGCircleElement>('[data-pre-arc]');
  const sat = pre.querySelector<HTMLElement>('[data-pre-sat]');
  const core = pre.querySelector<HTMLElement>('[data-pre-core]');
  const mark = pre.querySelector<HTMLElement>('[data-pre-mark]');
  const fades = Array.from(pre.querySelectorAll<HTMLElement>('[data-pre-fade]'));
  const ctx = canvas?.getContext('2d', { alpha: false }) ?? null;
  const born = performance.now();

  const shown = { v: 0 };   // displayed 0..100
  const fx = { speed: 0.05, streak: 0 }; // starfield: depth units per second, extra streak length
  let goal = 0;             // target 0..1 (never 1 until finish)
  let dead = false;

  // ---- starfield
  let W = 0, H = 0, dpr = 1, n = 0, lastAsp = 0;
  let sx = new Float32Array(0), sy = new Float32Array(0), sz = new Float32Array(0), ss = new Float32Array(0), sw = new Float32Array(0);
  const spawn = (i: number, z: number) => {
    // spread to the viewport's own aspect, so a tall phone screen is as full as a wide one
    const m = Math.max(W, H) || 1;
    sx[i] = (Math.random() * 2 - 1) * 1.1 * (W / m); sy[i] = (Math.random() * 2 - 1) * 1.1 * (H / m); sz[i] = z;
    ss[i] = Math.random() < 0.06 ? 1.6 + Math.random() * 0.8 : 0.5 + Math.random() * 0.7;
    sw[i] = Math.random(); // tint: a few cool, a few warm, most white
  };
  const resize = () => {
    if (!canvas) return;
    dpr = Math.min(2, devicePixelRatio || 1);
    W = canvas.clientWidth; H = canvas.clientHeight;
    canvas.width = Math.round(W * dpr); canvas.height = Math.round(H * dpr);
    const want = Math.round(Math.min(900, Math.max(260, (W * H) / 2200)));
    if (want !== n || Math.abs(W / Math.max(1, H) - lastAsp) > 0.05) {
      lastAsp = W / Math.max(1, H);
      n = want;
      sx = new Float32Array(n); sy = new Float32Array(n); sz = new Float32Array(n); ss = new Float32Array(n); sw = new Float32Array(n);
      for (let i = 0; i < n; i++) spawn(i, 0.05 + Math.random() * 0.95);
    }
  };
  resize();
  addEventListener('resize', resize);

  let last = performance.now();
  const tick = () => {
    const now = performance.now();
    const dt = Math.min(0.05, (now - last) / 1000);
    last = now;
    if (!ctx) return;
    const cx = W / 2, cy = H / 2, f = Math.max(W, H) * 0.5;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.globalAlpha = 1;
    ctx.fillStyle = BG;
    ctx.fillRect(0, 0, W, H);
    ctx.lineCap = 'round';
    const dz = fx.speed * dt;
    const tail = 0.0006 + fx.streak; // depth span drawn as a streak behind each star
    for (let i = 0; i < n; i++) {
      let z = sz[i] - dz;
      if (z <= 0.02) { spawn(i, 1); z = 1; }
      sz[i] = z;
      const x = cx + (sx[i] / z) * f, y = cy + (sy[i] / z) * f;
      if (x < -50 || x > W + 50 || y < -50 || y > H + 50) { spawn(i, 0.6 + Math.random() * 0.4); continue; }
      const z2 = Math.min(1.2, z + tail);
      const x2 = cx + (sx[i] / z2) * f, y2 = cy + (sy[i] / z2) * f;
      // fade in from the far plane, brighten as they come close
      const a = Math.min(1, (1 - z) * 1.6) * (0.35 + 0.65 * (1 - z));
      const t = sw[i];
      ctx.strokeStyle = t < 0.12 ? '#C9D6FF' : t > 0.9 ? '#FFE2C4' : '#FFFFFF';
      ctx.globalAlpha = a;
      ctx.lineWidth = Math.min(3.2, ss[i] * (0.6 + 1.1 * (1 - z)));
      ctx.beginPath(); ctx.moveTo(x2, y2); ctx.lineTo(x + 0.01, y); ctx.stroke();
    }
    ctx.globalAlpha = 1;
  };
  gsap.ticker.add(tick);

  // ---- progress readout (ring arc + satellite + count), eased so jumps in load progress never look jumpy
  const draw = () => {
    const v = shown.v;
    if (countEl) countEl.textContent = String(Math.floor(v));
    if (arc) arc.style.strokeDashoffset = String(1 - v / 100);
    if (sat) sat.style.transform = `rotate(${(v / 100) * 360}deg)`;
  };
  draw();
  pre.classList.add('is-live');

  return {
    progress(fr, frames, total) {
      if (dead) return;
      goal = Math.min(0.99, Math.max(goal, fr));
      gsap.to(shown, { v: goal * 100, duration: 0.6, ease: 'power2.out', overwrite: true, onUpdate: draw });
      // the field drifts a little faster as the film fills up
      gsap.to(fx, { speed: 0.05 + goal * 0.1, duration: 0.8, overwrite: 'auto' });
      if (framesEl) framesEl.textContent = `${String(frames).padStart(String(total).length, '0')} / ${total}`;
    },
    finish() {
      return new Promise<void>((res) => {
        if (dead) { res(); return; }
        const iris = { r: 0 };
        const maxR = Math.hypot(innerWidth, innerHeight) / 2 + 4;
        const ringR = (core?.getBoundingClientRect().width ?? 200) * 0.46; // the orbit circle is r=92 of the 200 viewBox
        const setIris = () => {
          const m = `radial-gradient(circle at 50% 50%, transparent ${iris.r.toFixed(1)}px, #000 ${(iris.r + 1.5).toFixed(1)}px)`;
          pre.style.maskImage = m; (pre.style as any).webkitMaskImage = m;
          if (core) {
            const k = Math.max(1, (iris.r + 4) / ringR); // the ring rides just outside the opening
            core.style.setProperty('--k', k.toFixed(4));
            core.style.opacity = String(1 - Math.min(1, Math.max(0, (iris.r - ringR) / (maxR * 0.7))));
          }
        };
        pre.classList.add('is-done');
        gsap.timeline({ onComplete: res, delay: Math.max(0, MIN_SHOWN - (performance.now() - born) / 1000) })
          .to(shown, { v: 100, duration: 0.45, ease: 'power2.out', overwrite: true, onUpdate: draw })
          .to(fades, { opacity: 0, y: -14, duration: 0.5, ease: 'power3.in', stagger: 0.04 }, '+=0.1')
          .to(sat, { opacity: 0, duration: 0.3 }, '<')
          // warp: speed and streak length build, the mark falls away into the field
          .to(fx, { speed: 3.2, streak: 0.09, duration: 1.1, ease: 'power3.in' }, '<')
          .to(mark, { scale: 0.55, opacity: 0, duration: 0.9, ease: 'power3.in' }, '<0.15')
          .to(iris, { r: maxR, duration: 1.15, ease: 'power3.inOut', onUpdate: setIris }, '-=0.35');
      });
    },
    dispose() {
      dead = true;
      gsap.ticker.remove(tick);
      removeEventListener('resize', resize);
      gsap.killTweensOf([shown, fx, mark, sat, ...fades]);
      pre.classList.remove('is-live', 'is-done');
      pre.style.maskImage = ''; (pre.style as any).webkitMaskImage = '';
      [mark, sat, ...fades].forEach((e) => e && gsap.set(e, { clearProps: 'all' }));
      if (core) { core.style.opacity = ''; core.style.removeProperty('--k'); }
    },
  };
}
