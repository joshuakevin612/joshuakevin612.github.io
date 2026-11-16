# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Joshua Kevin's developer portfolio: a static Astro 5 site whose hero is a scroll-scrubbed 3D film (pre-rendered in Blender, played back as a WebP frame sequence through WebGL), followed by an interactive WebGL project carousel. Motion is the product; treat smoothness and visual polish as requirements, not extras.

## Commands

```bash
npm run dev          # Astro dev server, http://localhost:4321 (also .claude/launch.json "dev")
npm run build        # static build to dist/; also the only automated check (type + content schema errors surface here)
npm run preview      # serve dist/
npm run frames       # after a Blender render: build public/film/mobile + rewrite src/data/film.json
npm run placeholder  # overwrite film frames with 120 generated placeholders (destroys a real render in public/film)
npm run covers       # regenerate abstract placeholder project covers
```

There are no tests and no linter. Verify changes with `npm run build` plus a look in the browser.

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
- `src/scripts/film.ts` maps scroll progress (0–1) over the pinned hero to a frame position.

The beat timing is duplicated on both sides and must be changed together:

| Beat | Frames (`build_scene.py` header/tunables) | Progress (`BEATS` in `film.ts`) |
|---|---|---|
| Workspace wide shot | 1–120 | 0–0.25 |
| Glide to keyboard | 121–200 | 0.25–0.42 |
| JK key launches, world goes black | 201–250 | 0.42–0.52 (no caption) |
| Hero spin | 251–330 | 0.52–0.69 |
| Liquid ripple | 331–400 | 0.69–0.83 |
| Push-in to JK | 401–480 | 0.83–1 |

The page's light-to-dark theme change is tied to the same timeline: `film.ts` interpolates the theme CSS variables across progress 0.44–0.52 (`THEME_A`/`THEME_B`) and flips `data-theme` at the midpoint, matching the frames where the render fades to black. The render uses the Standard view transform so the studio background is exactly `#0B0B0C`, the page's dark background; keep that if lighting is changed.

Typing animation in the film comes from one table (`KEY_EVENTS`), kept that way so a hand rig can be driven from it later. There is deliberately no hand yet.

### Client runtime (`src/scripts/`)

`main.ts` is the single entry and owns lifecycle. The site uses Astro's `ClientRouter`, so every module must initialise on `astro:page-load` and fully tear down on `astro:before-swap` (ScrollTriggers, Lenis, RAF loops, Three.js renderers/textures, listeners via the `disposers` list). A module that leaks breaks back-navigation.

- `film.ts` + `filmgl.ts`: damped playhead (drawn frame eases toward the scroll target and cross-blends neighbouring frames), streaming frame loader around the playhead, captions and theme blend driven by the same damped progress. `filmgl.ts` draws through a Three.js quad with pointer fluid distortion, parallax, grain and vignette; 2D canvas is the fallback.
- `work.ts`: the "Selected work" stage, a curved Three.js carousel driven by page scroll, drag/swipe and arrow keys, with a synced DOM title overlay. A real `<ul>` of project links stays in the DOM for keyboard, no-WebGL and reduced-motion use.
- `open.ts` / `next.ts`: the fill-viewport transition into a project page and the "Next project" footer.

State that depends on scroll (theme, carousel position) is derived from the current scroll offset every frame, not from enter/leave events, so it is correct after reloads mid-page, anchor jumps and back-navigation. Keep new scroll-linked state on that model.

`prefers-reduced-motion` disables Lenis and scrubbing and shows the last film frame as a static poster.

### Content

Projects are one Markdown file each in `src/content/projects/` with the cover image beside it; schema in `src/content.config.ts`, field reference in `README.md`. `order` drives both the carousel order and the wrapping "Next project" chain. `cover` is an optional `image()` (relative path, processed by Astro), `live`/`repo` must be valid URLs. Current projects: Veylith, Clyra (both still TODO text) and Clipfarm (`twitch.md`, real content). `src/pages/projects/[slug].astro` renders them. The carousel must keep working for any project count.

### Design tokens (`src/styles/global.css`)

Light "desk" theme and dark "studio" theme as CSS variables on `<html>`. The only saturated colour anywhere is `--accent` vermilion `#FF4A1C` (also the keycap colour in the render); it is reserved for interactive/active states. No gradients or second accent.

## Known gaps

- Placeholder content: Veylith and Clyra project text, contact email (`hello@example.com`), social links, `site` in `astro.config.mjs`, and a missing `public/og.png`.
- Unverified: touch swipe and real mouse-wheel feel, reduced-motion and no-WebGL fallbacks, small-viewport caption layout over the film.
- Not a git repository yet (`.gitignore` already excludes `node_modules`, `dist`, `.astro`; the ~29 MB of film frames in `public/film` are committed content, not generated at build).
- `README.md` has an encoding glitch in its title line (mojibake dash).
