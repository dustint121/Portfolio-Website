import os

from flask import Flask, Response, abort, jsonify, render_template, request, send_from_directory
from botocore.exceptions import ClientError

import storage
from rendering import render_markdown

# S3 key for the profile picture stored at the bucket root. str.
PROFILE_IMAGE_KEY = "profile_image.jpg"

# S3 key for the About page markdown stored at the bucket root. str.
ABOUT_KEY = "About_Me.md"


RESUME_FILENAME = "Dustin_Tran_Resume.pdf"
RESUME_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")

# Favicon shown in the browser tab, also a local file under assets/. str, str
FAVICON_FILENAME = "favicon.ico"
FAVICON_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")

# How many posts are shown on a single page of Home/Projects/Notes before
# pagination controls (Previous / page numbers / Next) kick in. Change this
# to alter the page size everywhere at once. int.
POSTS_PER_PAGE = 10

app = Flask(__name__)


def _paginate(items, page):
    # Slice a list of Post into one page and compute pagination metadata.
    # Inputs:
    #   items : list of Post - already sorted newest-first
    #   page  : int - 1-based page number requested by the caller
    # Output: tuple of (list of Post - the page's items,
    #                    dict - {page, total_pages, has_prev, has_next,
    #                            prev_page, next_page, total_count})
    total_count = len(items)  # int
    total_pages = max(1, (total_count + POSTS_PER_PAGE - 1) // POSTS_PER_PAGE)  # int
    page = max(1, min(page, total_pages))  # int, clamped into range
    start = (page - 1) * POSTS_PER_PAGE  # int
    end = start + POSTS_PER_PAGE         # int
    page_items = items[start:end]        # list of Post
    pagination = {
        "page": page,
        "total_pages": total_pages,
        "has_prev": page > 1,
        "has_next": page < total_pages,
        "prev_page": page - 1,
        "next_page": page + 1,
        "total_count": total_count,
    }
    return page_items, pagination


def _get_page_param():
    # Read and validate the "?page=" query parameter shared by every
    # paginated route. Output: int - 1 if missing/invalid/less than 1.
    raw = request.args.get("page", "1")  # str
    try:
        page = int(raw)
    except (TypeError, ValueError):
        page = 1
    return max(1, page)


@app.route("/")
def home():
    # Pull both sections and merge into one newest-first feed, then show
    # one page's worth (POSTS_PER_PAGE) with pagination controls for the rest.
    projects = storage.list_posts("Projects")  # list of Post
    notes = storage.list_posts("Notes")        # list of Post
    feed = sorted(
        projects + notes,
        key=lambda p: (p.date is None, p.date),  # None dates sink to the bottom
        reverse=True,
    )  # list of Post, full newest-first feed

    page = _get_page_param()  # int
    page_posts, pagination = _paginate(feed, page)

    return render_template(
        "home.html",
        active_page="home",
        posts=page_posts,
        pagination=pagination,
        pagination_endpoint="home",
        pagination_endpoint_kwargs={},
    )


# Per-section metadata used to title and describe the index pages.
# dict mapping str (section name) -> dict with str keys "heading" and "intro"
SECTION_META = {
    "Projects": {
        "heading": "Projects",
        "intro": (
            "Things I've built or am building. Each entry links to a longer "
            "writeup with context, decisions, and what I learned."
        ),
    },
    "Notes": {
        "heading": "Notes",
        "intro": (
            "Shorter writeups, cheatsheets, and study notes I keep around "
            "for my own reference. Posted here in case they're useful to others."
        ),
    },
}


@app.route("/projects")
def projects_page():
    # Output: rendered HTML for the Projects index
    return _render_section("Projects")


@app.route("/notes")
def notes_page():
    # Output: rendered HTML for the Notes index
    return _render_section("Notes")


def _render_section(section):
    # Input:  section : str - "Projects" or "Notes"
    # Output: rendered HTML
    all_posts = storage.list_posts(section)  # list of Post, full newest-first
    meta = SECTION_META[section]             # dict

    page = _get_page_param()  # int
    page_posts, pagination = _paginate(all_posts, page)

    return render_template(
        "section.html",
        active_page=section.lower(),
        section=section,
        heading=meta["heading"],
        intro=meta["intro"],
        posts=page_posts,
        total_count=len(all_posts),
        pagination=pagination,
        pagination_endpoint="projects_page" if section == "Projects" else "notes_page",
        pagination_endpoint_kwargs={},
    )


@app.route("/<section>/<slug>")
def post_page(section, slug):
    # section : str, slug : str
    if section not in storage.SECTIONS:
        abort(404)

    post = storage.get_post_by_slug(section, slug)  # Post or None
    if post is None:
        abort(404)

    body_html = render_markdown(post.body)  # str
    return render_template(
        "post.html",
        active_page=section.lower(),
        post=post,
        body_html=body_html,
    )


@app.route("/about")
def about_page():
    # Output: rendered HTML for the About page
    try:
        post = storage.get_post_cached(ABOUT_KEY)  # Post
    except ClientError:
        abort(404)
    body_html = render_markdown(post.body)  # str
    return render_template(
        "post.html",
        active_page="about",
        post=post,
        body_html=body_html,
        breadcrumb_label="About",
        # Static page: hide date + tags meta line.
        hide_meta=True,
    )


@app.route("/profile-image")
def profile_image():
    # Proxy the profile image bytes from S3 with browser-cache headers.
    # Output: flask.Response (image bytes) or 404
    try:
        data, content_type = storage.get_binary(PROFILE_IMAGE_KEY)
    except ClientError:
        abort(404)

    if not content_type:
        content_type = "image/jpeg"  # str fallback

    resp = Response(data, mimetype=content_type)
    # Browser may cache for 1 hour; matches the in-memory TTL roughly.
    resp.headers["Cache-Control"] = "public, max-age=3600"
    return resp


@app.route("/" + RESUME_FILENAME)
def resume():
    # Serve the resume PDF straight from the local "assets" folder
    if not os.path.isfile(os.path.join(RESUME_DIR, RESUME_FILENAME)):
        abort(404)
    return send_from_directory(RESUME_DIR, RESUME_FILENAME, mimetype="application/pdf")


@app.route("/favicon.ico")
def favicon():
    # Serve the browser-tab icon straight from the local "assets" folder.
    # Output: flask.Response (ICO bytes) or 404
    favicon_path = os.path.join(FAVICON_DIR, FAVICON_FILENAME)  # str
    if not os.path.isfile(favicon_path):
        abort(404)
    resp = send_from_directory(
        FAVICON_DIR, FAVICON_FILENAME, mimetype="image/vnd.microsoft.icon"
    )
    # Cache for a long time once a browser does pick it up correctly.
    # Chrome caches favicons very aggressively and sometimes ignores a
    # fresh fetch entirely; the cache-busting "v" query param on the
    # <link> tag (see inject_globals + base.html) is what actually forces
    # a refetch when the file changes, not this header.
    resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    return resp


def _static_version(*relative_path_parts):
    # Compute a cache-busting version number from a static file's mtime.
    # Inputs:  relative_path_parts : str... - joined under the Flask app's
    #          static folder, e.g. _static_version("css", "style.css")
    # Output: int - the file's mtime (whole seconds), or 0 if missing.
    path = os.path.join(app.static_folder, *relative_path_parts)  # str
    try:
        return int(os.path.getmtime(path))
    except OSError:
        return 0  # int fallback if the file is missing


@app.context_processor
def inject_globals():
    # Make the profile image URL and cache-busted asset URLs available to
    # every template. Browsers (and any reverse proxy / CDN in front of the
    # deployed app) can cache CSS/JS/favicon aggressively and sometimes
    # ignore normal Cache-Control headers, so every asset URL carries a "v"
    # query param derived from that file's mtime -- editing the file changes
    # this value, which forces a refetch instead of reusing a stale cached
    # copy. This is why a change can render correctly right after a local
    # `python app.py` run (no stale cache yet) but look outdated on a
    # deployed server that already cached the old file.
    # Output: dict
    favicon_path = os.path.join(FAVICON_DIR, FAVICON_FILENAME)  # str
    try:
        favicon_version = int(os.path.getmtime(favicon_path))  # int
    except OSError:
        favicon_version = 0  # int fallback if the file is missing

    return {
        "profile_image_url": "/profile-image",
        "favicon_url": "/favicon.ico?v=" + str(favicon_version),
        "style_css_url": "/static/css/style.css?v=" + str(_static_version("css", "style.css")),
        "main_js_url": "/static/js/main.js?v=" + str(_static_version("js", "main.js")),
        "search_js_url": "/static/js/search.js?v=" + str(_static_version("js", "search.js")),
    }


@app.route("/healthz")
def healthz():
    # Output: JSON dict
    return jsonify(storage.check_connection())


@app.errorhandler(404)
def not_found(_e):
    return render_template("404.html"), 404


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)