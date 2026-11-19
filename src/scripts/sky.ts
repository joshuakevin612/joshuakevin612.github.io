import gsap from 'gsap';

/** A clean night sky behind the page: a fixed canvas under all content (see `.sky` in global.css), shown only while the
 *  dark theme is on. Stars sit in three depth layers that drift gently with scroll, twinkle, and now and then a meteor
 *  crosses. It only draws while some of it can be seen (not under the pinned film, not in the light theme). */
export function initSky(reduced: boolean): (() => void) | null {
  const canvas = document.querySelector<HTMLCanvasElement>('[data-sky]');
  const ctx = canvas?.getContext('2d');
  if (!canvas || !ctx) return null;
  const html = document.documentElement;
  const hero = document.querySelector<HTMLElement>('[data-film]');

  // deterministic field so the sky looks the same on every visit and resize
  let seed = 1337;
  const rnd = () => { seed = (seed * 16807) % 2147483647; return (seed - 1) / 2147483646; };
  let W = 0, H = 0, dpr = 1, n = 0;
  let x = new Float32Array(0), y = new Float32Array(0), r = new Float32Array(0), a = new Float32Array(0);
  let sp = new Float32Array(0), ph = new Float32Array(0), dp = new Float32Array(0), tw = new Float32Array(0);
  let tint = new Uint8Array(0);
  const COLS = ['#FFFFFF', '#CFDBFF', '#FFE6CC'];

  // soft glow sprite for the few bright stars
  const glow = document.createElement('canvas');
  glow.width = glow.height = 64;
  { const g = glow.getContext('2d')!; const grd = g.createRadialGradient(32, 32, 0, 32, 32, 32);
    grd.addColorStop(0, 'rgba(255,255,255,.9)'); grd.addColorStop(.18, 'rgba(255,255,255,.28)'); grd.addColorStop(1, 'rgba(255,255,255,0)');
    g.fillStyle = grd; g.fillRect(0, 0, 64, 64); }

  const build = () => {
    seed = 1337;
    n = Math.round(Math.min(1100, Math.max(220, (W * H) / 2100)));
    x = new Float32Array(n); y = new Float32Array(n); r = new Float32Array(n); a = new Float32Array(n);
    sp = new Float32Array(n); ph = new Float32Array(n); dp = new Float32Array(n); tw = new Float32Array(n); tint = new Uint8Array(n);
    for (let i = 0; i < n; i++) {
      x[i] = rnd(); y[i] = rnd();
      const k = rnd();
      // mostly faint pinpricks, a handful of bright ones
      r[i] = k > 0.985 ? 1.5 + rnd() * 0.7 : k > 0.9 ? 0.95 + rnd() * 0.4 : 0.45 + rnd() * 0.45;
      a[i] = k > 0.985 ? 1 : k > 0.9 ? 0.75 + rnd() * 0.25 : 0.25 + rnd() * 0.45;
      dp[i] = k > 0.9 ? 0.6 + rnd() * 0.4 : 0.15 + rnd() * 0.5;
      sp[i] = 0.4 + rnd() * 1.8; ph[i] = rnd() * Math.PI * 2;
      tw[i] = rnd() < 0.35 ? 0.35 + rnd() * 0.45 : 0.08 + rnd() * 0.12;
      const c = rnd(); tint[i] = c < 0.12 ? 1 : c > 0.92 ? 2 : 0;
    }
  };
  const resize = () => {
    dpr = Math.min(2, devicePixelRatio || 1);
    const w = innerWidth, h = innerHeight;
    if (w === W && Math.abs(h - H) < 120 && n) { H = h; canvas.height = Math.round(h * dpr); dirty = true; return; } // mobile URL bar
    W = w; H = h;
    canvas.width = Math.round(W * dpr); canvas.height = Math.round(H * dpr);
    build();
    dirty = true;
  };
  let dirty = true;

  // meteors
  let met: { x: number; y: number; vx: number; vy: number; t: number; life: number } | null = null;
  let nextMet = performance.now() + 4000 + Math.random() * 6000;

  const visible = () => {
    if (html.dataset.theme !== 'dark') return false;
    if (hero) { const b = hero.getBoundingClientRect().bottom; if (b >= innerHeight - 1) return false; } // pinned film covers the screen
    return true;
  };

  const t0 = performance.now();
  let lastScroll = -1;
  const draw = (now: number) => {
    const t = (now - t0) / 1000;
    const sc = scrollY;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, W, H);
    for (let i = 0; i < n; i++) {
      // parallax: nearer stars drift further per scrolled pixel; wrap vertically
      let py = (y[i] * H - sc * dp[i] * 0.06) % H; if (py < 0) py += H;
      const px = x[i] * W;
      const al = reduced ? a[i] : a[i] * (1 - tw[i] * (0.5 + 0.5 * Math.sin(t * sp[i] + ph[i])));
      ctx.globalAlpha = al;
      if (r[i] > 1.4) {
        const s = r[i] * 7;
        ctx.drawImage(glow, px - s, py - s, s * 2, s * 2);
      }
      ctx.fillStyle = COLS[tint[i]];
      ctx.beginPath(); ctx.arc(px, py, r[i], 0, Math.PI * 2); ctx.fill();
    }
    if (met) {
      const m = met, k = m.t / m.life;
      const fade = Math.sin(Math.PI * Math.min(1, k));
      const hx = m.x + m.vx * m.t, hy = m.y + m.vy * m.t;
      const len = 140, nx = m.vx / Math.hypot(m.vx, m.vy), ny = m.vy / Math.hypot(m.vx, m.vy);
      const g = ctx.createLinearGradient(hx, hy, hx - nx * len, hy - ny * len);
      g.addColorStop(0, 'rgba(255,255,255,.9)'); g.addColorStop(1, 'rgba(255,255,255,0)');
      ctx.globalAlpha = fade; ctx.strokeStyle = g; ctx.lineWidth = 1.2; ctx.lineCap = 'round';
      ctx.beginPath(); ctx.moveTo(hx, hy); ctx.lineTo(hx - nx * len, hy - ny * len); ctx.stroke();
    }
    ctx.globalAlpha = 1;
    lastScroll = sc;
  };

  let last = performance.now();
  const tick = () => {
    const now = performance.now();
    const dt = Math.min(0.05, (now - last) / 1000);
    last = now;
    if (!visible()) { met = null; return; }
    if (!reduced) {
      if (!met && now > nextMet) {
        const dir = Math.random() < 0.5 ? -1 : 1;
        met = { x: W * (0.2 + Math.random() * 0.6), y: H * Math.random() * 0.4, vx: dir * (500 + Math.random() * 300), vy: 220 + Math.random() * 160, t: 0, life: 0.7 + Math.random() * 0.4 };
      }
      if (met) { met.t += dt; if (met.t > met.life) { met = null; nextMet = now + 7000 + Math.random() * 9000; } }
      draw(now);
    } else if (dirty || scrollY !== lastScroll) { dirty = false; draw(now); }
  };

  resize();
  addEventListener('resize', resize);
  gsap.ticker.add(tick);
  return () => {
    gsap.ticker.remove(tick);
    removeEventListener('resize', resize);
    ctx.clearRect(0, 0, canvas.width, canvas.height);
  };
}
