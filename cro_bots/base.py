"""
base.py — Shared utilities for all CRO bots.
"""
from __future__ import annotations
import re
from html.parser import HTMLParser


# ─────────────────────────────────────────────────────────────────────────────
#  DOM HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def dom_y(element: dict) -> int:
    return int(
        (element.get("states", {}).get("default", {}).get("bbox", {}) or {}).get("y", 0)
    )


def dom_visible(element: dict) -> bool:
    bbox = (element.get("states", {}).get("default", {}).get("bbox", {}) or {})
    return bbox.get("width", 0) > 0 and bbox.get("height", 0) > 0


def dom_on_screen(element: dict) -> bool:
    return dom_y(element) > 0 and dom_visible(element)


def above_fold(element: dict, fold_px: int = 800) -> bool:
    y = dom_y(element)
    return 0 < y <= fold_px


def filter_cookie_els(elements: list) -> list:
    """Remove elements with y=0 and w=0 (typically cookie modal / off-screen)."""
    return [
        e for e in elements
        if not (dom_y(e) == 0 and not dom_visible(e))
    ]


# ─────────────────────────────────────────────────────────────────────────────
#  HTML PARSER  (single-pass extraction)
# ─────────────────────────────────────────────────────────────────────────────

class AuditParser(HTMLParser):
    """
    Single-pass HTML parser that extracts everything CRO bots need.
    Avoids re-parsing the HTML multiple times across bots.
    """

    def __init__(self):
        super().__init__()
        self.headings:   list[dict] = []   # {tag, text}
        self.links:      list[dict] = []   # {href, text}
        self.images:     list[dict] = []   # {src, alt, data_src}
        self.forms:      list[dict] = []   # {action, method}
        self.schema_raw: list[str]  = []   # raw LD+JSON strings
        self.og_tags:    list[dict] = []   # {property, content}
        self.twitter_tags: list[dict] = [] # {name, content}
        self.title_text: str        = ""
        self.meta_desc:  str        = ""
        self.tel_hrefs:  list[str]  = []

        self._in_title     = False
        self._in_script    = False
        self._script_type  = ""
        self._script_buf   = ""
        self._in_heading   = False
        self._heading_tag  = ""
        self._heading_buf  = ""
        self._in_link      = False
        self._link_href    = ""
        self._link_buf     = ""

    # ── Tag open ─────────────────────────────────────────────────────────────

    def handle_starttag(self, tag: str, attrs: list):
        a = dict(attrs)

        if tag == "title":
            self._in_title = True
            return

        if tag == "script":
            stype = a.get("type", "")
            if "ld+json" in stype:
                self._in_script   = True
                self._script_type = "ldjson"
                self._script_buf  = ""
            return

        if tag in ("h1","h2","h3","h4","h5","h6"):
            self._in_heading  = True
            self._heading_tag = tag
            self._heading_buf = ""
            return

        if tag == "a":
            href = a.get("href", "")
            self._in_link  = True
            self._link_href = href
            self._link_buf  = ""
            if href.startswith("tel:"):
                self.tel_hrefs.append(href)
            return

        if tag == "img":
            self.images.append({
                "src":      a.get("src", ""),
                "alt":      a.get("alt"),
                "data_src": a.get("data-src", ""),
            })
            return

        if tag == "form":
            self.forms.append({
                "action": a.get("action", ""),
                "method": a.get("method", "get"),
            })
            return

        if tag == "meta":
            prop    = a.get("property", "")
            name    = a.get("name", "")
            content = a.get("content", "")
            if prop.startswith("og:"):
                self.og_tags.append({"property": prop, "content": content})
            elif name.startswith("twitter:"):
                self.twitter_tags.append({"name": name, "content": content})
            elif name.lower() == "description":
                self.meta_desc = content

    # ── Tag close ────────────────────────────────────────────────────────────

    def handle_endtag(self, tag: str):
        if tag == "title":
            self._in_title = False
            return

        if tag == "script" and self._script_type == "ldjson":
            self.schema_raw.append(self._script_buf)
            self._in_script   = False
            self._script_type = ""
            self._script_buf  = ""
            return

        if tag in ("h1","h2","h3","h4","h5","h6") and self._in_heading:
            self.headings.append({
                "tag":  self._heading_tag,
                "text": self._heading_buf.strip(),
            })
            self._in_heading  = False
            self._heading_tag = ""
            self._heading_buf = ""
            return

        if tag == "a" and self._in_link:
            self.links.append({
                "href": self._link_href,
                "text": self._link_buf.strip(),
            })
            self._in_link   = False
            self._link_href = ""
            self._link_buf  = ""
            return

    # ── Data ─────────────────────────────────────────────────────────────────

    def handle_data(self, data: str):
        if self._in_title:
            self.title_text += data
        elif self._in_script and self._script_type == "ldjson":
            self._script_buf += data
        elif self._in_heading:
            self._heading_buf += data
        elif self._in_link:
            self._link_buf += data
