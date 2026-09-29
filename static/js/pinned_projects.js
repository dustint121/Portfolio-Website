// Collapsible "Pinned Projects" section on the home page
// (static/partials/pinned_projects.html). Click the header to hide/show
// the project cards; the open/closed state is persisted per-browser via
// localStorage (same pattern as the table-of-contents panel on post
// pages, static/js/toc.js), so it stays how the visitor left it.
document.addEventListener('DOMContentLoaded', () => {
    const section = document.getElementById('pinned-projects');
    if (!section) return;

    const toggle = document.getElementById('pinned-toggle');
    const body = document.getElementById('pinned-body');
    const STORAGE_KEY = 'pinned-projects-collapsed';  // str, localStorage key

    const setCollapsed = (collapsed) => {
        section.classList.toggle('pinned-collapsed', collapsed);
        if (toggle) {
            toggle.setAttribute('aria-expanded', String(!collapsed));
            toggle.title = collapsed ? 'Expand pinned projects' : 'Collapse pinned projects';
        }
        if (body) {
            body.hidden = collapsed;
        }
        try {
            localStorage.setItem(STORAGE_KEY, collapsed ? '1' : '0');
        } catch (e) { /* ignore (e.g. storage disabled) */ }
    };

    // Restore persisted collapse state, if any. bool
    let startCollapsed = false;
    try {
        startCollapsed = localStorage.getItem(STORAGE_KEY) === '1';
    } catch (e) { /* ignore */ }
    setCollapsed(startCollapsed);

    if (toggle) {
        toggle.addEventListener('click', () => {
            setCollapsed(!section.classList.contains('pinned-collapsed'));
        });
    }
});
