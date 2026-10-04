"""
Storage layer for the portfolio site.

Reads Markdown files from a Mega S4 (S3-compatible) bucket organized as:

    <bucket>/
        Projects/
            some-project.md
        Notes/
            some-note.md

Each Markdown file is expected to start with YAML front matter:

    ---
    title: My Post
    date: 2026-04-29
    tags: [ml, pytorch]
    summary: Short blurb for the card view.
    ---

    Body in Markdown...
"""

import logging
import os
import threading
import time
from datetime import date, datetime
from functools import lru_cache

import boto3
import frontmatter
from botocore.exceptions import ClientError
from dotenv import load_dotenv

from rendering import strip_markdown

load_dotenv()

# ----- Config ---------------------------------------------------------------

# All values below are strings loaded from the .env file.
ACCESS_KEY = os.getenv("MEGA_ACCESS_KEY")
SECRET_KEY = os.getenv("MEGA_SECRET_KEY")
S4_ENDPOINT = os.getenv("MEGA_S4_ENDPOINT")
S4_REGION = os.getenv("MEGA_S4_REGION")
BUCKET_NAME = os.getenv("MEGA_BUCKET_NAME")

# Folder prefixes inside the bucket. Tuple of strings, capitalized to match S3 keys.
SECTIONS = ("Projects", "Notes")

# How long (seconds) cached posts count as "fresh". Once older than this, the
# cached copy is still served immediately (stale-while-revalidate) while a
# background thread checks the bucket for changes. int.
CACHE_TTL_SECONDS = 300

# After a FAILED background refresh (e.g. the bucket is unreachable), wait
# this many seconds before trying again so an outage is not hit on every
# request. The stale copy keeps being served meanwhile. int.
FAILED_REFRESH_RETRY_SECONDS = 30

logger = logging.getLogger(__name__)

# Module-level caches.
# _cache : dict mapping str (cache name) -> tuple(float timestamp, value)
#   cache names: "section:<Section>" -> value is list of Post
#                "single:<S3 key>"   -> value is Post
_cache = {}

# Parsed posts remembered by S3 key, along with the ETag they were parsed
# from. A refresh compares the bucket listing's ETag to this one and skips
# downloading files whose ETag has not changed.
# _post_cache : dict mapping str (S3 key) -> tuple(str etag, Post)
_post_cache = {}

# One refresh at a time per cache name, so concurrent visitors on a cold
# cache wait for a single download pass instead of each doing their own.
# _refresh_locks : dict mapping str (cache name) -> threading.Lock
_refresh_locks = {}
# Cache names that currently have a background refresh running. set of str
_refreshing = set()
# Guards _refresh_locks, _refreshing and _cache writes. threading.Lock
_state_lock = threading.Lock()


# ----- Data model -----------------------------------------------------------
class Post:
    """A parsed Markdown post: front-matter metadata + body.

    Field types:
        key      : str   - full S3 key, e.g. "Projects/foo.md"
        section  : str   - "Projects" or "Notes"
        slug     : str   - filename without extension, e.g. "foo"
        title    : str
        date     : datetime.date or None
        tags     : list of str
        summary  : str
        author   : str
        body     : str   - Markdown body (no front matter)
        extra    : dict  - any other YAML keys not listed above
    """

    def __init__(
        self,
        key="",
        section="",
        slug="",
        title="",
        date=None,
        tags=None,
        summary="",
        author="",
        body="",
        extra=None,
    ):
        self.key = key            # str
        self.section = section    # str
        self.slug = slug          # str
        self.title = title        # str
        self.date = date          # datetime.date or None
        self.tags = tags or []    # list of str
        self.summary = summary    # str
        self.author = author      # str
        self.body = body          # str
        self.extra = extra or {}  # dict
        
    def __repr__(self):
        # Output: str
        return (
            f"Post(key={self.key!r}, title={self.title!r}, "
            f"date={self.date_iso!r}, tags={self.tags!r})"
        )

    @property
    def date_iso(self):
        # Returns: str ("" when date is missing, else ISO 8601 date string)
        return self.date.isoformat() if self.date else ""

    @property
    def search_text(self):
        # Plain-text version of the body, used for client-side full-text
        # search (see templates/partials/post_card.html data-search-text).
        # Returns: str
        return strip_markdown(self.body)


# ----- Client ---------------------------------------------------------------


@lru_cache(maxsize=1)
def get_client():
    """Build (and cache) a boto3 S3 client pointed at the Mega S4 endpoint.

    Returns: botocore.client.S3 instance.
    """
    if not all([ACCESS_KEY, SECRET_KEY, S4_ENDPOINT, S4_REGION, BUCKET_NAME]):
        raise RuntimeError(
            "Missing one or more env vars: "
            "MEGA_ACCESS_KEY, MEGA_SECRET_KEY, MEGA_S4_ENDPOINT, "
            "MEGA_S4_REGION, MEGA_BUCKET_NAME"
        )

    session = boto3.session.Session()
    return session.client(
        service_name="s3",
        aws_access_key_id=ACCESS_KEY,
        aws_secret_access_key=SECRET_KEY,
        endpoint_url=S4_ENDPOINT,
        region_name=S4_REGION,
    )


# ----- Helpers --------------------------------------------------------------


def _coerce_date(value):
    """Accept date, datetime, or ISO string from front matter.

    Input:  any (typically datetime.date, datetime.datetime, str, or None)
    Output: datetime.date or None
    """
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value.strip())
        except ValueError:
            return None
    return None


def _coerce_tags(value):
    """Normalize tags to a lowercase, hyphenated list.

    Input:  any (typically list, tuple, str, or None)
    Output: list of str
    """
    if not value:
        return []
    if isinstance(value, str):
        items = [t.strip() for t in value.split(",")]
    elif isinstance(value, (list, tuple)):
        items = [str(t).strip() for t in value]
    else:
        return []
    return [t.lower().replace(" ", "-") for t in items if t]


def _parse(key, raw_bytes):
    """Parse a Markdown file's bytes into a Post.

    Inputs:
        key       : str   - full S3 key, e.g. "Projects/foo.md"
        raw_bytes : bytes - raw file contents from S3

    Output: Post
    """
    text = raw_bytes.decode("utf-8")  # str
    fm = frontmatter.loads(text)      # frontmatter.Post
    meta = dict(fm.metadata)          # dict (front-matter keys -> values)


    # Keys at the bucket root have no "/" and thus no section.
    if "/" in key:
        section, _, filename = key.partition("/")  # all str
    else:
        section = ""        # str
        filename = key      # str
    slug = os.path.splitext(filename)[0]           # str


    known_keys = {"title", "date", "tags", "summary", "author"}  # set of str
    extra = {k: v for k, v in meta.items() if k not in known_keys}  # dict

    return Post(
        key=key,
        section=section,
        slug=slug,
        title=str(meta.get("title") or slug),
        date=_coerce_date(meta.get("date")),
        tags=_coerce_tags(meta.get("tags")),
        summary=str(meta.get("summary") or ""),
        author=str(meta.get("author") or ""),
        body=fm.content,  # str
        extra=extra,
    )


# ----- Public API -----------------------------------------------------------


def list_objects(section):
    """List all `.md` objects under a section prefix, with their ETags.

    Input:  section : str - "Projects" or "Notes"
    Output: list of tuple(str key, str etag). The ETag changes whenever the
            file's contents change, so it is used to skip unchanged files.
    """
    if section not in SECTIONS:
        raise ValueError(f"Unknown section: {section}. Expected one of {SECTIONS}.")

    client = get_client()
    prefix = f"{section}/"  # str
    paginator = client.get_paginator("list_objects_v2")

    objects = []  # list of tuple(str, str)
    for page in paginator.paginate(Bucket=BUCKET_NAME, Prefix=prefix):
        for obj in page.get("Contents", []) or []:
            key = obj["Key"]  # str
            if key.lower().endswith(".md") and key != prefix:
                objects.append((key, obj.get("ETag") or ""))
    return objects


def list_keys(section):
    """List all `.md` object keys under a section prefix.

    Input:  section : str - "Projects" or "Notes"
    Output: list of str
    """
    return [key for key, _etag in list_objects(section)]


def _fetch_post(key):
    """Download and parse one Markdown file.

    Input:  key : str - full S3 key
    Output: tuple(str etag, Post). The ETag comes from the same response as
            the body, so the pair always matches.
    """
    client = get_client()
    obj = client.get_object(Bucket=BUCKET_NAME, Key=key)  # dict
    etag = obj.get("ETag") or ""                          # str
    return etag, _parse(key, obj["Body"].read())


def get_post(key):
    """Fetch and parse a single Markdown file by its full key.

    Input:  key : str - full S3 key
    Output: Post
    """
    return _fetch_post(key)[1]


# ----- Stale-while-revalidate machinery ---------------------------------------


def _lock_for(name):
    # Input: name : str - cache name. Output: threading.Lock (one per name)
    with _state_lock:
        lock = _refresh_locks.get(name)  # threading.Lock or None
        if lock is None:
            lock = threading.Lock()
            _refresh_locks[name] = lock
        return lock


def _store(name, value):
    # Save a freshly built value under a cache name, stamped with now.
    # Inputs: name : str, value : list of Post or Post
    with _state_lock:
        _cache[name] = (time.time(), value)


def _refresh_in_background(name, refresh_fn):
    """Start a background refresh unless one is already running for `name`.

    Visitors keep getting the stale cached value meanwhile. If the refresh
    fails, the stale value is kept and the next attempt is delayed by
    FAILED_REFRESH_RETRY_SECONDS.

    Inputs: name       : str - cache name
            refresh_fn : callable taking one float (the start time) that
                         rebuilds and stores the value for `name`
    """
    with _state_lock:
        if name in _refreshing:
            return
        _refreshing.add(name)

    def run():
        try:
            refresh_fn(time.time())
        except Exception:
            logger.exception("Background refresh failed for %s; serving stale copy", name)
            with _state_lock:
                cached = _cache.get(name)  # tuple or None
                if cached:
                    # Backdate the timestamp so the copy counts as stale
                    # again only after FAILED_REFRESH_RETRY_SECONDS.
                    retry_stamp = time.time() - CACHE_TTL_SECONDS + FAILED_REFRESH_RETRY_SECONDS  # float
                    _cache[name] = (retry_stamp, cached[1])
        finally:
            with _state_lock:
                _refreshing.discard(name)

    threading.Thread(target=run, name=f"refresh-{name}", daemon=True).start()


def _refresh_section(section, started_at):
    """Rebuild a section's post list, downloading only new or changed files.

    One list call returns every file with its ETag. A file whose ETag
    matches the remembered one reuses its parsed Post with no download.
    Files no longer in the listing disappear from the result.

    Inputs: section    : str   - "Projects" or "Notes"
            started_at : float - when the caller began waiting; if another
                         refresh finished after this, its result is reused
    Output: list of Post, newest first
    """
    name = f"section:{section}"  # str
    with _lock_for(name):
        cached = _cache.get(name)  # tuple or None
        if cached and cached[0] >= started_at:
            return cached[1]  # someone else just refreshed while we waited

        objects = list_objects(section)  # list of tuple(str, str)
        posts = []                       # list of Post
        for key, etag in objects:
            remembered = _post_cache.get(key)  # tuple(str, Post) or None
            if remembered and etag and remembered[0] == etag:
                posts.append(remembered[1])
            else:
                new_etag, post = _fetch_post(key)
                _post_cache[key] = (new_etag, post)
                posts.append(post)

        # Forget parsed posts whose files were deleted from this section.
        live_keys = {key for key, _etag in objects}  # set of str
        prefix = f"{section}/"                        # str
        for key in [k for k in _post_cache if k.startswith(prefix) and k not in live_keys]:
            _post_cache.pop(key, None)

        posts.sort(key=lambda p: (p.date or date.min), reverse=True)
        _store(name, posts)
        return posts


def _refresh_single(key, started_at):
    """Rebuild one standalone post (e.g. About page), skipping the download
    if its ETag is unchanged (one cheap HEAD request instead of a GET).

    Inputs: key : str - full S3 key, started_at : float (see above)
    Output: Post
    """
    name = f"single:{key}"  # str
    with _lock_for(name):
        cached = _cache.get(name)  # tuple or None
        if cached and cached[0] >= started_at:
            return cached[1]

        remembered = _post_cache.get(key)  # tuple(str, Post) or None
        post = None  # Post or None
        if remembered:
            head = get_client().head_object(Bucket=BUCKET_NAME, Key=key)  # dict
            current_etag = head.get("ETag") or ""                          # str
            if current_etag and current_etag == remembered[0]:
                post = remembered[1]
        if post is None:
            etag, post = _fetch_post(key)
            _post_cache[key] = (etag, post)
        _store(name, post)
        return post


def get_post_cached(key, use_cache=True):
    """Same as get_post(), but cached with stale-while-revalidate.

    A fresh cached copy is returned as is. A stale one is returned
    immediately and refreshed in the background. Only the very first call
    (nothing cached yet) waits on the bucket.

    Inputs:
        key       : str  - full S3 key
        use_cache : bool - False forces a blocking refresh
    Output: Post
    """
    now = time.time()  # float
    name = f"single:{key}"  # str
    if use_cache:
        cached = _cache.get(name)  # tuple or None
        if cached:
            if (now - cached[0]) >= CACHE_TTL_SECONDS:
                _refresh_in_background(name, lambda started_at: _refresh_single(key, started_at))
            return cached[1]
    return _refresh_single(key, now)


def list_posts(section, use_cache=True):
    """Return every Markdown post in a section, newest first.

    Uses stale-while-revalidate: a fresh cached list is returned as is; a
    stale one is returned immediately while a background thread re-checks the
    bucket (downloading only changed files). Only the very first call after
    a restart waits on the bucket, and then only for files not yet seen.

    Inputs:
        section   : str  - "Projects" or "Notes"
        use_cache : bool - False forces a blocking refresh
    Output: list of Post
    """
    if section not in SECTIONS:
        raise ValueError(f"Unknown section: {section}. Expected one of {SECTIONS}.")

    now = time.time()  # float
    name = f"section:{section}"  # str
    if use_cache:
        cached = _cache.get(name)  # tuple or None
        if cached:
            if (now - cached[0]) >= CACHE_TTL_SECONDS:
                _refresh_in_background(name, lambda started_at: _refresh_section(section, started_at))
            return cached[1]
    return _refresh_section(section, now)


def get_post_by_slug(section, slug, use_cache=True):
    """Look up a single post by section + slug.
    Inputs:
        section   : str
        slug      : str  - filename without .md extension
        use_cache : bool
    Output: Post or None
    """
    for p in list_posts(section, use_cache=use_cache):
        if p.slug == slug:
            return p
    return None


def clear_cache():
    """Drop the in-memory caches so the next read goes back to S3."""
    with _state_lock:
        _cache.clear()
        _post_cache.clear()
    _binary_cache.clear()


# Cache for arbitrary binary objects (e.g. the profile image).
# _binary_cache : dict mapping str (key) -> tuple(float timestamp, bytes data, str content_type)
_binary_cache = {}
# How long (seconds) to cache binary objects. int.
BINARY_CACHE_TTL_SECONDS = 3600
def get_binary(key, use_cache=True):
    """Fetch any object from the bucket as raw bytes.
    Inputs:
        key       : str  - full S3 key, e.g. "profile_image.jpg"
        use_cache : bool
    Output: tuple (data, content_type)
        data         : bytes
        content_type : str (e.g. "image/jpeg"), "" if unknown
    Raises: botocore.exceptions.ClientError if the object is missing.
    """
    now = time.time()  # float
    if use_cache:
        cached = _binary_cache.get(key)  # tuple or None
        if cached and (now - cached[0]) < BINARY_CACHE_TTL_SECONDS:
            return cached[1], cached[2]
        
    client = get_client()
    obj = client.get_object(Bucket=BUCKET_NAME, Key=key)  # dict
    data = obj["Body"].read()                              # bytes
    content_type = obj.get("ContentType") or ""           # str

    if use_cache:
        _binary_cache[key] = (now, data, content_type)
    return data, content_type


def list_all_posts():
    """Return a dict of section -> list of Post.

    Output: dict mapping str -> list of Post
    """
    return {section: list_posts(section) for section in SECTIONS}


def check_connection():
    """Lightweight health check: confirms creds + bucket reachability.

    Output: dict with keys:
        ok       : bool
        bucket   : str
        endpoint : str
        error    : str (only present when ok is False)
    """
    client = get_client()
    try:
        client.head_bucket(Bucket=BUCKET_NAME)
        return {"ok": True, "bucket": BUCKET_NAME, "endpoint": S4_ENDPOINT}
    except ClientError as e:
        return {
            "ok": False,
            "bucket": BUCKET_NAME,
            "endpoint": S4_ENDPOINT,
            "error": str(e),
        }


def iter_sections():
    # Output: iterator over str
    return iter(SECTIONS)