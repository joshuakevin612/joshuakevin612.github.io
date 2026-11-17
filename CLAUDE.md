# CLAUDE.md

## What this is

Joshua Kevin's developer portfolio: a static Astro 5 site whose hero is a scroll-scrubbed 3D film (pre-rendered in Blender, played back as a WebP frame sequence through WebGL), followed by an interactive WebGL project carousel. Motion is the product; treat smoothness and visual polish as requirements, not extras.

## Commands

```bash
npm run dev          # Astro dev server, http://localhost:4321/portfolio/ (also .claude/launch.json "dev")
npm run build        # static build to dist/; content schema and .astro errors surface here
npx tsc --noEmit     # type-checks src/scripts (the build does not)
npm run preview      # serve dist/
npm run frames       # after a Blender render: build public/film/mobile + rewrite src/data/film.json
npm run placeholder  # overwrite film frames with 120 generated placeholders (destroys a real render in public/film)
npm run covers       # abstract placeholder cover for any project that has none; never overwrites an existing image
```

There are no tests and no linter. Verify changes with `npm run build` plus a look in the browser at phone, tablet and desktop widths.

- `npx tsc --noEmit` currently reports one known error in `work.ts` (the raycast `meshes.indexOf(h.object as THREE.Mesh)` cast); anything else is new.
- The dev server caches the content collection. After adding, removing or reordering project files, restart it before trusting what the carousel shows.
- Everything animated runs off `requestAnimationFrame`. A hidden or background tab throttles it, so screenshots from a preview pane that is not on screen show half-finished transitions and a stuck preloader; that is not a bug in the site.

Film render (Blender 5.3 is installed but not on PATH: `C:\Program Files\Blender Foundation\Blender 5.3\blender.exe`):

```bash
blender -b -P blender/build_scene.py -- --preview            # EEVEE, all 480 frames, ~1 h
blender -b -P blender/build_scene.py -- --final              # Cycles GPU, ~2 h
blender -b -P blender/build_scene.py -- --final --list 1,60,160 --out <dir>   # stills for look checks
blender -b -P blender/build_scene.py -- --final --frames 200 250 --out <dir>  # a range
```

Default output is `public/film/desktop/`. Render to a staging dir with `--out`, inspect stills, then swap the full set in and run `npm run frames`. Keep staging dirs outside `public/` so they are not shipped.

## Architecture

### One film, two halves, one contract

- `blender/build_scene.py` builds the whole scene procedurally (no external assets) and renders `f_0001.webp … f_0480.webp`.
- `scripts/frames.mjs` derives the mobile set and writes `src/data/film.json` (`count`, `desktop`/`mobile` sizes). Site code must read count and sizes from that file, never hard-code them.
- `src/scripts/film.ts` maps scroll progress over the pinned hero to a frame position. The film completes at `FILM_END` (0.86) of the pin and holds on the last frame for the rest, so the damped playhead lands before the hero scrolls away (the owner reported scrolling past mid push-in). Progress values below are film progress, after that mapping.

The beat timing is duplicated on both sides and must be changed together:

| Beat | Frames (`build_scene.py` header/tunables) | Progress (`BEATS` in `film.ts`) |
|---|---|---|
| Workspace wide shot: camera static to frame 100 while morning turns to night (sunset 12–80), then starts moving | 1–120 | 0–0.25 |
| Glide to keyboard | 121–200 | 0.25–0.42 |
| JK key launches, world goes black | 201–250 | 0.42–0.52 (no caption) |
| Hero spin | 251–330 | 0.52–0.69 |
| Liquid ripple | 331–400 | 0.69–0.83 |
| Push-in to JK | 401–480 | 0.83–1 |

The page's light-to-dark theme change is tied to the same timeline: `film.ts` interpolates the theme CSS variables across progress 0.075–0.115 (`THEME_A`/`THEME_B`) and flips `data-theme` at the midpoint, matching the frames where the sun goes down in the render (kept short: mid-blend text is hard to read). The rig's RGB is a full hue wheel (owner's choice, the one exception to the vermilion-only rule; the JK keycap stays vermilion), driven per frame from one function so frames render independently. The render uses the Standard view transform so the studio background is exactly `#0B0B0C`, the page's dark background; keep that if lighting is changed.

Typing animation comes from one table (`KEY_EVENTS`) so a hand rig can be driven from it later; there is deliberately no hand yet.

### Client runtime (`src/scripts/`)

`main.ts` is the single entry and owns lifecycle. After every `await`, `init()` checks its `gen` counter and bails if the page was swapped meanwhile. The site uses Astro's `ClientRouter`, so every module must initialise on `astro:page-load` and fully tear down on `astro:before-swap` (ScrollTriggers, Lenis, RAF loops, Three.js renderers/textures, listeners via the `disposers` list). A module that leaks breaks back-navigation.

- `film.ts` + `filmgl.ts`: the bar for scrubbing is "as smooth as oryzo.ai". Every frame is fetched up front as a Blob and kept in memory; full bitmaps are decoded only in a sliding window round the playhead, with small permanent proxies of every 8th frame as the fallback. The playhead is one critically damped spring (`PLAYHEAD_T95`) that cross-blends neighbouring frames while moving and glides onto a whole frame at rest (a resting cross-blend is a visible double image). Lenis `lerp` is deliberately light (0.25) because the spring supplies the glide. Dev builds expose `window.__film.stats`. Captions and the theme blend are driven by the same damped progress. `filmgl.ts` draws through a Three.js quad with pointer fluid distortion, parallax, grain and vignette; 2D canvas is the fallback.
- `work.ts`: the "Selected work" stage, a curved, looping Three.js carousel with a synced DOM overlay (title, count, meta, progress bar). A real `<ul>` of project links stays in the DOM for keyboard, no-WebGL and reduced-motion use. See below.
- `open.ts` / `next.ts`: the fill-viewport transition into a project page and the "Next project" footer.

State that depends on scroll (theme, carousel position) is derived from the current scroll offset every frame, not from enter/leave events, so it is correct after reloads mid-page, anchor jumps and back-navigation. Keep new scroll-linked state on that model.

`prefers-reduced-motion` disables Lenis and scrubbing and shows the last film frame as a static poster.

The home preloader is switched on by an inline head script in `Layout.astro` (first load only, so no-JS visitors never get a stuck loading screen). It counts failed frames as done and gives up after `PRELOAD_TIMEOUT`.

### The carousel (`work.ts`)

- **Position** is `scrollPos() + offset`. `scrollPos()` is the page scroll through the pinned stage (0 to N−1, re-read every frame); `offset` is moved by drag/swipe, arrow keys, clicking a side card and the resting snap. `work.ts` never scrolls the page.
- **Looping** is done in the render, not the data: every per-card distance goes through `wrap()` (shortest signed distance round the loop), and indices through `mod()`. Positions are unbounded floats.
- **Two indices on purpose.** Cards, the progress bar and click-to-open use `active`, from the eased position `cur`. The title, count and meta use `titleIdx`, from the un-eased `target`, so they head straight for the destination.
- **Title swaps are coalesced** (`requestTitle` / `hideTitle` / `showTitle`, the `phase` state). A change hides the title once; the new one is built only after the destination has been stable for `SETTLE` ms. Do not go back to swapping on every index change (visible stutter).
- **Layout is anchored to the title's font size** (`resize`). The card stops just above the title, so light covers never sit behind white title text. Long titles are therefore fitted with a `transform: scale` (`fitTitle`), not a font-size change. Portrait viewports get a wide 5:4 card so 16:10 covers are not cropped to a sliver.
- Textures are uploaded with `renderer.initTexture` when they load, so a card's first visible frame does not hitch.
- It must keep working for any project count, including 1 and 2.

### Content

One Markdown file per project in `src/content/projects/`, images beside it. Schema in `src/content.config.ts`, field reference in `README.md`. `order` drives both the carousel order and the wrapping "Next project" chain. `live`/`repo` must be valid URLs.

Each project has up to two 1600×1000 images:

- `cover` → `<slug>-hero.webp`: what the carousel, the "Next project" strip and the OG image use. It is the app's own landing page where one exists, otherwise generated title art (abstract geometry in the site's token colours plus the project name, centred so it survives cropping).
- `shot` → `<slug>.webp`: an in-app screenshot shown on the project page (`[slug].astro` uses `shot ?? cover`). The open transition cross-fades the cover into it, because both carry the same view-transition name.

Which projects get title art instead of a landing-page capture is the owner's decision, not a judgement call: currently Clipfarm, NeuroVasc-X, DevHub, OS Simulators, Marine Debris and Veylith. Clipfarm deliberately has no `shot` (its real output shows other people's faces). Title art was rendered ad hoc in headless Chrome (no generator in the repo; `npm run covers` makes only title-less placeholders).

There are thirteen projects, each written from its GitHub repo under `github.com/joshuakevin612`. Clipfarm lives in `twitch.md`; `os-simulators.md` covers three small repos in one entry and embeds two extra screenshots in its body. Project copy must only claim what the repo backs up (Veylith is described as an unfinished scaffold because it is one). Roles were stated by the owner; projects marked "Solo developer" are ones whose repo has a single contributor.

Project page titles are split by word then character in `main.ts` and shrunk until the longest word fits, so they wrap only between words on narrow screens.

### Scroll length and the About page

How far the visitor scrolls before the contact section is set by two CSS heights in `global.css`: `.hero` (400vh, the film) and `.work--gl` (one screen plus 30svh per further project, capped at `WORK_SCROLL_CAP` = 5 in `index.astro`; page scroll walks only that many projects, the rest are reached by drag, arrow keys and clicks). The owner had these shortened; do not lengthen them without asking.

The home contact section's "Let's talk" links to `src/pages/about.astro` (bio, stack, email, phone, GitHub, LinkedIn) rather than a `mailto:`. That page reuses the `.proj` article classes, so it gets the project-page title split and nav backing. The bio must only claim what the owner has stated.

### Design tokens (`src/styles/global.css`)

Light "desk" theme and dark "studio" theme as CSS variables on `<html>`. The only saturated colour anywhere is `--accent` vermilion `#FF4A1C` (also the keycap colour in the render); it is reserved for interactive/active states. No gradients or second accent. The fixed nav is transparent over the home film and gets a blurred backing bar only on project pages, where long text scrolls beneath it.

## Deploy

Deployed by `.github/workflows/deploy.yml` to GitHub Pages on every push to `main`, at `https://joshuakevin612.github.io/portfolio/`. The site therefore lives under `base: '/portfolio'`: never write a root-absolute path (`/film/...`, `/projects/...`, `/#work`); prefix with `import.meta.env.BASE_URL` as the existing links do. Internal project links end in `/` so Pages does not redirect mid-transition.

## Known gaps

- Unverified on real hardware: touch swipe, mouse-wheel feel and carousel smoothness on a real GPU (checks so far were emulated viewports in headless Chrome), plus the reduced-motion and no-WebGL fallbacks and the small-viewport caption layout over the film.
- The ~29 MB of film frames in `public/film` are committed content, not generated at build. `public/og.png` is a crop of the film's last frame.
