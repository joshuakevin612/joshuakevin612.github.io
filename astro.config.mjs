import { defineConfig } from 'astro/config';
import sitemap from '@astrojs/sitemap';
// Served by GitHub Pages as the user site (joshuakevin612.github.io), so everything lives at the root.
// With a custom domain, just change site.
export default defineConfig({
  site: 'https://joshuakevin612.github.io',
  trailingSlash: 'always',
  integrations: [sitemap({ filter: (page) => !page.endsWith('/404/') })],
  devToolbar: { enabled: false },
});
