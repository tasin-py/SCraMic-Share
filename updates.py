"""Check for updates: asks GitHub for this app's releases, each time the app starts and from Settings.

It only tells the user. Nothing is downloaded or installed here: the button opens the releases page.
"""
import json
import re
import urllib.error
import urllib.request

VERSION = "1.2.1"
REPO = "tasin-py/SCraMic-Share"
RELEASES_PAGE = f"https://github.com/{REPO}/releases"
RELEASES_API = f"https://api.github.com/repos/{REPO}/releases?per_page=30"   # also lists pre-releases


def _number(version):
    """'v1.2.0' -> (1, 2), so that 1.2 and 1.2.0 count as the same version."""
    parts = [int(p) for p in re.findall(r"\d+", version)]
    while parts and parts[-1] == 0:
        parts.pop()
    return tuple(parts)


def check():
    """{"state": "current" | "update" | "none" | "error", "current": VERSION, "version": newest, if newer}"""
    out = {"current": VERSION}
    req = urllib.request.Request(RELEASES_API, headers={"User-Agent": "SCraMicShare",
                                                        "Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            releases = json.load(r)
        tags = [x.get("tag_name", "") for x in releases if not x.get("draft")]
    except urllib.error.HTTPError as e:
        return {**out, "state": "none" if e.code == 404 else "error"}   # 404: nothing published yet
    except (OSError, ValueError, AttributeError, TypeError):
        return {**out, "state": "error"}
    tags = [t for t in tags if isinstance(t, str) and re.fullmatch(r"v?\d+(\.\d+)*", t)]
    if not tags:
        return {**out, "state": "none"}
    newest = max(tags, key=_number)
    if _number(newest) > _number(VERSION):
        return {**out, "state": "update", "version": newest.lstrip("v")}
    return {**out, "state": "current"}
