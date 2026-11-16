import * as THREE from 'three';

export type FrameSource = ImageBitmap | HTMLImageElement;

export interface GLFrameInput {
  a: number; aSrc: FrameSource;       // lower neighbour (index + pixels)
  b: number; bSrc: FrameSource;       // upper neighbour
  mix: number;                        // 0..1 blend from a to b
  fluid: number;                      // 0..1 distortion strength
  liquid: number;                     // 0..1 ambient liquid wobble (liquid beat)
  time: number;                       // seconds
  par: [number, number];              // damped pointer -1..1
  dt: number;
}

export interface FilmGL {
  resize(cssW: number, cssH: number, dpr: number): void;
  splat(x: number, y: number, vx: number, vy: number): void;
  /** true while the fluid trail still has energy and needs rendering */
  readonly active: boolean;
  render(f: GLFrameInput): void;
  dispose(): void;
}

const VERT = 'varying vec2 vUv; void main(){ vUv = uv; gl_Position = vec4(position.xy, 0., 1.); }';

const TRAIL_FRAG = /* glsl */ `
precision highp float;
varying vec2 vUv;
uniform sampler2D uPrev;
uniform vec2 uP0, uP1, uVel, uTexel;
uniform float uRad, uAmt, uDecay, uAspect;
void main(){
  vec2 prev = texture2D(uPrev, vUv).xy;
  vec2 uv = vUv - prev * 0.004;                       // slight self-advection
  vec2 c = texture2D(uPrev, uv).xy;
  vec2 b = (texture2D(uPrev, uv + vec2(uTexel.x, 0.)).xy + texture2D(uPrev, uv - vec2(uTexel.x, 0.)).xy
          + texture2D(uPrev, uv + vec2(0., uTexel.y)).xy + texture2D(uPrev, uv - vec2(0., uTexel.y)).xy) * 0.25;
  vec2 v = mix(c, b, 0.35) * uDecay;                  // diffuse + decay
  vec2 asp = vec2(uAspect, 1.);
  vec2 p = vUv * asp, a = uP0 * asp, e = uP1 * asp, ab = e - a;
  float t = clamp(dot(p - a, ab) / max(dot(ab, ab), 1e-6), 0., 1.);
  float d = length(p - (a + ab * t));
  v += uVel * exp(-(d * d) / (uRad * uRad)) * uAmt;
  gl_FragColor = vec4(clamp(v, -1., 1.), 0., 1.);
}`;

const MAIN_FRAG = (lite: boolean) => /* glsl */ `
precision highp float;
varying vec2 vUv;
uniform sampler2D uA, uB, uTrail;
uniform float uMix, uFluid, uLiquid, uTime, uGrainT, uAspect, uImgAspect;
uniform vec2 uPar;
float hash(vec2 p){ vec3 q = fract(vec3(p.xyx) * .1031); q += dot(q, q.yzx + 33.33); return fract((q.x + q.y) * q.z); }
vec3 film(vec2 c){
  vec2 s = vec2(1.);
  if (uAspect > uImgAspect) s.y = uImgAspect / uAspect; else s.x = uAspect / uImgAspect;
  vec2 t = (c) * s + .5;
  t.y = 1. - t.y;
  return mix(texture2D(uA, t).rgb, texture2D(uB, t).rgb, uMix);
}
void main(){
  vec2 c = vUv - .5;
  c /= 1.035;                                          // overscan so parallax never exposes edges
  c += uPar * vec2(.0055, .004);                       // parallax shift
  c.x += c.y * uPar.x * .010; c.y -= c.x * uPar.y * .006; // slight tilt
  vec2 tv = texture2D(uTrail, vUv).xy;
  vec2 disp = tv * (.035 * uFluid);
  disp += uLiquid * .0035 * vec2(sin(vUv.y * 9. + uTime * .9), cos(vUv.x * 7. - uTime * .8));
  ${lite
    ? 'vec3 col = film(c - disp);'
    : `vec3 col = vec3(film(c - disp * 1.35).r, film(c - disp).g, film(c - disp * .65).b);`}
  vec2 q = (vUv - .5) * vec2(uAspect, 1.);
  col *= 1. - .22 * smoothstep(.35, 1.05, length(q) / (.5 * max(uAspect, 1.)) * .9);   // soft vignette
  float n = hash(gl_FragCoord.xy + uGrainT * vec2(37., 17.)) - .5;
  float l = dot(col, vec3(.299, .587, .114));
  col += n * .05 * (1. - .55 * l);                                                     // fine animated grain
  gl_FragColor = vec4(col, 1.);
}`;

export function createFilmGL(canvas: HTMLCanvasElement, opts: { lite: boolean; imgAspect: number }): FilmGL | null {
  // probe first so a failure never leaves the canvas locked to a broken context
  try {
    const probe = document.createElement('canvas');
    const g = probe.getContext('webgl2');
    if (!g) return null;
    g.getExtension('WEBGL_lose_context')?.loseContext();
  } catch { return null; }

  let renderer: THREE.WebGLRenderer;
  try {
    renderer = new THREE.WebGLRenderer({ canvas, alpha: false, antialias: false, depth: false, stencil: false, powerPreference: opts.lite ? 'low-power' : 'high-performance' });
  } catch { return null; }
  if (!renderer.extensions.has('EXT_color_buffer_float') && !renderer.extensions.has('EXT_color_buffer_half_float')) {
    renderer.dispose();
    return null;
  }
  renderer.autoClear = false;

  const cam = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1);
  const geo = new THREE.PlaneGeometry(2, 2);
  const mkRT = (w: number, h: number) => new THREE.WebGLRenderTarget(w, h, {
    type: THREE.HalfFloatType, minFilter: THREE.LinearFilter, magFilter: THREE.LinearFilter, depthBuffer: false, generateMipmaps: false,
  });
  let rts = [mkRT(4, 4), mkRT(4, 4)];
  let ri = 0;

  const trailMat = new THREE.ShaderMaterial({
    vertexShader: VERT, fragmentShader: TRAIL_FRAG, depthTest: false, depthWrite: false,
    uniforms: {
      uPrev: { value: null }, uP0: { value: new THREE.Vector2() }, uP1: { value: new THREE.Vector2() }, uVel: { value: new THREE.Vector2() },
      uTexel: { value: new THREE.Vector2(1 / 4, 1 / 4) }, uRad: { value: 0.07 }, uAmt: { value: 0 }, uDecay: { value: 0.9 }, uAspect: { value: 1 },
    },
  });
  const mainMat = new THREE.ShaderMaterial({
    vertexShader: VERT, fragmentShader: MAIN_FRAG(opts.lite), depthTest: false, depthWrite: false,
    uniforms: {
      uA: { value: null }, uB: { value: null }, uTrail: { value: rts[0].texture },
      uMix: { value: 0 }, uFluid: { value: 0 }, uLiquid: { value: 0 }, uTime: { value: 0 }, uGrainT: { value: 0 },
      uAspect: { value: 1 }, uImgAspect: { value: opts.imgAspect }, uPar: { value: new THREE.Vector2() },
    },
  });
  const trailScene = new THREE.Scene(); const trailMesh = new THREE.Mesh(geo, trailMat); trailMesh.frustumCulled = false; trailScene.add(trailMesh);
  const mainScene = new THREE.Scene(); const mainMesh = new THREE.Mesh(geo, mainMat); mainMesh.frustumCulled = false; mainScene.add(mainMesh);

  // small texture pool: neighbouring frames keep their GPU texture, so scrubbing never re-uploads what it just drew
  const POOL = 5;
  const pool = new Map<number, { tex: THREE.Texture; used: number }>();
  let tick = 0;
  const texFor = (idx: number, src: FrameSource, keep: number[]) => {
    let e = pool.get(idx);
    if (!e) {
      let tex: THREE.Texture | null = null;
      if (pool.size >= POOL) {
        let oldest = Infinity, key = -1;
        pool.forEach((v, k) => { if (!keep.includes(k) && v.used < oldest) { oldest = v.used; key = k; } });
        if (key >= 0) { tex = pool.get(key)!.tex; pool.delete(key); }
      }
      if (!tex) {
        tex = new THREE.Texture();
        tex.minFilter = THREE.LinearFilter; tex.magFilter = THREE.LinearFilter; tex.generateMipmaps = false;
        tex.flipY = false; tex.premultiplyAlpha = false;
        tex.wrapS = tex.wrapT = THREE.ClampToEdgeWrapping;
      }
      tex.image = src as any;
      tex.needsUpdate = true;
      e = { tex, used: 0 };
      pool.set(idx, e);
    }
    e.used = ++tick;
    return e.tex;
  };

  // trail state
  let aspect = 1;
  let energy = 0;
  let pend: { x0: number; y0: number; x1: number; y1: number; vx: number; vy: number } | null = null;
  let lastX = -1, lastY = -1;
  const GAIN = 1;

  const resize = (w: number, h: number, dpr: number) => {
    renderer.setPixelRatio(dpr);
    renderer.setSize(w, h, false);
    aspect = w / Math.max(1, h);
    const long = opts.lite ? 128 : 256;
    const tw = aspect >= 1 ? long : Math.round(long * aspect);
    const th = aspect >= 1 ? Math.round(long / aspect) : long;
    rts.forEach((r) => r.setSize(tw, th));
    trailMat.uniforms.uTexel.value.set(1 / tw, 1 / th);
    trailMat.uniforms.uAspect.value = aspect;
    mainMat.uniforms.uAspect.value = aspect;
    [0, 1].forEach((i) => { renderer.setRenderTarget(rts[i]); renderer.setClearColor(0x000000, 1); renderer.clear(); });
    renderer.setRenderTarget(null);
    energy = 0;
  };

  const self: FilmGL = {
    resize,
    splat(x, y, vx, vy) {
      if (lastX < 0) { lastX = x; lastY = y; }
      if (pend) { pend.x1 = x; pend.y1 = y; pend.vx += vx * GAIN; pend.vy += vy * GAIN; }
      else pend = { x0: lastX, y0: lastY, x1: x, y1: y, vx: vx * GAIN, vy: vy * GAIN };
      lastX = x; lastY = y;
      energy = Math.max(energy, Math.min(1, Math.hypot(vx, vy) * 4));
    },
    get active() { return energy > 0.002 || !!pend; },
    render(f) {
      // 1) velocity trail
      if (self.active) {
        const u = trailMat.uniforms;
        const src = rts[ri], dst = rts[1 - ri];
        u.uPrev.value = src.texture;
        u.uDecay.value = Math.exp(-f.dt * 2.4);
        if (pend) {
          const mag = Math.hypot(pend.vx, pend.vy);
          const k = mag > 0.5 ? 0.5 / mag : 1;
          u.uP0.value.set(pend.x0, pend.y0); u.uP1.value.set(pend.x1, pend.y1);
          u.uVel.value.set(pend.vx * k, pend.vy * k);
          u.uAmt.value = 0.55;
          pend = null;
        } else u.uAmt.value = 0;
        renderer.setRenderTarget(dst);
        renderer.render(trailScene, cam);
        renderer.setRenderTarget(null);
        ri = 1 - ri;
        energy *= Math.exp(-f.dt * 1.5);
        if (energy < 0.002) energy = 0;
      }
      // 2) composited film frame
      const m = mainMat.uniforms;
      m.uA.value = texFor(f.a, f.aSrc, [f.a, f.b]);
      m.uB.value = texFor(f.b, f.bSrc, [f.a, f.b]);
      m.uTrail.value = rts[ri].texture;
      m.uMix.value = f.mix; m.uFluid.value = f.fluid; m.uLiquid.value = f.liquid;
      m.uTime.value = f.time; m.uGrainT.value = Math.floor(f.time * 24) % 997;
      m.uPar.value.set(f.par[0], f.par[1]);
      renderer.render(mainScene, cam);
    },
    dispose() {
      pool.forEach((e) => e.tex.dispose()); pool.clear();
      rts.forEach((r) => r.dispose());
      geo.dispose(); trailMat.dispose(); mainMat.dispose();
      renderer.dispose();
      renderer.forceContextLoss();
    },
  };
  return self;
}
