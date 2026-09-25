// Client-side search + tag filter for post-card lists (home/section pages).
// Filters ".card-link" elements already in the DOM against:
//   - free-text query, matched against data-search-text (title + summary + body)
//   - a set of active tags (toggled via .tag-chip buttons), matched against
//     data-tags -- a post must have ALL active tags to stay visible (AND logic)
// The two filters are combined with AND: a card must satisfy both to show.
document.addEventListener('DOMContentLoaded', () => {
    const root = document.querySelector('[data-search-root="true"]');
    const cardList = document.getElementById('card-list');
    if (!root || !cardList) return;

    const input = document.getElementById('search-input');
    const clearBtn = document.getElementById('search-clear');
    const emptyState = document.getElementById('search-empty-state');
    const introCount = document.getElementById('intro-count');
    const tagChips = Array.from(root.querySelectorAll('.tag-chip'));
    const cards = Array.from(cardList.querySelectorAll('.card-link'));

    // Set of currently active (selected) tag names, lowercase. Set of str.
    const activeTags = new Set();

    const applyFilters = () => {
        const query = (input.value || '').trim().toLowerCase();  // str
        let visibleCount = 0;  // int

        cards.forEach((card) => {
            const searchText = card.dataset.searchText || '';          // str
            const cardTags = (card.dataset.tags || '').split(',')      // list of str
                .map((t) => t.trim())
                .filter(Boolean);

            const matchesText = query === '' || searchText.includes(query);
            const matchesTags = activeTags.size === 0 ||
                Array.from(activeTags).every((tag) => cardTags.includes(tag));

            const visible = matchesText && matchesTags;
            card.hidden = !visible;
            if (visible) visibleCount += 1;
        });

        emptyState.hidden = visibleCount !== 0;
        clearBtn.hidden = query === '' && activeTags.size === 0;

        if (introCount) {
            const label = visibleCount === 1 ? 'post' : 'posts';
            introCount.textContent = `${visibleCount} ${label}`;
        }
    };

    input.addEventListener('input', applyFilters);

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
            applyFilters();
        });
    });

    clearBtn.addEventListener('click', () => {
        input.value = '';
        activeTags.clear();
        tagChips.forEach((chip) => chip.classList.remove('active'));
        applyFilters();
        input.focus();
    });

    // Initial pass in case the browser restored a typed value on reload.
    applyFilters();
});
