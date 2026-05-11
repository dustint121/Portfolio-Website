"""
Markdown rendering for post bodies.

Wraps the python-markdown library with a fixed extension set so the same
flavor of Markdown is used everywhere.
"""

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