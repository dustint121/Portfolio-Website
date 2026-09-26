// Collapsible "Contents" panel for post pages (static/partials/toc.html).
// Two independent behaviors:
//   1. Collapse/expand toggle -- click the "Contents" header to hide/show
//      the heading list, persisted per-browser via localStorage so it
//      stays collapsed across page loads if the user closed it.
//   2. Active-heading tracking -- as the reader scrolls through the post,
//      whichever heading is currently at/above the top of the viewport
//      gets highlighted in the list (IntersectionObserver-based, no
//      scroll-event polling).
document.addEventListener('DOMContentLoaded', () => {
    const panel = document.getElementById('toc-panel');
    if (!panel) return;

    const toggle = document.getElementById('toc-toggle');
    const scrollEl = document.getElementById('toc-scroll');
    const STORAGE_KEY = 'toc-collapsed';  // str, localStorage key

    const setCollapsed = (collapsed) => {
        panel.classList.toggle('toc-collapsed', collapsed);
        if (toggle) {
            toggle.setAttribute('aria-expanded', String(!collapsed));
            toggle.title = collapsed ? 'Expand table of contents' : 'Collapse table of contents';
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
            setCollapsed(!panel.classList.contains('toc-collapsed'));
        });
    }

    // Smooth-scroll to the target heading on click instead of a hard jump,
    // and update the URL hash without adding a new history entry per click.
    const links = Array.from(panel.querySelectorAll('.toc-link'));
    links.forEach((link) => {
        link.addEventListener('click', (evt) => {
            const id = link.dataset.tocId;  // str
            const target = id ? document.getElementById(id) : null;
            if (!target) return;
            evt.preventDefault();
            target.scrollIntoView({ behavior: 'smooth', block: 'start' });
            if (history.replaceState) {
                history.replaceState(null, '', '#' + id);
            }
        });
    });

    // Active-heading tracking via IntersectionObserver: watch every
    // heading element the TOC links to, and mark whichever one is
    // closest to (and above) the top of the viewport as active.
    const headingEls = links
        .map((link) => document.getElementById(link.dataset.tocId))
        .filter(Boolean);  // list of Element
    if (headingEls.length === 0) return;

    const linkById = {};  // dict str id -> Element (the <a>)
    links.forEach((link) => { linkById[link.dataset.tocId] = link; });

    const setActive = (id) => {
        links.forEach((link) => {
            link.classList.toggle('toc-active', link.dataset.tocId === id);
        });
        // Keep the active link scrolled into view within the (possibly
        // shorter-than-the-list) scrollable panel.
        const activeLink = id ? linkById[id] : null;
        if (activeLink && scrollEl) {
            const linkTop = activeLink.offsetTop;  // int, relative to toc-scroll
            const linkBottom = linkTop + activeLink.offsetHeight;
            if (linkTop < scrollEl.scrollTop) {
                scrollEl.scrollTop = linkTop;
            } else if (linkBottom > scrollEl.scrollTop + scrollEl.clientHeight) {
                scrollEl.scrollTop = linkBottom - scrollEl.clientHeight;
            }
        }
    };

    // Headings currently intersecting the "activation band" near the top
    // of the viewport, tracked by id. Set of str.
    const visibleIds = new Set();

    const observer = new IntersectionObserver((entries) => {
        entries.forEach((entry) => {
            if (entry.isIntersecting) {
                visibleIds.add(entry.target.id);
            } else {
                visibleIds.delete(entry.target.id);
            }
        });

        if (visibleIds.size > 0) {
            // Multiple headings can be in the band at once (short
            // sections); prefer the one that appears first in document
            // order among the currently-visible set.
            const firstVisible = headingEls.find((el) => visibleIds.has(el.id));
            if (firstVisible) setActive(firstVisible.id);
        } else {
            // Nothing is in the band -- we're either above the first
            // heading or between two headings after scrolling past one;
            // fall back to the last heading whose top has already
            // scrolled above the band.
            let lastPassed = null;
            for (const el of headingEls) {
                if (el.getBoundingClientRect().top <= 96) {
                    lastPassed = el;
                } else {
                    break;
                }
            }
            setActive(lastPassed ? lastPassed.id : null);
        }
    }, {
        // Activation band: top 96px (below the sticky topbar) down to
        // 70% of the viewport height, so a heading counts as "active"
        // once it's near the top rather than only when fully in view.
        rootMargin: '-96px 0px -70% 0px',
        threshold: 0,
    });

    headingEls.forEach((el) => observer.observe(el));
});
