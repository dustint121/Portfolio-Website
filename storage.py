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

import os
from datetime import date, datetime
from functools import lru_cache

import boto3
import frontmatter
from botocore.exceptions import ClientError
from dotenv import load_dotenv

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

    section, _, filename = key.partition("/")  # all str
    slug = os.path.splitext(filename)[0]       # str

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


def list_keys(section):
    """List all `.md` object keys under a section prefix.

    Input:  section : str - "Projects" or "Notes"
    Output: list of str
    """
    if section not in SECTIONS:
        raise ValueError(f"Unknown section: {section}. Expected one of {SECTIONS}.")

    client = get_client()
    prefix = f"{section}/"  # str
    paginator = client.get_paginator("list_objects_v2")

    keys = []  # list of str
    for page in paginator.paginate(Bucket=BUCKET_NAME, Prefix=prefix):
        for obj in page.get("Contents", []) or []:
            key = obj["Key"]  # str
            if key.lower().endswith(".md") and key != prefix:
                keys.append(key)
    return keys


def get_post(key):
    """Fetch and parse a single Markdown file by its full key.

    Input:  key : str - full S3 key
    Output: Post
    """
    client = get_client()
    obj = client.get_object(Bucket=BUCKET_NAME, Key=key)  # dict
    return _parse(key, obj["Body"].read())


def list_posts(section):
    """Fetch and parse every Markdown file in a section, newest first.

    Input:  section : str - "Projects" or "Notes"
    Output: list of Post
    """
    posts = [get_post(k) for k in list_keys(section)]  # list of Post
    posts.sort(key=lambda p: (p.date or date.min), reverse=True)
    return posts


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