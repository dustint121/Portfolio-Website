import os

from flask import Flask, Response, abort, jsonify, render_template, send_from_directory
from botocore.exceptions import ClientError

import storage
from rendering import render_markdown

PROFILE_IMAGE_FILENAME = "profile_image.jpg"
PROFILE_IMAGE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")

# S3 key for the About page markdown stored at the bucket root. str.
ABOUT_KEY = "About_Me.md"


RESUME_FILENAME = "Dustin_Tran_Resume.pdf"
RESUME_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")

# Favicon shown in the browser tab, also a local file under assets/. str, str
FAVICON_FILENAME = "favicon.ico"
FAVICON_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")

# How many posts are shown on a single page of Home/Projects/Notes before
# pagination controls (Previous / page numbers / Next) kick in. Passed to
# the templates as `posts_per_page` and read by static/js/search.js, which
# does the actual paging client-side over ALL of a page's posts -- change
# this one value to alter the page size everywhere at once. int.
POSTS_PER_PAGE = 10

app = Flask(__name__)


@app.route("/")
def home():
    # Pull both sections and merge into one newest-first feed. All posts are
    # rendered into the page; pagination AND search/tag filtering both run
    # client-side (static/js/search.js) over that same full set, so paging
    # through results and filtering results stay consistent with each other
    # -- neither one is limited to whatever happened to be on the current
    # server-rendered page.
    projects = storage.list_posts("Projects")  # list of Post
    notes = storage.list_posts("Notes")        # list of Post
    feed = sorted(
        projects + notes,
        key=lambda p: (p.date is None, p.date),  # None dates sink to the bottom
        reverse=True,
    )  # list of Post, full newest-first feed

    return render_template(
        "home.html",
        active_page="home",
        posts=feed,
        posts_per_page=POSTS_PER_PAGE,
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

    # All posts are rendered into the page; pagination AND search/tag
    # filtering both run client-side over that same full set (see home()
    # above for why).
    return render_template(
        "section.html",
        active_page=section.lower(),
        section=section,
        heading=meta["heading"],
        intro=meta["intro"],
        posts=all_posts,
        total_count=len(all_posts),
        posts_per_page=POSTS_PER_PAGE,
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
    # Serve the profile picture straight from the local "assets" folder
    # (see PROFILE_IMAGE_DIR comment above) instead of fetching it from
    # S3-compatible storage on every request.
    # Output: flask.Response (image bytes) or 404
    profile_image_path = os.path.join(PROFILE_IMAGE_DIR, PROFILE_IMAGE_FILENAME)  # str
    if not os.path.isfile(profile_image_path):
        abort(404)
    resp = send_from_directory(
        PROFILE_IMAGE_DIR, PROFILE_IMAGE_FILENAME, mimetype="image/jpeg"
    )
    # Cache-busting "v" query param (see inject_globals + base.html pattern)
    # already forces a refetch when the file changes, so this header can
    # cache aggressively without risking a stale image after an update.
    resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
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

    profile_image_path = os.path.join(PROFILE_IMAGE_DIR, PROFILE_IMAGE_FILENAME)  # str
    try:
        profile_image_version = int(os.path.getmtime(profile_image_path))  # int
    except OSError:
        profile_image_version = 0  # int fallback if the file is missing

    return {
        "profile_image_url": "/profile-image?v=" + str(profile_image_version),
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