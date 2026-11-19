# Joshua Kevin — portfolio

Astro 5 + GSAP (ScrollTrigger, SplitText) + Lenis + Three.js.

## Run

```
npm install
npm run dev        # http://localhost:4321/
npm run build      # static output in dist/
npm run preview
```

Film frames live in `public/film/desktop/f_0001.webp …` (optionally `public/film/mobile/`), described by `src/data/film.json`.
`npm run placeholder` regenerates 120 placeholder frames; `npm run frames` runs the real frame pipeline (`scripts/frames.mjs`).
`npm run covers` regenerates placeholder project covers.

## Adding a project

Create one file: `src/content/projects/<slug>.md` (put the cover image next to it).

| Field | Type | Notes |
| --- | --- | --- |
| title | string | required |
| summary | string | required, one line |
| year | number | required |
| role | string | required |
| stack | string[] | required |
| cover | image path | optional, relative e.g. `./my-app.webp` |
| shot | image path | optional, in-app screenshot shown on the project page; `cover` is then the app's landing page, shown in the carousel |
| live | url | optional |
| repo | url | optional |
| order | number | required, sort order (and "Next project" order, wraps) |

```md
---
title: Orbit
summary: A realtime dashboard for fleet telemetry.
year: 2025
role: Design and development
stack: ["TypeScript", "Astro", "WebGL"]
cover: ./orbit.webp
live: https://orbit.example.com
order: 4
---

Markdown body goes here.
```
