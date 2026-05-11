from flask import Flask, abort, jsonify, render_template

import storage
from rendering import render_markdown

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


@app.route("/healthz")
def healthz():
    # Output: JSON dict
    return jsonify(storage.check_connection())


@app.errorhandler(404)
def not_found(_e):
    return render_template("404.html"), 404


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)