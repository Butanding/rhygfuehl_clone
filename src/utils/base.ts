// Prefixes root-relative paths with Astro's `base`, so the site also works
// when served from a sub-path (e.g. GitHub Pages project sites).
export const withBase = (path: string) =>
	import.meta.env.BASE_URL.replace(/\/$/, '') + path;

// Set PUBLIC_IS_CLONE=true for test deployments: disables analytics and indexing.
export const isClone = import.meta.env.PUBLIC_IS_CLONE === 'true';
