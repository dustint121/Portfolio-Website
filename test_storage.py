"""
Manual integration test for the storage layer.

Usage:
    python test_storage.py

Requires a populated .env file. Will hit the live Mega S4 bucket.
"""

import sys
import textwrap

import storage


def hr(label=""):
    # label : str
    line = "-" * 60
    print(f"\n{line}\n{label}\n{line}" if label else line)


def test_connection():
    # Output: bool (True if connection is healthy)
    hr("1. Connection check")
    result = storage.check_connection()  # dict
    print(result)
    if not result["ok"]:
        print("\nConnection failed. Check .env values and bucket permissions.")
        return False
    return True


def test_list_keys():
    # Output: dict mapping section name (str) -> list of S3 keys (list of str)
    hr("2. List keys per section")
    found = {}
    for section in storage.iter_sections():  # section : str
        keys = storage.list_keys(section)    # list of str
        found[section] = keys
        print(f"\n[{section}] {len(keys)} file(s):")
        for k in keys:
            print(f"  - {k}")
    return found


def test_get_post(found):
    # Input: found - dict of section (str) -> list of keys (list of str)
    hr("3. Fetch + parse a single post")
    sample_key = None  # str or None
    for keys in found.values():
        if keys:
            sample_key = keys[0]
            break
    if not sample_key:
        print("No .md files found in any section. Upload some first.")
        return

    post = storage.get_post(sample_key)  # storage.Post
    print(f"key:     {post.key}")
    print(f"section: {post.section}")
    print(f"slug:    {post.slug}")
    print(f"title:   {post.title}")
    print(f"date:    {post.date_iso}")
    print(f"tags:    {post.tags}")
    print(f"author:  {post.author}")
    print(f"summary: {post.summary}")
    print(f"extra:   {post.extra}")
    body_preview = textwrap.shorten(post.body.replace("\n", " "), width=200)  # str
    print(f"body:    {body_preview}")


def test_list_posts():
    hr("4. List + parse all posts (sorted by date, newest first)")
    everything = storage.list_all_posts()  # dict of str -> list of Post
    for section, posts in everything.items():
        print(f"\n[{section}] {len(posts)} post(s):")
        for p in posts:
            tags = ", ".join(p.tags) if p.tags else "-"  # str
            print(f"  {p.date_iso or '????-??-??'}  {p.title}  ({tags})")


def main():
    # Output: int (process exit code)
    if not test_connection():
        return 1
    found = test_list_keys()
    test_get_post(found)
    test_list_posts()
    hr()
    print("All checks completed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())