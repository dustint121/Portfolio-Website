// Client-side search + tag filter for post-card lists (home/section pages).
// Filters ".card-link" elements already in the DOM against:
//   - free-text query, matched against either data-title (title-only mode)
//     or data-search-text (title + summary + body), depending on the
//     "Title only" toggle button's state
//   - a set of active tags (toggled via .tag-chip buttons inside the
//     collapsible <details> tag list), matched against data-tags -- a post
//     must have ALL active tags to stay visible (AND logic)
// The text filter and tag filter are combined with AND: a card must satisfy
// both to show.
document.addEventListener('DOMContentLoaded', () => {
    const root = document.querySelector('[data-search-root="true"]');
    const cardList = document.getElementById('card-list');
    if (!root || !cardList) return;

    const input = document.getElementById('search-input');
    const clearBtn = document.getElementById('search-clear');
    const emptyState = document.getElementById('search-empty-state');
    const introCount = document.getElementById('intro-count');
    const titleOnlyToggle = document.getElementById('title-only-toggle');
    const tagFilterCount = document.getElementById('tag-filter-count');
    const tagChips = Array.from(root.querySelectorAll('.tag-chip'));
    const cards = Array.from(cardList.querySelectorAll('.card-link'));
    // Pagination nav sits right after the card list and only makes sense
    // for the full, unfiltered page -- it is server-rendered from ALL posts,
    // not just the ones currently loaded in the DOM, so it can't reflect a
    // client-side filter. Hide it while a filter is active, restore it when
    // the filter is cleared. May be null on a page with a single pagination
    // page (partial renders nothing) -- guarded below.
    const paginationNav = cardList.parentElement
        ? cardList.parentElement.querySelector('.pagination')
        : null;

    // Set of currently active (selected) tag names, lowercase. Set of str.
    const activeTags = new Set();
    // Whether the free-text query should only match the title. bool.
    let titleOnly = false;

    const updateTagFilterCount = () => {
        if (!tagFilterCount) return;
        if (activeTags.size > 0) {
            tagFilterCount.textContent = String(activeTags.size);
            tagFilterCount.hidden = false;
        } else {
            tagFilterCount.hidden = true;
        }
    };

    const applyFilters = () => {
        const query = (input.value || '').trim().toLowerCase();  // str
        let visibleCount = 0;  // int

        cards.forEach((card) => {
            const haystack = titleOnly
                ? (card.dataset.title || '')
                : (card.dataset.searchText || '');  // str
            const cardTags = (card.dataset.tags || '').split(',')      // list of str
                .map((t) => t.trim())
                .filter(Boolean);

            const matchesText = query === '' || haystack.includes(query);
            const matchesTags = activeTags.size === 0 ||
                Array.from(activeTags).every((tag) => cardTags.includes(tag));

            const visible = matchesText && matchesTags;
            card.hidden = !visible;
            if (visible) visibleCount += 1;
        });

        const filterActive = query !== '' || activeTags.size > 0;  // bool

        emptyState.hidden = visibleCount !== 0;
        clearBtn.hidden = !filterActive;

        // Pagination reflects the server-side, unfiltered full post list --
        // it can't account for a client-side filter that only touches the
        // current page's cards, so hide it while filtering and bring it back
        // once the filter clears.
        if (paginationNav) {
            paginationNav.hidden = filterActive;
        }

        if (introCount) {
            const label = visibleCount === 1 ? 'post' : 'posts';
            introCount.textContent = filterActive
                ? `${visibleCount} ${label} on this page`
                : `${visibleCount} ${label}`;
        }
    };

    input.addEventListener('input', applyFilters);

    if (titleOnlyToggle) {
        titleOnlyToggle.addEventListener('click', () => {
            titleOnly = !titleOnly;
            titleOnlyToggle.classList.toggle('active', titleOnly);
            titleOnlyToggle.setAttribute('aria-pressed', String(titleOnly));
            applyFilters();
        });
    }

    tagChips.forEach((chip) => {
        chip.addEventListener('click', () => {
            const tag = chip.dataset.tag;  // str
            if (activeTags.has(tag)) {
                activeTags.delete(tag);
                chip.classList.remove('active');
            } else {
                activeTags.add(tag);
                chip.classList.add('active');
            }
            updateTagFilterCount();
            applyFilters();
        });
    });

    clearBtn.addEventListener('click', () => {
        input.value = '';
        activeTags.clear();
        tagChips.forEach((chip) => chip.classList.remove('active'));
        updateTagFilterCount();
        applyFilters();
        input.focus();
    });

    // Initial pass in case the browser restored a typed value on reload.
    updateTagFilterCount();
    applyFilters();
});
