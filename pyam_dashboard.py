
# streamlit_app.py
# ------------------------------------------------------------
# PyAM-style comparator dashboard for Activity/Capacity/Emissions
# ------------------------------------------------------------
# Features
# - Upload multiple CSV/XLSX files in IAMC/pyam "wide" or "long" format
# - Filter by Model, Scenario, Region
# - Choose a top-level category: Activity, Capacity, Emissions
# - Aggregate by the next level down (e.g., "electricity" or emission species)
# - Optional breakdown of Level-3+ technologies inside the graph
# - Compare datasets (overlay, facet, or stack) and choose chart type
# - Download the aggregated data
#
# Run: streamlit run streamlit_app.py
#
# Notes:
# - If your data is in "wide" years (e.g., 2025,2030,... as columns),
#   this app melts to long format with columns: year,value.
# - If your data is already "long" with columns (year or time) & value, it is used directly.
# - "Variable" strings are parsed as Category|Level2|Level3|...
#   Category must be one of: Activity, Capacity, Emissions.
# ------------------------------------------------------------

from __future__ import annotations

from typing import Dict, Tuple

import pandas as pd
import streamlit as st
import plotly.express as px

try:
    import pyam  # type: ignore
    _HAS_PYAM = True
except Exception:
    _HAS_PYAM = False


# ------------------------------
# Helpers
# ------------------------------

TOP_LEVELS = ["Activity", "Capacity", "Emissions"]

def _is_year(col: str) -> bool:
    try:
        y = int(str(col))
        return 1800 <= y <= 2200
    except Exception:
        return False

def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Standardize column names (case-insensitive) to: Model, Scenario, Region, Variable, Unit, ... years/time/value.
    Returns a copy.
    """
    df = df.copy()
    rename_map = {}
    for c in df.columns:
        lc = str(c).strip().lower()
        if lc in ("model",): rename_map[c] = "Model"
        elif lc in ("scenario",): rename_map[c] = "Scenario"
        elif lc in ("region", "area", "location"): rename_map[c] = "Region"
        elif lc in ("variable", "var"): rename_map[c] = "Variable"
        elif lc in ("unit", "units"): rename_map[c] = "Unit"
        elif lc in ("time", "year"): rename_map[c] = "Year"
        elif lc in ("value", "val"): rename_map[c] = "Value"
    df = df.rename(columns=rename_map)
    return df

def _to_long_format(df: pd.DataFrame) -> pd.DataFrame:
    """Convert a pyam-style 'wide' or 'long' dataframe into a unified long format:
       Columns: Model, Scenario, Region, Variable, Unit, Year, Value
    """
    df = _normalize_columns(df)

    must_have = {"Model","Scenario","Region","Variable","Unit"}
    if not must_have.issubset(set(df.columns)):
        missing = must_have - set(df.columns)
        raise ValueError(f"Missing required columns: {sorted(missing)}")

    # If already long with Year/Value columns
    if {"Year","Value"}.issubset(df.columns):
        out = df.copy()
        # Coerce Year
        out["Year"] = out["Year"].apply(lambda x: int(str(x)[:4]) if pd.notna(x) else x)
        out = out.dropna(subset=["Year","Value"])
        return out[["Model","Scenario","Region","Variable","Unit","Year","Value"]]

    # Otherwise, assume wide across year columns
    year_cols = [c for c in df.columns if _is_year(str(c))]
    if not year_cols:
        raise ValueError("Could not find year columns or Year/Value; please include either wide year columns or a 'Year'/'Value' pair.")

    id_cols = ["Model","Scenario","Region","Variable","Unit"]
    m = df.melt(id_vars=id_cols, value_vars=year_cols, var_name="Year", value_name="Value")
    m["Year"] = m["Year"].astype(int)
    # Drop missing values
    m = m.dropna(subset=["Value"])
    return m[["Model","Scenario","Region","Variable","Unit","Year","Value"]]

def _split_variable(var: str) -> Tuple[str,str,str]:
    """Split Variable into (Category, Level2, RemainderLevel3Plus).
       - If missing parts, fill with "Total" appropriately.
    """
    parts = str(var).split("|")
    cat = parts[0] if parts else "Unknown"
    lvl2 = parts[1] if len(parts) > 1 else "Total"
    remainder = "|".join(parts[2:]) if len(parts) > 2 else ""
    return cat, lvl2, remainder

def prepare_dataset(df: pd.DataFrame, dataset_name: str) -> pd.DataFrame:
    """Parse into long format and add helper columns for Category/Level2/Level3Plus + dataset name."""
    long = _to_long_format(df)
    long["dataset"] = dataset_name
    # Parse variable hierarchy
    splits = long["Variable"].apply(_split_variable)
    long["Category"] = splits.map(lambda t: t[0])
    long["Level2"] = splits.map(lambda t: t[1])
    long["Level3Plus"] = splits.map(lambda t: t[2])
    return long

def aggregate(df: pd.DataFrame, category: str, filters: Dict, detail: str) -> pd.DataFrame:
    """Aggregate by the chosen detail level.
       detail: "Level2" or "Level3Plus".
       - Always keep Level2 in group (for x/facet), add Level3Plus when requested.
       - When detail == Level3Plus, drop rows without Level3Plus (i.e., totals) to avoid double counting.
    """
    use = df[df["Category"] == category].copy()

    if filters.get("models"):
        use = use[use["Model"].isin(filters["models"])]
    if filters.get("scenarios"):
        use = use[use["Scenario"].isin(filters["scenarios"])]
    if filters.get("regions"):
        use = use[use["Region"].isin(filters["regions"])]

    # Filter Level2 selection first
    if filters.get("level2s"):
        use = use[use["Level2"].isin(filters["level2s"])]

    grp_cols = ["dataset","Model","Scenario","Region","Unit","Year","Level2"]

    if detail == "Level3Plus":
        # Keep only rows with a non-empty Level3Plus label
        use = use[use["Level3Plus"].fillna('').str.len() > 0]
        # Optional filter on specific technologies
        if filters.get("level3s"):
            use = use[use["Level3Plus"].isin(filters["level3s"])]
        grp_cols.append("Level3Plus")

    g = (
        use.groupby(grp_cols, dropna=False)["Value"]
        .sum()
        .reset_index()
        .sort_values(grp_cols + ["Value"])
    )
    return g

def _unit_warning(selected: pd.DataFrame) -> str | None:
    units = selected["Unit"].dropna().unique().tolist()
    if len(units) > 1:
        return f"Multiple units found in selection: {units}. Data are not converted."
    return None

def _default_year(selected: pd.DataFrame) -> int:
    years = sorted(selected["Year"].dropna().unique().tolist())
    return years[-1] if years else 2050

def _y_axis_label(df: pd.DataFrame) -> str:
    """Choose a y-axis label based on Unit column in the current view."""
    units = df["Unit"].dropna().unique().tolist()
    if len(units) == 1:
        return units[0]
    elif len(units) == 0:
        return "Value"
    else:
        return "Value (mixed units)"


# ------------------------------
# Streamlit UI
# ------------------------------

st.set_page_config(page_title="PyAM Comparator", layout="wide")
st.title("📊 PyAM-style Comparator: Activity / Capacity / Emissions")

with st.sidebar:
    st.header("1) Upload files")
    st.caption("Upload one or more CSV or Excel (.xlsx) files in IAMC/pyam format.")
    uploads = st.file_uploader("Choose file(s)", type=["csv","xlsx"], accept_multiple_files=True)

    st.markdown("---")
    st.header("2) Select filters")
    category = st.selectbox("Top-level category", TOP_LEVELS, index=0)
    chart_type = st.selectbox(
        "Chart type (pyam-style)",
        [
            "Stacked Area (time)",
            "Line (time)",
            "Stacked Bar (single year)",
            "Grouped Bar (single year)",
        ],
        index=0
    )
    overlay_mode = st.selectbox(
        "Compare datasets by",
        [
            "Overlay (datasets as separate traces)",
            "Facet by dataset",
            "Stack within dataset"
        ],
        index=0
    )

    detail = st.radio(
        "Aggregation detail",
        ["Level-2 (sum technologies)", "Level-3+ (technology breakdown)"],
        index=0
    )

    facet_level2 = st.checkbox("Facet by Level-2 (columns) — only when showing technologies", value=False)

    region_view = st.radio(
        "Region comparison",
        [
            "Aggregate selected regions (sum)",
            "Compare regions side-by-side",
        ],
        index=0,
        help="Choose whether to sum all selected Regions together or show one panel per Region."
    )

    st.markdown("---")
    st.caption("Tip: Use Level-3+ breakdown to see technology composition within each Level-2 category.")

# Sample data message
if not uploads:
    st.info("👉 Upload one or more files to get started. This app accepts pyam-style CSV/XLSX files.")

# ------------------------------
# Load and combine datasets
# ------------------------------
frames = []
if uploads:
    for file in uploads:
        try:
            # Try reading CSV or Excel
            if file.name.lower().endswith(".xlsx"):
                df_raw = pd.read_excel(file)
            else:
                df_raw = pd.read_csv(file)

            prepared = prepare_dataset(df_raw, dataset_name=file.name)
            frames.append(prepared)
        except Exception as e:
            st.error(f"Failed to load {file.name}: {e}")

if not frames:
    st.stop()

data = pd.concat(frames, ignore_index=True)

# Dynamic filter widgets
models = sorted(data["Model"].dropna().unique().tolist())
scenarios = sorted(data["Scenario"].dropna().unique().tolist())
regions = sorted(data["Region"].dropna().unique().tolist())

col1, col2, col3 = st.columns(3)
with col1:
    pick_models = st.multiselect("Model(s)", options=models, default=models)
with col2:
    pick_scenarios = st.multiselect("Scenario(s)", options=scenarios, default=scenarios)
with col3:
    pick_regions = st.multiselect("Region(s)", options=regions, default=regions)

# Level2 depends on category
level2_all = sorted(data.loc[data["Category"] == category, "Level2"].dropna().unique().tolist())
level2_pick = st.multiselect("Level-2 selection", options=level2_all, default=level2_all)

# Optional technology (Level-3+) filter with search
pick_level3 = None
if detail.startswith("Level-3+"):
    # All technologies within the chosen Category and Level-2 selection
    level3_all = sorted(
        data.loc[
            (data["Category"] == category)
            & (data["Level3Plus"].notna())
            & (data["Level3Plus"] != "")
            & (data["Level2"].isin(level2_pick)),
            "Level3Plus",
        ].unique().tolist()
    )

    if level3_all:
        with st.expander("🔍 Technology filter (Level-3+)", expanded=False):
            search_term = st.text_input(
                "Search technologies (substring, case-insensitive)",
                value="",
                key="tech_search",
            )
            level3_options = level3_all
            if search_term:
                s = search_term.lower()
                level3_options = [t for t in level3_all if s in t.lower()]
                if not level3_options:
                    st.info("No technologies match this search; showing full list.")
                    level3_options = level3_all

            pick_level3 = st.multiselect(
                "Select technologies",
                options=level3_options,
                default=level3_options,
                help="Hold Ctrl/Cmd to select multiple technologies.",
            )

# Filters passed to the aggregation step
filters = dict(
    models=pick_models,
    scenarios=pick_scenarios,
    regions=pick_regions,
    level2s=level2_pick,
    level3s=pick_level3,
)

detail_key = "Level3Plus" if detail.startswith("Level-3+") else "Level2"
agg = aggregate(data, category=category, filters=filters, detail=detail_key)

# Optionally aggregate across Regions into a single total
if region_view.startswith("Aggregate"):
    group_cols_no_region = [c for c in agg.columns if c not in ("Region", "Value")]
    agg = (
        agg.groupby(group_cols_no_region, dropna=False)["Value"]
        .sum()
        .reset_index()
    )

# Warn if units inconsistent
warn = _unit_warning(agg)
if warn:
    st.warning(warn)

# ------------------------------
# Visualization
# ------------------------------
if agg.empty:
    st.warning("No data after filtering.")
    st.stop()

# Select single year for bar charts
single_year_default = _default_year(agg)
if "Bar" in chart_type:
    single_year = st.slider(
        "Select year for bar charts",
        min_value=int(agg["Year"].min()),
        max_value=int(agg["Year"].max()),
        value=int(single_year_default),
        step=5,
    )
    agg_view = agg[agg["Year"] == single_year].copy()
else:
    single_year = None
    agg_view = agg.copy()

# Y-axis label from units
y_axis_label = _y_axis_label(agg_view)

# Encodings
is_time = "time" in chart_type.lower()
x = "Year" if is_time else "Level2"

# Color dimension
color_dim = "Level2" if detail_key == "Level2" else "Level3Plus"

# Facet behavior
facet_col = None
facet_row = None

# When comparing Regions, show one panel per Region
if region_view == "Compare regions side-by-side" and "Region" in agg_view.columns:
    facet_col = "Region"
# Otherwise, fall back to dataset/Level-2 faceting
else:
    if overlay_mode == "Facet by dataset":
        facet_col = "dataset"
    elif detail_key == "Level3Plus" and facet_level2:
        facet_col = "Level2"

hover_data = ["dataset","Unit","Model","Scenario","Level2"]
if "Region" in agg_view.columns:
    hover_data.append("Region")
if "Level3Plus" in agg_view.columns:
    hover_data.append("Level3Plus")

title = f"{category} — {'Level-2' if detail_key=='Level2' else 'Technology'} breakdown"
subtitle = f"Models: {', '.join(pick_models)} | Scenarios: {', '.join(pick_scenarios)} | Regions: {', '.join(pick_regions)}"
if single_year is not None:
    subtitle += f" | Year: {single_year}"
if y_axis_label and y_axis_label not in ("Value","Value (mixed units)"):
    subtitle += f" | Units: {y_axis_label}"

px_labels = {"Value": y_axis_label, "Year": "Year", "Level2": "Level-2", "Level3Plus": "Technology"}

# Plot
if chart_type == "Stacked Area (time)":
    fig = px.area(
        agg_view, x="Year", y="Value", color=color_dim, facet_col=facet_col, facet_row=facet_row,
        line_group="dataset" if overlay_mode == "Overlay (datasets as separate traces)" else None,
        hover_data=hover_data, markers=False, labels=px_labels, title=title
    )
    fig.update_layout(title={'text': f"{title}<br><sup>{subtitle}</sup>"})
    st.plotly_chart(fig, width='stretch')

elif chart_type == "Line (time)":
    fig = px.line(
        agg_view, x="Year", y="Value", color=color_dim, facet_col=facet_col, facet_row=facet_row,
        line_dash="dataset" if overlay_mode == "Overlay (datasets as separate traces)" else None,
        hover_data=hover_data, markers=True, labels=px_labels, title=title
    )
    fig.update_layout(title={'text': f"{title}<br><sup>{subtitle}</sup>"})
    st.plotly_chart(fig, width='stretch')

elif chart_type == "Stacked Bar (single year)":
    # Always show Level-2 on x; stack Level3Plus if in breakdown mode
    bar_color = color_dim if detail_key == "Level3Plus" else (color_dim if overlay_mode=="Stack within dataset" else "dataset")
    fig = px.bar(
        agg_view, x="Level2", y="Value", color=bar_color, facet_col=facet_col, facet_row=facet_row,
        hover_data=hover_data, barmode="relative", labels=px_labels, title=title
    )
    fig.update_layout(title={'text': f"{title}<br><sup>{subtitle}</sup>"})
    st.plotly_chart(fig, width='stretch')

elif chart_type == "Grouped Bar (single year)":
    # Grouped by Level2; color by dataset for overlay, otherwise by color_dim
    bar_color = "dataset" if overlay_mode != "Stack within dataset" else color_dim
    fig = px.bar(
        agg_view, x="Level2", y="Value", color=bar_color, facet_col=facet_col, facet_row=facet_row,
        hover_data=hover_data, barmode="group", labels=px_labels, title=title
    )
    fig.update_layout(title={'text': f"{title}<br><sup>{subtitle}</sup>"})
    st.plotly_chart(fig, width='stretch')

# Display a tidy data preview & download
st.subheader("Aggregated data (preview)")
st.dataframe(
    agg_view.sort_values([c for c in ["dataset","Model","Scenario","Region","Unit","Level2","Level3Plus","Year"] if c in agg_view.columns])
)

@st.cache_data
def to_csv_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode("utf-8")

st.download_button(
    label="Download aggregated CSV",
    data=to_csv_bytes(agg_view),
    file_name=f"aggregated_{category.lower()}_{'time' if single_year is None else single_year}.csv",
    mime="text/csv",
)

# Footer
st.caption("Built for pyam-style IAMC datasets. "
           "Category = first token of 'Variable'; Level-2 = second token; "
           "Level-3+ shows technology breakdown when available.")