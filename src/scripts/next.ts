import gsap from 'gsap';
import { fillAndGo } from './open';

/** "Next project" footer: cover strip grows with scroll and opens with the fill-viewport transition. */
export function initNext(reduced: boolean, add: (fn: () => void) => void): (() => void) | null {
  const a = document.querySelector<HTMLAnchorElement>('[data-next]');
  const strip = a?.querySelector<HTMLElement>('[data-next-strip]');
  const img = strip?.querySelector<HTMLImageElement>('img');
  if (!a || !strip || !img) return null;
  if (!reduced) {
    add(() => {
      const st = { trigger: a, start: 'top 85%', end: 'top 10%', scrub: true };
      gsap.fromTo(strip, { clipPath: 'inset(0% 34% 0% 34%)' }, { clipPath: 'inset(0% 0% 0% 0%)', ease: 'none', scrollTrigger: st });
      gsap.fromTo(img, { scale: 1.35 }, { scale: 1, ease: 'none', scrollTrigger: st });
    });
  }
  const click = (e: MouseEvent) => {
    if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0 || reduced) return;
    e.preventDefault();
    fillAndGo(img.currentSrc || img.src, a.dataset.slug || '', strip.getBoundingClientRect());
  };
  a.addEventListener('click', click);
  return () => a.removeEventListener('click', click);
}
