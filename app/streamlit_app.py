"""
Forging Line — Piece Travel Time Dashboard

Displays processed pieces with predicted bath time and per-stage
timing detail.

Usage:
    uv run streamlit run app/streamlit_app.py
"""

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from vaultech_analysis.inference import Predictor

GOLD_FILE = PROJECT_ROOT / "data" / "gold" / "pieces.parquet"

# Column definitions — process order
PARTIAL_COLS = [
    "partial_furnace_to_2nd_strike_s",
    "partial_2nd_to_3rd_strike_s",
    "partial_3rd_to_4th_strike_s",
    "partial_4th_strike_to_auxiliary_press_s",
    "partial_auxiliary_press_to_bath_s",
]
PARTIAL_LABELS = [
    "Furnace → 2nd strike",
    "2nd strike → 3rd strike",
    "3rd strike → 4th strike",
    "4th strike → Aux. press",
    "Aux. press → Bath",
]
CUMULATIVE_COLS = [
    "lifetime_2nd_strike_s",
    "lifetime_3rd_strike_s",
    "lifetime_4th_strike_s",
    "lifetime_auxiliary_press_s",
    "lifetime_bath_s",
]
CUMULATIVE_LABELS = [
    "2nd strike (1st op)",
    "3rd strike (2nd op)",
    "4th strike (drill)",
    "Auxiliary press",
    "Bath",
]


@st.cache_resource
def load_predictor() -> Predictor:
    return Predictor()


@st.cache_data
def load_data() -> pd.DataFrame:
    predictor = load_predictor()
    df = pd.read_parquet(GOLD_FILE)
    df["predicted_bath_s"] = predictor.predict_batch(df)
    df["prediction_error_s"] = df["lifetime_bath_s"] - df["predicted_bath_s"]
    return df


@st.cache_data
def get_reference() -> pd.DataFrame:
    df = load_data()
    ref_cols = PARTIAL_COLS + CUMULATIVE_COLS
    return df.groupby("die_matrix")[ref_cols].median()


# ── Page config ──────────────────────────────────────────────────────────────
st.set_page_config(page_title="Forging Line Dashboard", layout="wide")
st.title("Forging Line — Piece Travel Time Dashboard")

# ── Load data ────────────────────────────────────────────────────────────────
df = load_data()
reference = get_reference()

# ── Sidebar filters ──────────────────────────────────────────────────────────
st.sidebar.header("Filters")

all_matrices = sorted(df["die_matrix"].unique().tolist())
selected_matrices = st.sidebar.multiselect(
    "Die matrix", all_matrices, default=all_matrices
)

min_date = df["timestamp"].min().date()
max_date = df["timestamp"].max().date()
date_range = st.sidebar.date_input(
    "Date range", value=(min_date, max_date), min_value=min_date, max_value=max_date
)

slow_only = st.sidebar.checkbox("Show slow pieces only (bath > 90th pct)")

# ── Apply filters ────────────────────────────────────────────────────────────
filtered = df[df["die_matrix"].isin(selected_matrices)].copy()

if len(date_range) == 2:
    start_date, end_date = date_range
    filtered = filtered[
        (filtered["timestamp"].dt.date >= start_date)
        & (filtered["timestamp"].dt.date <= end_date)
    ]

if slow_only:
    p90 = filtered.groupby("die_matrix")["lifetime_bath_s"].transform(
        lambda x: x.quantile(0.9)
    )
    filtered = filtered[filtered["lifetime_bath_s"] > p90]

# ── Summary metrics ──────────────────────────────────────────────────────────
if filtered.empty:
    st.warning("No pieces match the current filters.")
    st.stop()

col1, col2, col3, col4 = st.columns(4)
col1.metric("Total pieces", f"{len(filtered):,}")
col2.metric("Median bath time", f"{filtered['lifetime_bath_s'].median():.1f} s")
col3.metric("Median predicted", f"{filtered['predicted_bath_s'].median():.1f} s")
col4.metric("MAE", f"{filtered['prediction_error_s'].abs().mean():.2f} s")

st.divider()

# ── Pieces table ─────────────────────────────────────────────────────────────
st.subheader("Pieces")

table_df = filtered[[
    "timestamp", "piece_id", "die_matrix",
    "lifetime_bath_s", "predicted_bath_s", "prediction_error_s", "oee_cycle_time_s"
]].copy()

table_df = table_df.rename(columns={
    "timestamp": "Timestamp",
    "piece_id": "Piece ID",
    "die_matrix": "Die Matrix",
    "lifetime_bath_s": "Actual Bath (s)",
    "predicted_bath_s": "Predicted Bath (s)",
    "prediction_error_s": "Error (s)",
    "oee_cycle_time_s": "OEE Cycle (s)",
})

table_df["Timestamp"] = table_df["Timestamp"].dt.strftime("%Y-%m-%d %H:%M:%S")
table_df = table_df.reset_index(drop=True)

event = st.dataframe(
    table_df,
    use_container_width=True,
    hide_index=True,
    on_select="rerun",
    selection_mode="single-row",
)

# ── Piece detail panel ───────────────────────────────────────────────────────
selected_rows = event.selection.get("rows", []) if event.selection else []

if not selected_rows:
    st.info("Select a piece from the table above to see its per-stage timing detail.")
else:
    row_idx = selected_rows[0]
    piece = filtered.iloc[row_idx]
    matrix = piece["die_matrix"]
    ref = reference.loc[matrix]

    st.divider()
    st.subheader(f"Piece detail — ID {piece['piece_id']}  |  Die {matrix}  |  {piece['timestamp'].strftime('%Y-%m-%d %H:%M')}")

    # ── Cumulative times ──────────────────────────────────────────────────────
    st.markdown("**Cumulative travel times vs die matrix reference**")
    cum_rows = []
    for col, label in zip(CUMULATIVE_COLS, CUMULATIVE_LABELS):
        actual = piece[col]
        ref_val = ref[col]
        deviation = actual - ref_val
        cum_rows.append({
            "Stage": label,
            "Actual (s)": round(actual, 2),
            "Reference (s)": round(ref_val, 2),
            "Deviation (s)": round(deviation, 2),
        })
    cum_df = pd.DataFrame(cum_rows)
    st.dataframe(cum_df, use_container_width=True, hide_index=True)

    # ── Partial times ─────────────────────────────────────────────────────────
    st.markdown("**Partial times between stages vs die matrix reference**")
    partial_rows = []
    slow_threshold = 1.5  # seconds above reference = "slow"
    for col, label in zip(PARTIAL_COLS, PARTIAL_LABELS):
        actual = piece[col]
        ref_val = ref[col]
        deviation = actual - ref_val
        status = "🔴 Slow" if deviation > slow_threshold else "✅ OK"
        partial_rows.append({
            "Segment": label,
            "Actual (s)": round(actual, 2),
            "Reference (s)": round(ref_val, 2),
            "Deviation (s)": round(deviation, 2),
            "Status": status,
        })
    partial_df = pd.DataFrame(partial_rows)
    st.dataframe(partial_df, use_container_width=True, hide_index=True)

    # ── Bar chart — process synoptic ──────────────────────────────────────────
    st.markdown("**Process synoptic — actual vs reference partial times**")
    chart_df = pd.DataFrame({
        "Segment": PARTIAL_LABELS,
        "Actual (s)": [piece[c] for c in PARTIAL_COLS],
        "Reference (s)": [ref[c] for c in PARTIAL_COLS],
    }).set_index("Segment")
    st.bar_chart(chart_df, use_container_width=True)

    # ── Inference debug panel ─────────────────────────────────────────────────
    st.divider()
    st.markdown("**Inference debug — SageMaker endpoint**")
    predictor = load_predictor()
    debug_result = predictor.predict(
        die_matrix=int(piece["die_matrix"]),
        lifetime_2nd_strike_s=float(piece["lifetime_2nd_strike_s"]),
        oee_cycle_time_s=float(piece["oee_cycle_time_s"]),
    )
    if "debug" in debug_result:
        dbg = debug_result["debug"]
        col_a, col_b, col_c = st.columns(3)
        col_a.metric("Endpoint", dbg["endpoint_name"])
        col_b.metric("Predicted bath (s)", debug_result["predicted_bath_time_s"])
        col_c.metric("Latency (ms)", dbg["latency_ms"])
        st.code(f"Payload sent:     {dbg['payload']}\nRaw response:     {dbg['raw_response']}", language="text")
