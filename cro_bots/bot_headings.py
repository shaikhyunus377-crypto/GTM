"""
Bot 2 — Heading Hierarchy
Checks: level skips, empty headings, cookie-modal headings polluting structure.
CRO framing: headings = the page's conversion sections table-of-contents.
Works on: all verticals.
"""
from __future__ import annotations
from .base import AuditParser, dom_y, filter_cookie_els


def run(p: AuditParser, dom_elements: list | None = None) -> dict | None:
    dom_els = dom_elements or []

    # Build a set of off-screen heading texts to exclude (cookie modals etc.)
    offscreen_texts: set[str] = set()
    if dom_els:
        dom_heads = [e for e in dom_els if e.get("tag") in ("h1","h2","h3","h4","h5","h6")]
        for dh in dom_heads:
            y    = dom_y(dh)
            text = (dh.get("text") or "").strip()
            if y == 0 and text:
                offscreen_texts.add(text.lower()[:50])

    visible = [
        h for h in p.headings
        if h["text"].strip()
        and h["text"].strip().lower()[:50] not in offscreen_texts
    ]

    skips    = []
    empties  = [h for h in p.headings if not h["text"].strip()]

    for i in range(1, len(visible)):
        prev_level = int(visible[i-1]["tag"][1])
        curr_level = int(visible[i]["tag"][1])
        if curr_level > prev_level + 1:
            skips.append({
                "from": visible[i-1]["tag"],
                "from_text": visible[i-1]["text"][:40],
                "to":   visible[i]["tag"],
                "to_text":   visible[i]["text"][:40],
            })

    findings = []
    evidence  = []

    if skips:
        for s in skips[:3]:
            findings.append(
                f"Heading jumps from {s['from'].upper()} (\"{s['from_text']}\") "
                f"to {s['to'].upper()} (\"{s['to_text']}\") — "
                "skipping levels breaks screen reader navigation and section hierarchy."
            )
            evidence.append(f"{s['from']} → {s['to']}: \"{s['from_text']}\" → \"{s['to_text']}\"")

    if empties:
        findings.append(
            f"{len(empties)} empty heading tag(s) found — "
            "screen readers announce them as blank sections."
        )
        evidence.append(f"Empty heading tags: {[h['tag'] for h in empties[:4]]}")

    if not findings:
        return None

    return {
        "id":               "heading_hierarchy",
        "title":            "Heading structure has level skips or empty tags",
        "severity":         "medium",
        "confidence":       "confirmed",
        "cro_impact":       "Screen reader navigation + content scannability",
        "revenue_signal":   "Logical heading structure improves scroll depth by ~18% (NNGroup).",
        "detection_source": "html+dom",
        "industry_tags":    ["all"],
        "fix_effort":       "hours",
        "affected_elements": [{"tag": h["tag"], "text": h.get("text","")[:40]} for h in (visible + empties)[:6]],
        "findings":         findings,
        "fix": (
            "Follow strict H1 → H2 → H3 nesting — never skip levels. "
            "Remove or fill empty heading tags. "
            "Use CSS margin/size for visual spacing — not extra heading levels."
        ),
        "evidence": evidence,
    }
