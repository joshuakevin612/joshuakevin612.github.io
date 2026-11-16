import { defineConfig } from 'astro/config';
// Served by GitHub Pages as a project site, so everything lives under /portfolio.
// With a custom domain, set site to it and remove base.
export default defineConfig({ site: 'https://joshuakevin612.github.io', base: '/portfolio', devToolbar: { enabled: false } });
