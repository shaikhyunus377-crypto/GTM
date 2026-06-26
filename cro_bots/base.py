"""Shared utilities for all CRO bots."""
from __future__ import annotations
import re
import json
from html.parser import HTMLParser


# ── DOM helpers ──────────────────────────────────────────────────────────────

def _bbox(el: dict) -> dict:
    return el.get("states", {}).get("default", {}).get("bbox", {}) or {}

def dom_y(el: dict) -> float:      return _bbox(el).get("y", 0)
def dom_x(el: dict) -> float:      return _bbox(el).get("x", 0)
def dom_width(el: dict) -> float:  return _bbox(el).get("width", 0)
def dom_height(el: dict) -> float: return _bbox(el).get("height", 0)

def dom_visible(el: dict) -> bool:
    """Element has non-zero width AND height."""
    return dom_width(el) > 0 and dom_height(el) > 0

def dom_on_screen(el: dict) -> bool:
    """Element is visible and has y > 0 (not hidden off-top)."""
    return dom_visible(el) and dom_y(el) > 0

def filter_cookie_els(elements: list) -> list:
    """Remove off-screen cookie-modal elements (y=0, width=0)."""
    return [e for e in elements if not (dom_y(e) == 0 and dom_width(e) == 0)]

def above_fold(el: dict, fold: int = 900) -> bool:
    """Element top edge is above the fold."""
    return 0 < dom_y(el) <= fold


# ── HTML parser ───────────────────────────────────────────────────────────────

class AuditParser(HTMLParser):
    """
    Single-pass HTML parser that extracts everything the bots need.
    Instantiate once per page; share across bots.
    """

    def __init__(self, html: str):
        super().__init__(convert_charrefs=True)
        # outputs
        self.title: str = ""
        self.meta_description: str = ""
        self.headings: list[dict] = []   # {tag, level, text}
        self.links: list[dict] = []      # {href, text}
        self.images: list[dict] = []     # {src, data_src, alt, width, height}
        self.forms: list[dict] = []      # {action, method, fields}
        self.schema_blocks: list[dict] = []
        self.og_tags: dict[str, str] = {}
        self.twitter_tags: dict[str, str] = {}
        self.tel_hrefs: list[str] = []
        self.inline_styles: list[str] = []

        # internal
        self._current_tag: str = ""
        self._current_attrs: dict = {}
        self._in_title = False
        self._in_script = False
        self._in_style = False
        self._script_type = ""
        self._buf: list[str] = []
        self._current_form: dict | None = None
        self._head_tag: str = ""

        self.feed(html)

    def _attrs_dict(self, attrs):
        return {k.lower(): (v or "") for k, v in attrs}

    def handle_starttag(self, tag, attrs):
        a = self._attrs_dict(attrs)
        self._current_tag = tag
        self._current_attrs = a

        if tag == "title":
            self._in_title = True
            self._buf = []
        elif tag in ("h1","h2","h3","h4","h5","h6"):
            self._head_tag = tag
            self._buf = []
        elif tag == "a":
            href = a.get("href","")
            if href.startswith("tel:"):
                self.tel_hrefs.append(href)
            self._buf = []
        elif tag == "img":
            self.images.append({
                "src":      a.get("src",""),
                "data_src": a.get("data-src",""),
                "alt":      a.get("alt", None),
                "width":    a.get("width",""),
                "height":   a.get("height",""),
                "loading":  a.get("loading",""),
            })
        elif tag == "meta":
            name  = a.get("name","").lower()
            prop  = a.get("property","").lower()
            content = a.get("content","")
            if name == "description":
                self.meta_description = content
            if prop.startswith("og:"):
                self.og_tags[prop[3:]] = content
            if name.startswith("twitter:"):
                self.twitter_tags[name[8:]] = content
        elif tag == "form":
            self._current_form = {"action": a.get("action",""), "method": a.get("method","get"), "fields": []}
            self.forms.append(self._current_form)
        elif tag in ("input","select","textarea"):
            if self._current_form is not None:
                self._current_form["fields"].append({
                    "type": a.get("type","text"), "name": a.get("name",""),
                    "required": "required" in a,
                })
        elif tag == "script":
            self._in_script = True
            self._script_type = a.get("type","")
            self._buf = []
        elif tag == "style":
            self._in_style = True
            self._buf = []

    def handle_endtag(self, tag):
        if tag == "title" and self._in_title:
            self.title = re.sub(r"<[^>]+>",""," ".join(self._buf)).strip()
            self._in_title = False
        elif tag in ("h1","h2","h3","h4","h5","h6") and tag == self._head_tag:
            text = " ".join(self._buf).strip()
            self.headings.append({"tag": tag, "level": int(tag[1]), "text": text})
            self._head_tag = ""
        elif tag == "a":
            text = " ".join(self._buf).strip()
            self.links.append({"href": self._current_attrs.get("href",""), "text": text})
        elif tag == "script" and self._in_script:
            raw = "".join(self._buf)
            if "ld+json" in self._script_type.lower() or "application/ld" in self._script_type.lower():
                try:
                    self.schema_blocks.append(json.loads(raw))
                except Exception:
                    pass
            self._in_script = False
        elif tag == "style" and self._in_style:
            self.inline_styles.append("".join(self._buf))
            self._in_style = False
        elif tag == "form":
            self._current_form = None

    def handle_data(self, data):
        if self._in_title or self._head_tag or self._current_tag == "a" or self._in_script or self._in_style:
            self._buf.append(data)
