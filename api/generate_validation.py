"""
Generate validation_pieces.csv and validation_expected.json programmatically
from reference_times.json and the §1.3 rules. Run this script once; do not
hand-edit the outputs.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

from src.diagnose import diagnose

HERE = Path(__file__).resolve().parent
REF_PATH = HERE / "reference_times.json"
CSV_PATH = HERE / "validation_pieces.csv"
JSON_PATH = HERE / "validation_expected.json"

with open(REF_PATH) as f:
    REF = json.load(f)


def cumulative_from_partials(partials: list[float | None]) -> list[float | None]:
    """Convert 5 partial times into 5 cumulative lifetime timestamps."""
    t = 0.0
    out: list[float | None] = []
    for p in partials:
        if p is None:
            out.append(None)
            t = None  # once None, downstream are None unless reset
        elif t is None:
            # Cannot compute further cumulative times without an anchor
            out.append(None)
        else:
            t = t + p
            out.append(round(t, 1))
    return out


def piece_rows() -> list[dict]:
    """Build the 10 validation pieces per the §1.4 coverage map."""
    rows = []

    # P001-P004: all-OK on each matrix - use reference values exactly
    for i, matrix in enumerate(["4974", "5052", "5090", "5091"], start=1):
        ref = REF[matrix]
        partials = [
            ref["furnace_to_2nd_strike"],
            ref["2nd_to_3rd_strike"],
            ref["3rd_to_4th_strike"],
            ref["4th_strike_to_aux_press"],
            ref["aux_press_to_bath"],
        ]
        cum = cumulative_from_partials(partials)
        rows.append(
            {
                "piece_id": f"P00{i}",
                "die_matrix": int(matrix),
                "lifetime_2nd_strike_s": cum[0],
                "lifetime_3rd_strike_s": cum[1],
                "lifetime_4th_strike_s": cum[2],
                "lifetime_auxiliary_press_s": cum[3],
                "lifetime_bath_s": cum[4],
            }
        )

    # P005: only furnace_to_2nd_strike penalized (on matrix 4974)
    ref = REF["4974"]
    partials = [
        ref["furnace_to_2nd_strike"] + 3.0,  # penalized: +3s
        ref["2nd_to_3rd_strike"],
        ref["3rd_to_4th_strike"],
        ref["4th_strike_to_aux_press"],
        ref["aux_press_to_bath"],
    ]
    cum = cumulative_from_partials(partials)
    rows.append(
        {
            "piece_id": "P005",
            "die_matrix": 4974,
            "lifetime_2nd_strike_s": cum[0],
            "lifetime_3rd_strike_s": cum[1],
            "lifetime_4th_strike_s": cum[2],
            "lifetime_auxiliary_press_s": cum[3],
            "lifetime_bath_s": cum[4],
        }
    )

    # P006: only 2nd_to_3rd_strike penalized (on matrix 5052)
    ref = REF["5052"]
    partials = [
        ref["furnace_to_2nd_strike"],
        ref["2nd_to_3rd_strike"] + 2.5,  # penalized
        ref["3rd_to_4th_strike"],
        ref["4th_strike_to_aux_press"],
        ref["aux_press_to_bath"],
    ]
    cum = cumulative_from_partials(partials)
    rows.append(
        {
            "piece_id": "P006",
            "die_matrix": 5052,
            "lifetime_2nd_strike_s": cum[0],
            "lifetime_3rd_strike_s": cum[1],
            "lifetime_4th_strike_s": cum[2],
            "lifetime_auxiliary_press_s": cum[3],
            "lifetime_bath_s": cum[4],
        }
    )

    # P007: only 3rd_to_4th_strike penalized (on matrix 5090)
    ref = REF["5090"]
    partials = [
        ref["furnace_to_2nd_strike"],
        ref["2nd_to_3rd_strike"],
        ref["3rd_to_4th_strike"] + 3.0,  # penalized
        ref["4th_strike_to_aux_press"],
        ref["aux_press_to_bath"],
    ]
    cum = cumulative_from_partials(partials)
    rows.append(
        {
            "piece_id": "P007",
            "die_matrix": 5090,
            "lifetime_2nd_strike_s": cum[0],
            "lifetime_3rd_strike_s": cum[1],
            "lifetime_4th_strike_s": cum[2],
            "lifetime_auxiliary_press_s": cum[3],
            "lifetime_bath_s": cum[4],
        }
    )

    # P008: only 4th_strike_to_aux_press penalized (on matrix 5091)
    ref = REF["5091"]
    partials = [
        ref["furnace_to_2nd_strike"],
        ref["2nd_to_3rd_strike"],
        ref["3rd_to_4th_strike"],
        ref["4th_strike_to_aux_press"] + 2.5,  # penalized
        ref["aux_press_to_bath"],
    ]
    cum = cumulative_from_partials(partials)
    rows.append(
        {
            "piece_id": "P008",
            "die_matrix": 5091,
            "lifetime_2nd_strike_s": cum[0],
            "lifetime_3rd_strike_s": cum[1],
            "lifetime_4th_strike_s": cum[2],
            "lifetime_auxiliary_press_s": cum[3],
            "lifetime_bath_s": cum[4],
        }
    )

    # P009: only aux_press_to_bath penalized (on matrix 4974)
    ref = REF["4974"]
    partials = [
        ref["furnace_to_2nd_strike"],
        ref["2nd_to_3rd_strike"],
        ref["3rd_to_4th_strike"],
        ref["4th_strike_to_aux_press"],
        ref["aux_press_to_bath"] + 2.0,  # penalized
    ]
    cum = cumulative_from_partials(partials)
    rows.append(
        {
            "piece_id": "P009",
            "die_matrix": 4974,
            "lifetime_2nd_strike_s": cum[0],
            "lifetime_3rd_strike_s": cum[1],
            "lifetime_4th_strike_s": cum[2],
            "lifetime_auxiliary_press_s": cum[3],
            "lifetime_bath_s": cum[4],
        }
    )

    # P010: multi-segment delay + a NULL cumulative timestamp.
    # We penalize furnace_to_2nd_strike and 2nd_to_3rd_strike, then null
    # lifetime_auxiliary_press_s so that both 4th_strike_to_aux_press and
    # aux_press_to_bath become None/null.
    ref = REF["5090"]
    lt2 = ref["furnace_to_2nd_strike"] + 3.0  # penalized
    lt3 = lt2 + (ref["2nd_to_3rd_strike"] + 2.0)  # penalized
    lt4 = lt3 + ref["3rd_to_4th_strike"]
    lta = None  # NULL -> downstream segments become null
    ltb = None  # required since lta is None
    rows.append(
        {
            "piece_id": "P010",
            "die_matrix": 5090,
            "lifetime_2nd_strike_s": round(lt2, 1),
            "lifetime_3rd_strike_s": round(lt3, 1),
            "lifetime_4th_strike_s": round(lt4, 1),
            "lifetime_auxiliary_press_s": lta,
            "lifetime_bath_s": ltb,
        }
    )

    return rows


def main():
    rows = piece_rows()

    # Write CSV
    fieldnames = [
        "piece_id",
        "die_matrix",
        "lifetime_2nd_strike_s",
        "lifetime_3rd_strike_s",
        "lifetime_4th_strike_s",
        "lifetime_auxiliary_press_s",
        "lifetime_bath_s",
    ]
    with open(CSV_PATH, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            # Empty for None so CSV has blank cells
            row_out = {k: ("" if v is None else v) for k, v in r.items()}
            w.writerow(row_out)

    # Run diagnose() on each and write expected JSON
    expected = [diagnose(r, REF) for r in rows]
    with open(JSON_PATH, "w") as f:
        json.dump(expected, f, indent=2)

    print(f"Wrote {CSV_PATH}")
    print(f"Wrote {JSON_PATH} ({len(expected)} pieces)")


if __name__ == "__main__":
    main()
