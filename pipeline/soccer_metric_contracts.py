"""Audited Opta-coordinate definitions, independent of database writes.

The audited legacy snapshot's box_entries_pass counts all-phase completed
passes ENDING inside the box, including within-box completions. Its intended
SQL open-play flag did not establish stored phase validity. The explicit
open-play predicates below are separate, versioned contracts; do not silently
change the legacy field without rebuilding historical observations.
"""
from __future__ import annotations

import math


def inside_box(x, y) -> bool:
    if x is None or y is None:
        return False
    return math.isfinite(float(x)) and math.isfinite(float(y)) and 83 <= float(x) <= 100 and 21 <= float(y) <= 79


def completed_open_play_box_pass(event: dict) -> bool:
    return (event.get("type") == "Pass" and event.get("outcome_type") == "Successful"
            and event.get("is_open_play") is True and inside_box(event.get("end_x"), event.get("end_y")))


def completed_open_play_box_entry(event: dict) -> bool:
    """New, separate definition for a future versioned raw-event rebuild."""
    if not completed_open_play_box_pass(event):
        return False
    x, y = event.get("x"), event.get("y")
    if x is None or y is None:
        return False  # Unknown origin cannot establish an entry.
    if not (math.isfinite(float(x)) and math.isfinite(float(y)) and 0 <= float(x) <= 100 and 0 <= float(y) <= 100):
        return False
    return not inside_box(x, y)
