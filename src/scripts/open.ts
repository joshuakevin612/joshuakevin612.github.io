import gsap from 'gsap';
import { navigate } from 'astro:transitions/client';

/**
 * Shows a fixed cover image (optionally growing from `from` to the full viewport), tags it with the
 * view-transition-name of the target project's cover, then navigates so the page cover continues from it.
 */
export function fillAndGo(src: string, slug: string, from?: DOMRect | null) {
  const img = document.createElement('img');
  img.src = src;
  img.alt = '';
  img.setAttribute('aria-hidden', 'true');
  Object.assign(img.style, { position: 'fixed', zIndex: '300', objectFit: 'cover', pointerEvents: 'none' });
  img.style.setProperty('view-transition-name', `cover-${slug}`);
  const set = (r: { left: number; top: number; width: number; height: number }) =>
    Object.assign(img.style, { left: r.left + 'px', top: r.top + 'px', width: r.width + 'px', height: r.height + 'px' });
  const full = { left: 0, top: 0, width: innerWidth, height: innerHeight };
  set(from ?? full);
  document.body.appendChild(img);
  const url = `${import.meta.env.BASE_URL.replace(/\/$/, '')}/projects/${slug}/`;
  const go = () => navigate(url).catch(() => { img.remove(); location.assign(url); });
  if (from) {
    gsap.to(img, { left: 0, top: 0, width: innerWidth, height: innerHeight, duration: 0.9, ease: 'power4.inOut', onComplete: go });
  } else {
    img.decode().catch(() => {}).then(() => requestAnimationFrame(go));
  }
}
