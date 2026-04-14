"""
Unit tests for the diagnose() pure function.

Coverage: 4 matrices × 6 scenarios = 24 tests minimum, plus error handling.
Each test calls diagnose() directly — no HTTP server involved.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.diagnose import SEGMENTS, diagnose

HERE = Path(__file__).resolve().parent.parent

with open(HERE / "reference_times.json") as f:
    REF = json.load(f)

MATRICES = ["4974", "5052", "5090", "5091"]


def _all_ok_piece(matrix: str) -> dict:
    """Build a piece whose partials exactly equal the reference (all OK)."""
    r = REF[matrix]
    t2 = r["furnace_to_2nd_strike"]
    t3 = t2 + r["2nd_to_3rd_strike"]
    t4 = t3 + r["3rd_to_4th_strike"]
    ta = t4 + r["4th_strike_to_aux_press"]
    tb = ta + r["aux_press_to_bath"]
    return {
        "piece_id": f"ok-{matrix}",
        "die_matrix": int(matrix),
        "lifetime_2nd_strike_s": round(t2, 2),
        "lifetime_3rd_strike_s": round(t3, 2),
        "lifetime_4th_strike_s": round(t4, 2),
        "lifetime_auxiliary_press_s": round(ta, 2),
        "lifetime_bath_s": round(tb, 2),
    }


def _penalized_piece(matrix: str, penalized_segment: str, bump: float = 2.5) -> dict:
    """Build a piece where exactly one segment is penalized (deviation ~bump s)."""
    r = REF[matrix]
    partials = {
        "furnace_to_2nd_strike": r["furnace_to_2nd_strike"],
        "2nd_to_3rd_strike": r["2nd_to_3rd_strike"],
        "3rd_to_4th_strike": r["3rd_to_4th_strike"],
        "4th_strike_to_aux_press": r["4th_strike_to_aux_press"],
        "aux_press_to_bath": r["aux_press_to_bath"],
    }
    partials[penalized_segment] = partials[penalized_segment] + bump

    t2 = partials["furnace_to_2nd_strike"]
    t3 = t2 + partials["2nd_to_3rd_strike"]
    t4 = t3 + partials["3rd_to_4th_strike"]
    ta = t4 + partials["4th_strike_to_aux_press"]
    tb = ta + partials["aux_press_to_bath"]
    return {
        "piece_id": f"{penalized_segment}-{matrix}",
        "die_matrix": int(matrix),
        "lifetime_2nd_strike_s": round(t2, 2),
        "lifetime_3rd_strike_s": round(t3, 2),
        "lifetime_4th_strike_s": round(t4, 2),
        "lifetime_auxiliary_press_s": round(ta, 2),
        "lifetime_bath_s": round(tb, 2),
    }


# ── 4 × 1 = 4 all-OK tests ─────────────────────────────────────────────────
@pytest.mark.parametrize("matrix", MATRICES)
def test_all_ok(matrix):
    piece = _all_ok_piece(matrix)
    result = diagnose(piece, REF)
    assert result["delay"] is False
    assert result["probable_causes"] == []
    for seg in result["segments"]:
        assert seg["penalized"] is False


# ── 4 × 5 = 20 single-segment penalized tests ─────────────────────────────
@pytest.mark.parametrize("matrix", MATRICES)
@pytest.mark.parametrize("segment", SEGMENTS)
def test_single_segment_penalized(matrix, segment):
    piece = _penalized_piece(matrix, segment, bump=2.5)
    result = diagnose(piece, REF)
    assert result["delay"] is True
    for seg in result["segments"]:
        if seg["segment"] == segment:
            assert seg["penalized"] is True, f"{segment} should be penalized"
            assert seg["deviation_s"] > 1.0
        else:
            assert seg["penalized"] is False, f"{seg['segment']} should be OK"
    assert len(result["probable_causes"]) > 0


# ── Extra: multi-segment + null scenarios ──────────────────────────────────
def test_multi_segment_with_null():
    """Two penalized segments + null lifetime creating two null downstream segments."""
    r = REF["5090"]
    lt2 = r["furnace_to_2nd_strike"] + 3.0
    lt3 = lt2 + (r["2nd_to_3rd_strike"] + 2.0)
    lt4 = lt3 + r["3rd_to_4th_strike"]
    piece = {
        "piece_id": "multi-null",
        "die_matrix": 5090,
        "lifetime_2nd_strike_s": round(lt2, 2),
        "lifetime_3rd_strike_s": round(lt3, 2),
        "lifetime_4th_strike_s": round(lt4, 2),
        "lifetime_auxiliary_press_s": None,
        "lifetime_bath_s": None,
    }
    result = diagnose(piece, REF)
    assert result["delay"] is True
    by_seg = {s["segment"]: s for s in result["segments"]}
    assert by_seg["furnace_to_2nd_strike"]["penalized"] is True
    assert by_seg["2nd_to_3rd_strike"]["penalized"] is True
    assert by_seg["3rd_to_4th_strike"]["penalized"] is False
    assert by_seg["4th_strike_to_aux_press"]["penalized"] is None
    assert by_seg["4th_strike_to_aux_press"]["actual_s"] is None
    assert by_seg["aux_press_to_bath"]["penalized"] is None


def test_deviation_over_5_is_null_anomaly():
    """deviation > 5.0 should be treated as sensor anomaly (penalized=null)."""
    r = REF["4974"]
    # Make furnace_to_2nd_strike = reference + 10 (anomaly)
    partials = [
        r["furnace_to_2nd_strike"] + 10.0,
        r["2nd_to_3rd_strike"],
        r["3rd_to_4th_strike"],
        r["4th_strike_to_aux_press"],
        r["aux_press_to_bath"],
    ]
    t = 0.0
    cum = []
    for p in partials:
        t += p
        cum.append(round(t, 2))
    piece = {
        "piece_id": "anomaly",
        "die_matrix": 4974,
        "lifetime_2nd_strike_s": cum[0],
        "lifetime_3rd_strike_s": cum[1],
        "lifetime_4th_strike_s": cum[2],
        "lifetime_auxiliary_press_s": cum[3],
        "lifetime_bath_s": cum[4],
    }
    result = diagnose(piece, REF)
    furnace_seg = [s for s in result["segments"] if s["segment"] == "furnace_to_2nd_strike"][0]
    assert furnace_seg["penalized"] is None  # anomaly, not a delay


def test_boundary_deviation_equals_1_is_false():
    """deviation == 1.0 is NOT penalized (rule is strict > 1.0)."""
    r = REF["4974"]
    partials = [
        r["furnace_to_2nd_strike"] + 1.0,  # deviation exactly 1.0
        r["2nd_to_3rd_strike"],
        r["3rd_to_4th_strike"],
        r["4th_strike_to_aux_press"],
        r["aux_press_to_bath"],
    ]
    t = 0.0
    cum = []
    for p in partials:
        t += p
        cum.append(round(t, 2))
    piece = {
        "piece_id": "boundary-1",
        "die_matrix": 4974,
        "lifetime_2nd_strike_s": cum[0],
        "lifetime_3rd_strike_s": cum[1],
        "lifetime_4th_strike_s": cum[2],
        "lifetime_auxiliary_press_s": cum[3],
        "lifetime_bath_s": cum[4],
    }
    result = diagnose(piece, REF)
    furnace = [s for s in result["segments"] if s["segment"] == "furnace_to_2nd_strike"][0]
    assert furnace["penalized"] is False
    assert result["delay"] is False


def test_boundary_deviation_equals_5_is_true():
    """deviation == 5.0 is penalized=True (rule: > 1.0 and <= 5.0)."""
    r = REF["5052"]
    partials = [
        r["furnace_to_2nd_strike"] + 5.0,  # deviation exactly 5.0
        r["2nd_to_3rd_strike"],
        r["3rd_to_4th_strike"],
        r["4th_strike_to_aux_press"],
        r["aux_press_to_bath"],
    ]
    t = 0.0
    cum = []
    for p in partials:
        t += p
        cum.append(round(t, 2))
    piece = {
        "piece_id": "boundary-5",
        "die_matrix": 5052,
        "lifetime_2nd_strike_s": cum[0],
        "lifetime_3rd_strike_s": cum[1],
        "lifetime_4th_strike_s": cum[2],
        "lifetime_auxiliary_press_s": cum[3],
        "lifetime_bath_s": cum[4],
    }
    result = diagnose(piece, REF)
    furnace = [s for s in result["segments"] if s["segment"] == "furnace_to_2nd_strike"][0]
    assert furnace["penalized"] is True
    assert result["delay"] is True


def test_negative_deviation_is_not_penalized():
    """Faster than reference (negative deviation) is penalized=False."""
    r = REF["5090"]
    partials = [
        r["furnace_to_2nd_strike"] - 2.0,  # 2s faster than reference
        r["2nd_to_3rd_strike"],
        r["3rd_to_4th_strike"],
        r["4th_strike_to_aux_press"],
        r["aux_press_to_bath"],
    ]
    t = 0.0
    cum = []
    for p in partials:
        t += p
        cum.append(round(t, 2))
    piece = {
        "piece_id": "fast",
        "die_matrix": 5090,
        "lifetime_2nd_strike_s": cum[0],
        "lifetime_3rd_strike_s": cum[1],
        "lifetime_4th_strike_s": cum[2],
        "lifetime_auxiliary_press_s": cum[3],
        "lifetime_bath_s": cum[4],
    }
    result = diagnose(piece, REF)
    furnace = [s for s in result["segments"] if s["segment"] == "furnace_to_2nd_strike"][0]
    assert furnace["penalized"] is False
    assert furnace["deviation_s"] < 0
    assert result["delay"] is False


def test_all_segments_penalized():
    """All 5 segments penalized -> delay=True, causes union in process order."""
    r = REF["4974"]
    partials = [p + 2.5 for p in [
        r["furnace_to_2nd_strike"],
        r["2nd_to_3rd_strike"],
        r["3rd_to_4th_strike"],
        r["4th_strike_to_aux_press"],
        r["aux_press_to_bath"],
    ]]
    t = 0.0
    cum = []
    for p in partials:
        t += p
        cum.append(round(t, 2))
    piece = {
        "piece_id": "all-bad",
        "die_matrix": 4974,
        "lifetime_2nd_strike_s": cum[0],
        "lifetime_3rd_strike_s": cum[1],
        "lifetime_4th_strike_s": cum[2],
        "lifetime_auxiliary_press_s": cum[3],
        "lifetime_bath_s": cum[4],
    }
    result = diagnose(piece, REF)
    assert result["delay"] is True
    for seg in result["segments"]:
        assert seg["penalized"] is True
    # Process-order cause check: first cause is from furnace_to_2nd_strike,
    # last cause is from aux_press_to_bath ("bath deposit")
    assert result["probable_causes"][0] == "Billet pick"
    assert result["probable_causes"][-1] == "bath deposit"


def test_middle_null_nullifies_two_adjacent_segments():
    """If lifetime_3rd_strike_s is null, both 2nd_to_3rd and 3rd_to_4th are null."""
    r = REF["5091"]
    piece = {
        "piece_id": "middle-null",
        "die_matrix": 5091,
        "lifetime_2nd_strike_s": r["furnace_to_2nd_strike"],
        "lifetime_3rd_strike_s": None,  # breaks two adjacent segments
        "lifetime_4th_strike_s": r["furnace_to_2nd_strike"] + r["2nd_to_3rd_strike"] + r["3rd_to_4th_strike"],
        "lifetime_auxiliary_press_s": r["furnace_to_2nd_strike"] + r["2nd_to_3rd_strike"] + r["3rd_to_4th_strike"] + r["4th_strike_to_aux_press"],
        "lifetime_bath_s": r["furnace_to_2nd_strike"] + r["2nd_to_3rd_strike"] + r["3rd_to_4th_strike"] + r["4th_strike_to_aux_press"] + r["aux_press_to_bath"],
    }
    result = diagnose(piece, REF)
    by_seg = {s["segment"]: s for s in result["segments"]}
    assert by_seg["furnace_to_2nd_strike"]["penalized"] is False
    assert by_seg["2nd_to_3rd_strike"]["penalized"] is None
    assert by_seg["2nd_to_3rd_strike"]["actual_s"] is None
    assert by_seg["3rd_to_4th_strike"]["penalized"] is None
    assert by_seg["3rd_to_4th_strike"]["actual_s"] is None
    assert by_seg["4th_strike_to_aux_press"]["penalized"] is False
    assert by_seg["aux_press_to_bath"]["penalized"] is False
    assert result["delay"] is False  # no penalized=True


def test_probable_causes_process_order():
    """When 2 non-adjacent segments are penalized, causes follow process order."""
    r = REF["5052"]
    partials = [
        r["furnace_to_2nd_strike"],
        r["2nd_to_3rd_strike"],
        r["3rd_to_4th_strike"] + 2.5,  # penalized
        r["4th_strike_to_aux_press"],
        r["aux_press_to_bath"] + 2.0,  # penalized (non-adjacent)
    ]
    t = 0.0
    cum = []
    for p in partials:
        t += p
        cum.append(round(t, 2))
    piece = {
        "piece_id": "order-check",
        "die_matrix": 5052,
        "lifetime_2nd_strike_s": cum[0],
        "lifetime_3rd_strike_s": cum[1],
        "lifetime_4th_strike_s": cum[2],
        "lifetime_auxiliary_press_s": cum[3],
        "lifetime_bath_s": cum[4],
    }
    result = diagnose(piece, REF)
    # 3rd_to_4th causes come first ("Retraction", "conservative trajectory", ...)
    # then aux_press_to_bath causes ("Retraction", "transport", ...)
    assert result["probable_causes"][0] == "Retraction"  # from 3rd_to_4th
    assert result["probable_causes"][1] == "conservative trajectory"
    assert "bath deposit" in result["probable_causes"]  # from aux_press_to_bath
    # bath deposit must come after conservative trajectory
    assert result["probable_causes"].index("bath deposit") > result["probable_causes"].index("conservative trajectory")


def test_unknown_die_matrix_raises():
    piece = {
        "piece_id": "unknown",
        "die_matrix": 9999,
        "lifetime_2nd_strike_s": 17.5,
        "lifetime_3rd_strike_s": 24.0,
        "lifetime_4th_strike_s": 37.2,
        "lifetime_auxiliary_press_s": 54.2,
        "lifetime_bath_s": 56.0,
    }
    with pytest.raises(ValueError, match="unknown die_matrix"):
        diagnose(piece, REF)


# ── Golden test: validation_pieces.csv → validation_expected.json ────────
def _load_validation():
    import csv
    csv_path = HERE / "validation_pieces.csv"
    json_path = HERE / "validation_expected.json"
    with open(csv_path) as f:
        reader = csv.DictReader(f)
        pieces = []
        for row in reader:
            piece = {"piece_id": row["piece_id"], "die_matrix": int(row["die_matrix"])}
            for col in [
                "lifetime_2nd_strike_s",
                "lifetime_3rd_strike_s",
                "lifetime_4th_strike_s",
                "lifetime_auxiliary_press_s",
                "lifetime_bath_s",
            ]:
                v = row[col]
                piece[col] = None if v == "" else float(v)
            pieces.append(piece)
    with open(json_path) as f:
        expected = json.load(f)
    return list(zip(pieces, expected))


@pytest.mark.parametrize("piece,expected", _load_validation(), ids=[f"P{i+1:03d}" for i in range(10)])
def test_golden_validation_set(piece, expected):
    """Golden test: every validation piece must produce its expected JSON output."""
    result = diagnose(piece, REF)

    # Round for comparison (1 decimal per the exam contract)
    def normalize(obj):
        if isinstance(obj, float):
            return round(obj, 1)
        if isinstance(obj, dict):
            return {k: normalize(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [normalize(v) for v in obj]
        return obj

    assert normalize(result) == normalize(expected)
