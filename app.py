from flask import Flask, Response, abort, jsonify, render_template
from botocore.exceptions import ClientError

import storage
from rendering import render_markdown

# S3 key for the profile picture stored at the bucket root. str.
PROFILE_IMAGE_KEY = "profile_image.jpg"

app = Flask(__name__)


@app.route("/")
def home():
    # Pull both sections; show the most recent N items together as the
    # home-page feed (mirrors the reference site's behavior).
    projects = storage.list_posts("Projects")  # list of Post
    notes = storage.list_posts("Notes")        # list of Post
    feed = sorted(
        projects + notes,
        key=lambda p: (p.date is None, p.date),  # None dates sink to the bottom
        reverse=True,
    )[:10]  # list of Post (top 10)

    return render_template(
        "home.html",
        active_page="home",
        posts=feed,
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
    posts = storage.list_posts(section)  # list of Post
    meta = SECTION_META[section]         # dict
    return render_template(
        "section.html",
        active_page=section.lower(),
        section=section,
        heading=meta["heading"],
        intro=meta["intro"],
        posts=posts,
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


@app.context_processor
def inject_globals():
    # Make the profile image URL available to every template.
    # Output: dict
    return {"profile_image_url": "/profile-image"}


@app.route("/healthz")
def healthz():
    # Output: JSON dict
    return jsonify(storage.check_connection())


@app.errorhandler(404)
def not_found(_e):
    return render_template("404.html"), 404


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)