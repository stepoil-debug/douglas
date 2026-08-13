from __future__ import annotations

import re
from datetime import date
from typing import Any

from bs4 import Tag

DATE_RE = re.compile(r"\b(\d{1,2})\.\s*(\d{1,2})\.\s*(\d{4})\b")


def parse_section_date(value: Any) -> date | None:
    match = DATE_RE.search(str(value or ""))
    if not match:
        return None
    day, month, year = map(int, match.groups())
    try:
        return date(year, month, day)
    except ValueError:
        return None


def table_section_date(table: Tag) -> date | None:
    """Return the closest explicit dd.mm.yyyy date preceding a result table.

    TennisExplorer groups tables under visible calendar-date headings. Query-string
    date filters are not reliable enough by themselves; the same page can contain
    neighboring days. The closest preceding date heading is therefore the source of
    truth for the table's calendar day.
    """
    for attr in ("data-date", "data-day", "id"):
        parsed = parse_section_date(table.get(attr))
        if parsed:
            return parsed

    # Search backwards in document order. The first explicit date encountered is
    # the heading that owns this table. Bound the scan so unrelated footer/history
    # dates cannot leak in from far away.
    seen = 0
    for node in table.find_all_previous(string=True):
        text = str(node or "").strip()
        if not text:
            continue
        seen += 1
        parsed = parse_section_date(text)
        if parsed:
            return parsed
        if seen >= 80:
            break
    return None
