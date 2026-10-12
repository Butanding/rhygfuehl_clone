// Colours of the charts. The page follows the browser's light/dark setting
// (Tailwind's default `dark:` variant = prefers-color-scheme), so the charts have to
// follow it as well. The `dark` class on <html> is always set and says nothing about it.
const DARK_QUERY = '(prefers-color-scheme: dark)';

export const isDarkMode = () => window.matchMedia(DARK_QUERY).matches;

export const getChartColors = () => {
	const dark = isDarkMode();
	return {
		line: dark ? '#FFFFFF' : '#002855',
		text: dark ? 'rgba(255, 255, 255, 0.75)' : '#002855',
		grid: dark ? 'rgba(255, 255, 255, 0.15)' : 'rgba(0, 40, 85, 0.15)',
		// bars: clearly visible on both the dark blue and the light grey card
		rain: dark ? '#5AB0FF' : '#1B6FD6',
		radiation: dark ? '#FFC247' : '#E07B00'
	};
};

export const onThemeChange = (callback: () => void) =>
	window.matchMedia(DARK_QUERY).addEventListener('change', callback);
