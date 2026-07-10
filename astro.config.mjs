import { defineConfig } from 'astro/config';
import tailwindcss from '@tailwindcss/vite';
import AstroPWA from '@vite-pwa/astro';
import icon from 'astro-icon';

export default defineConfig({
  integrations: [
    icon(),
    AstroPWA({
      registerType: 'autoUpdate',
      manifest: {
        name: 'rhygfuehl',
        short_name: 'rhygfuehl',
        description: '☀️ current Rhine temperature in Basel',
        theme_color: '#002855',
        background_color: '#002855',
        display: 'standalone',
        icons: [
          {
            src: '/pwa-192x192.png',
            sizes: '192x192',
            type: 'image/png',
          },
          {
            src: '/pwa-512x512.png',
            sizes: '512x512',
            type: 'image/png',
          },
          {
            src: '/maskable-icon-512x512.png',
            sizes: '512x512',
            type: 'image/png',
            purpose: 'maskable',
          },
        ],
      },
      workbox: {
        cleanupOutdatedCaches: true,
        globPatterns: ['**/*.{js,css,svg,png,jpg,jpeg,gif,webp,woff,woff2,ttf,eot,ico,webmanifest}'],
        navigateFallback: null,
        runtimeCaching: [
          {
            urlPattern: ({ request }) => request.mode === 'navigate',
            handler: 'NetworkFirst',
            options: {
              cacheName: 'pages-cache',
              expiration: {
                maxEntries: 10,
                maxAgeSeconds: 60 * 60 * 24, // 24 hours
              },
            },
          },
          {
            urlPattern: /^https:\/\/data\.bs\.ch\/api\/.*$/,
            handler: 'NetworkFirst',
            options: {
              cacheName: 'api-cache',
              expiration: {
                maxEntries: 10,
                maxAgeSeconds: 60 * 60, // 1 hour
              },
            },
          },
        ],
      },
      devOptions: {
        enabled: true,
        type: 'module',
      },
    }),
  ],
  vite: {
    plugins: [tailwindcss()],
  },
  output: 'static',
});
