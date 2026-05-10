// Light / dark mode toggle with persistence.
document.addEventListener('DOMContentLoaded', () => {
    const root = document.documentElement;
    const themeToggle = document.getElementById('theme-toggle');
    if (!themeToggle) return;

    const setTheme = (theme) => {
        root.setAttribute('data-theme', theme);
        try { localStorage.setItem('theme', theme); } catch (e) { /* ignore */ }
    };

    themeToggle.addEventListener('click', () => {
        const current = root.getAttribute('data-theme') === 'light' ? 'light' : 'dark';
        setTheme(current === 'dark' ? 'light' : 'dark');
    });
});