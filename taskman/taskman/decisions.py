"""Read a replayed decision's supersession state — one reading for every view.

`decision.supersede` events fold into ``superseded_by`` (``part`` None = whole
decision); `decision.amend` events fold into ``amendments`` after replacing
the text, so callers already read the current text from the plain fields.
"""

from __future__ import annotations


def replaced_by(dec: dict) -> int | None:
    """Id of the decision that wholly replaces ``dec`` (latest wins), else None."""
    whole = [s["by"] for s in dec.get("superseded_by") or [] if s.get("part") is None]
    return whole[-1] if whole else None


def partly_replaced_by(dec: dict) -> list[tuple[int, str]]:
    """(by, part) for every partial supersession, oldest first."""
    return [(s["by"], s["part"]) for s in dec.get("superseded_by") or []
            if s.get("part") is not None]


def status_tag(dec: dict) -> str:
    """Short marker for one-line listings: '' when the decision stands untouched."""
    marks = []
    by = replaced_by(dec)
    if by is not None:
        marks.append(f"superseded by #{by}")
    marks.extend(f"partly superseded by #{b}" for b, _part in partly_replaced_by(dec))
    if dec.get("amendments"):
        marks.append("amended")
    return f"[{'; '.join(marks)}]" if marks else ""
