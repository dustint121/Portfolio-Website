// Client-side search + tag filter + pagination for post-card lists
// (home/section pages). Every post for the current page/section is
// rendered into the DOM up front (see app.py); this script decides which
// of those cards are shown at any moment, based on:
//   - free-text query, matched against either data-title (title-only mode)
//     or data-search-text (title + summary + body), depending on the
//     "Title only" toggle button's state
//   - a set of active tags (toggled via .tag-chip buttons inside the
//     collapsible <details> tag list), matched against data-tags -- a post
//     must have ALL active tags to stay visible (AND logic)
//   - the current page number, applied AFTER the above two filters, so
//     pagination always operates on the filtered result set rather than
//     the full unfiltered list. Changing the search query or tags resets
//     back to page 1.
// The text filter and tag filter are combined with AND: a card must
// satisfy both to be considered a match before pagination slices it.
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

    const paginationNav = document.getElementById('pagination-nav');
    const pagePrevBtn = document.getElementById('page-prev');
    const pageNextBtn = document.getElementById('page-next');
    const pageNumbersEl = document.getElementById('page-numbers');
    // Page size: how many matching posts to show per page. int.
    const postsPerPage = paginationNav
        ? (parseInt(paginationNav.dataset.postsPerPage, 10) || 10)
        : 10;

    // Set of currently active (selected) tag names, lowercase. Set of str.
    const activeTags = new Set();
    // Whether the free-text query should only match the title. bool.
    let titleOnly = false;
    // Current 1-based page number over the FILTERED result set. int.
    let currentPage = 1;

    const updateTagFilterCount = () => {
        if (!tagFilterCount) return;
        if (activeTags.size > 0) {
            tagFilterCount.textContent = String(activeTags.size);
            tagFilterCount.hidden = false;
        } else {
            tagFilterCount.hidden = true;
        }
    };

    // Returns the list of cards that pass the current text + tag filters,
    // in DOM order (which is already newest-first from the server).
    // Output: array of Element.
    const getMatchingCards = () => {
        const query = (input.value || '').trim().toLowerCase();  // str
        return cards.filter((card) => {
            const haystack = titleOnly
                ? (card.dataset.title || '')
                : (card.dataset.searchText || '');  // str
            const cardTags = (card.dataset.tags || '').split(',')  // list of str
                .map((t) => t.trim())
                .filter(Boolean);

            const matchesText = query === '' || haystack.includes(query);
            const matchesTags = activeTags.size === 0 ||
                Array.from(activeTags).every((tag) => cardTags.includes(tag));
            return matchesText && matchesTags;
        });
    };

    const renderPageNumbers = (totalPages) => {
        if (!pageNumbersEl) return;
        pageNumbersEl.innerHTML = '';
        for (let p = 1; p <= totalPages; p += 1) {
            const btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'page-number' + (p === currentPage ? ' current' : '');
            btn.textContent = String(p);
            if (p === currentPage) {
                btn.setAttribute('aria-current', 'page');
            } else {
                btn.addEventListener('click', () => {
                    currentPage = p;
                    applyFilters();
                });
            }
            pageNumbersEl.appendChild(btn);
        }
    };

    const applyFilters = (resetPage) => {
        const matching = getMatchingCards();  // array of Element, filtered
        const totalMatches = matching.length;  // int
        const totalPages = Math.max(1, Math.ceil(totalMatches / postsPerPage));  // int

        if (resetPage) currentPage = 1;
        currentPage = Math.max(1, Math.min(currentPage, totalPages));

        const start = (currentPage - 1) * postsPerPage;  // int
        const end = start + postsPerPage;                // int
        const matchingSet = new Set(matching);            // Set of Element

        let visibleCount = 0;  // int, cards shown on THIS page after paging
        cards.forEach((card) => {
            card.hidden = !matchingSet.has(card);
        });
        matching.forEach((card, idx) => {
            const onCurrentPage = idx >= start && idx < end;
            card.hidden = !onCurrentPage;
            if (onCurrentPage) visibleCount += 1;
        });

        const query = (input.value || '').trim();  // str
        const filterActive = query !== '' || activeTags.size > 0;  // bool

        emptyState.hidden = totalMatches !== 0;
        clearBtn.hidden = !filterActive;

        if (paginationNav) {
            paginationNav.hidden = totalPages <= 1;
            if (pagePrevBtn) pagePrevBtn.disabled = currentPage <= 1;
            if (pageNextBtn) pageNextBtn.disabled = currentPage >= totalPages;
            renderPageNumbers(totalPages);
        }

        if (introCount) {
            const label = totalMatches === 1 ? 'post' : 'posts';
            introCount.textContent = filterActive
                ? `${totalMatches} matching ${label}`
                : `${totalMatches} ${label}`;
        }
    };

    input.addEventListener('input', () => applyFilters(true));

    if (titleOnlyToggle) {
        titleOnlyToggle.addEventListener('click', () => {
            titleOnly = !titleOnly;
            titleOnlyToggle.classList.toggle('active', titleOnly);
            titleOnlyToggle.setAttribute('aria-pressed', String(titleOnly));
            applyFilters(true);
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
            applyFilters(true);
        });
    });

    clearBtn.addEventListener('click', () => {
        input.value = '';
        activeTags.clear();
        tagChips.forEach((chip) => chip.classList.remove('active'));
        updateTagFilterCount();
        applyFilters(true);
        input.focus();
    });

    if (pagePrevBtn) {
        pagePrevBtn.addEventListener('click', () => {
            currentPage -= 1;
            applyFilters();
        });
    }
    if (pageNextBtn) {
        pageNextBtn.addEventListener('click', () => {
            currentPage += 1;
            applyFilters();
        });
    }

    // Initial pass in case the browser restored a typed value on reload.
    updateTagFilterCount();
    applyFilters(true);
});
