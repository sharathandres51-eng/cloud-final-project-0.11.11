"""
Pure diagnose() function for the Forging Line Delay Diagnostics API.

Given a piece with cumulative timestamps and a reference_times lookup,
compute partial times, compare to reference, and return the diagnosis.
"""

from __future__ import annotations

from typing import Any

# Segment definitions in canonical process order
SEGMENTS = [
    "furnace_to_2nd_strike",
    "2nd_to_3rd_strike",
    "3rd_to_4th_strike",
    "4th_strike_to_aux_press",
    "aux_press_to_bath",
]

# Cause table from §1.1 of FINAL_EXAM.md
CAUSE_TABLE: dict[str, list[str]] = {
    "furnace_to_2nd_strike": [
        "Billet pick",
        "gripper close",
        "grip retries",
        "trajectory",
        "permissions",
        "queues",
    ],
    "2nd_to_3rd_strike": [
        "Retraction",
        "gripper",
        "press/PLC handshake",
        "wait points",
        "regrip",
    ],
    "3rd_to_4th_strike": [
        "Retraction",
        "conservative trajectory",
        "synchronization",
        "positioning",
        "confirmations",
    ],
    "4th_strike_to_aux_press": [
        "Pick micro-corrections",
        "transfer",
        "queue at Auxiliary Press entry",
        "interlocks",
    ],
    "aux_press_to_bath": [
        "Retraction",
        "transport",
        "bath queues",
        "permissions",
        "bath deposit",
    ],
}


def _partial_times(piece: dict[str, Any]) -> dict[str, float | None]:
    """Derive partial times from cumulative timestamps (§1.5)."""
    t2 = piece.get("lifetime_2nd_strike_s")
    t3 = piece.get("lifetime_3rd_strike_s")
    t4 = piece.get("lifetime_4th_strike_s")
    ta = piece.get("lifetime_auxiliary_press_s")
    tb = piece.get("lifetime_bath_s")

    def sub(a, b):
        if a is None or b is None:
            return None
        return a - b

    return {
        "furnace_to_2nd_strike": t2,  # absolute
        "2nd_to_3rd_strike": sub(t3, t2),
        "3rd_to_4th_strike": sub(t4, t3),
        "4th_strike_to_aux_press": sub(ta, t4),
        "aux_press_to_bath": sub(tb, ta),
    }


def _classify(actual: float | None, reference: float) -> tuple[float | None, bool | None]:
    """
    Apply the §1.3 per-segment rule.

    Returns (deviation, penalized).
    - actual is None -> (None, None)
    - deviation > 5.0 -> (deviation, None)  [sensor anomaly]
    - 1.0 < deviation <= 5.0 -> (deviation, True)
    - deviation <= 1.0 -> (deviation, False)
    """
    if actual is None:
        return None, None
    deviation = actual - reference
    if deviation > 5.0:
        return deviation, None
    if deviation > 1.0:
        return deviation, True
    return deviation, False


def diagnose(piece: dict[str, Any], reference_times: dict[str, dict[str, float]]) -> dict[str, Any]:
    """
    Apply the delay-detection rule to a single piece.

    Args:
        piece: dict with keys piece_id, die_matrix, and 5 lifetime_*_s fields (nullable).
        reference_times: {die_matrix_str: {segment: ref_seconds}}.

    Returns:
        Response dict matching the §1.4 schema.

    Raises:
        ValueError: if die_matrix is unknown.
    """
    piece_id = piece.get("piece_id")
    die_matrix = piece.get("die_matrix")

    matrix_key = str(int(die_matrix)) if die_matrix is not None else None
    if matrix_key not in reference_times:
        raise ValueError(f"unknown die_matrix {die_matrix}")

    refs = reference_times[matrix_key]
    partials = _partial_times(piece)

    segments_out = []
    penalized_segments = []
    any_penalized = False

    for seg in SEGMENTS:
        actual = partials[seg]
        ref_val = refs[seg]
        deviation, penalized = _classify(actual, ref_val)

        def _r(x):
            if x is None:
                return None
            r = round(x, 1)
            return 0.0 if r == 0.0 else r  # normalize -0.0 to 0.0

        segments_out.append(
            {
                "segment": seg,
                "actual_s": _r(actual),
                "reference_s": _r(ref_val),
                "deviation_s": _r(deviation),
                "penalized": penalized,
            }
        )

        if penalized is True:
            penalized_segments.append(seg)
            any_penalized = True

    # probable_causes: union of cause lists from penalized segments, in process order
    probable_causes: list[str] = []
    for seg in penalized_segments:
        probable_causes.extend(CAUSE_TABLE[seg])

    return {
        "piece_id": piece_id,
        "die_matrix": int(die_matrix),
        "delay": any_penalized,
        "segments": segments_out,
        "probable_causes": probable_causes,
    }
