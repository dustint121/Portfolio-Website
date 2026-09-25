"""
Markdown rendering for post bodies.

Wraps the python-markdown library with a fixed extension set so the same
flavor of Markdown is used everywhere.
"""

import re
import markdown


# python-markdown extensions we want enabled site-wide. list of str.
    # - extra:        tables, fenced code, footnotes, attr lists, etc.
    # - sane_lists:   nicer ordered/unordered list handling
    # - toc:          generate header anchors (used for in-page links)
    # - codehilite:   wraps code blocks in <pre><code class="language-..."> for highlighters
_EXTENSIONS = ["extra", "sane_lists", "toc", "codehilite"]

_EXTENSION_CONFIGS = {
    "codehilite": {
        "use_pygments": False,
        "css_class": "codehilite",
    },
}


def render_markdown(text):
    """Render a Markdown string to an HTML string.

    Input:  text : str - Markdown body (front matter already stripped)
    Output: str  - rendered HTML
    """
    if not text:
        return ""
    md = markdown.Markdown(
        extensions=_EXTENSIONS,
        extension_configs=_EXTENSION_CONFIGS,
        output_format="html5",
    )
    return md.convert(text)


# Matches Markdown/HTML markup we want stripped for the search index: code
# fences, inline code, HTML tags, link/image syntax (keeps the link text),
# heading/list/quote markers, emphasis markers, and horizontal rules.
# list of tuple(str pattern, str replacement)
_STRIP_PATTERNS = [
    (r"```.*?```", " "),                    # fenced code blocks (with body)
    (r"`[^`]*`", " "),                       # inline code
    (r"<[^>]+>", " "),                       # raw HTML tags
    (r"!\[([^\]]*)\]\([^)]*\)", r"\1"),      # images -> alt text only
    (r"\[([^\]]*)\]\([^)]*\)", r"\1"),       # links -> link text only
    (r"^\s{0,3}#{1,6}\s*", "", ),             # heading markers
    (r"^\s*>+\s?", ""),                      # blockquote markers
    (r"^\s*[-*+]\s+", ""),                   # bullet list markers
    (r"^\s*\d+\.\s+", ""),                   # numbered list markers
    (r"[*_~#>`]", " "),                      # remaining emphasis/markup chars
]


def strip_markdown(text):
    """Reduce a Markdown string to plain, searchable text.

    Not a full Markdown parser -- just enough regex cleanup so full-text
    search doesn't get tripped up by asterisks, headings, code fences,
    link syntax, etc. Whitespace is also collapsed to single spaces.

    Input:  text : str - raw Markdown body
    Output: str  - plain text, lowercased is NOT applied here (caller's choice)
    """
    if not text:
        return ""

    plain = text  # str, mutated line-by-line and pattern-by-pattern below
    for pattern, repl in _STRIP_PATTERNS:
        flags = re.MULTILINE if pattern.startswith("^") else 0
        plain = re.sub(pattern, repl, plain, flags=flags)

    # Collapse all whitespace (including newlines) down to single spaces.
    plain = re.sub(r"\s+", " ", plain).strip()
    return plain