import streamlit as st
import pandas as pd
import plotly.express as px
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import time
import plotly.colors as pc

# ==============================================================================
# 1. PAGE CONFIGURATION
# ==============================================================================
st.set_page_config(
    page_title="NYC & NYS Quarterly Taxable Sales Dashboard",
    page_icon="🛒",
    layout="wide"
)

st.title("🛒 NYC & NYS Quarterly Taxable Sales & Purchases by Industry")
st.markdown("Compare **New York City (`NY CITY`)** and **New York State (`NY STATE`)** taxable sales by quarter and sales tax year across NAICS industries.")

# ==============================================================================
# 2. CACHED DATA INGESTION (Your Working SODA2 Loader)
# ==============================================================================
@st.cache_data(ttl=86400, show_spinner="Fetching NYC & NYS Quarterly Sales Tax Data from NY Open Data...")
def load_sales_tax_data():
    api_url = "https://data.ny.gov/resource/ny73-2j3u.json"

    session = requests.Session()
    retries = Retry(
        total=5,
        backoff_factor=2,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"]
    )
    session.mount("https://", HTTPAdapter(max_retries=retries))

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) PythonDataScript/1.0",
        "Accept": "application/json"
    }

    nyc_jurisdictions = "'NY CITY','NY STATE'"

    limit = 5000
    offset = 0
    all_records = []

    while True:
        params = {
            "$limit": limit,
            "$offset": offset,
            "$order": ":id",
            "$where": f"jurisdiction IN ({nyc_jurisdictions})"
        }
        
        try:
            response = session.get(api_url, params=params, headers=headers, timeout=60)
            response.raise_for_status()
            batch = response.json()
        except requests.exceptions.RequestException:
            time.sleep(5)
            continue
        
        if not batch:
            break
            
        all_records.extend(batch)
        
        if len(batch) < limit:
            break
            
        offset += limit
        time.sleep(0.5)

    df = pd.DataFrame(all_records)

    numeric_cols = [
        "sales_tax_quarter",
        "taxable_sales_and_purchases",
        "jurisdiction_sort_order"
    ]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # Clean string columns & create clear Quarter labels (e.g., "Q1 (Mar - May)")
    df["naics_industry_group"] = df["naics_industry_group"].astype(str).str.strip()
    df["description"] = df["description"].astype(str).str.strip()
    df["quarter_label"] = (
        "Q" + df["sales_tax_quarter"].fillna(0).astype(int).astype(str) + 
        " (" + df["selling_period"].fillna("") + ")"
    )
    # Official 2-digit NAICS Sector Lookup (handles combined 31-33, 44-45, 48-49 prefixes)
    naics_2digit_map = {
        "11": "Agriculture, Forestry, Fishing and Hunting",
        "21": "Mining, Quarrying, and Oil and Gas Extraction",
        "22": "Utilities",
        "23": "Construction",
        "31": "Manufacturing",
        "32": "Manufacturing",
        "33": "Manufacturing",
        "42": "Wholesale Trade",
        "44": "Retail Trade",
        "45": "Retail Trade",
        "48": "Transportation and Warehousing",
        "49": "Transportation and Warehousing",
        "51": "Information",
        "52": "Finance and Insurance",
        "53": "Real Estate and Rental and Leasing",
        "54": "Professional, Scientific, and Technical Services",
        "55": "Management of Companies and Enterprises",
        "56": "Administrative and Support and Waste Management",
        "61": "Educational Services",
        "62": "Health Care and Social Assistance",
        "71": "Arts, Entertainment, and Recreation",
        "72": "Accommodation and Food Services",
        "81": "Other Services (except Public Administration)",
        "92": "Public Administration",
        "99": "Unclassified"
    }

    df["naics_2digit"] = df["naics_industry_group"].str[:2]
    df["naics_2digit_desc"] = df["naics_2digit"].map(naics_2digit_map).fillna("Other / Unclassified")
    
    # Combined label so users can search by either the 2-digit code OR its description
    df["naics_sector_label"] = df["naics_2digit"] + " - " + df["naics_2digit_desc"]

    return df

mod_df = load_sales_tax_data()

if mod_df.empty:
    st.error("No data was retrieved from the NY Open Data API.")
    st.stop()
# ==============================================================================
# TOP SECTION: HISTORICAL STACKED BAR BY 2-DIGIT NAICS (WITH QUARTER RADIO)
# ==============================================================================
latest_year_all = sorted(mod_df["sales_tax_year"].dropna().unique().tolist())[-1]
latest_qtr_all = int(mod_df[mod_df["sales_tax_year"] == latest_year_all]["sales_tax_quarter"].max())

# Build sorted quarter metadata: Q1 -> Q4
quarter_meta_df = (
    mod_df[["sales_tax_quarter", "selling_period", "quarter_label"]]
    .dropna(subset=["sales_tax_quarter"])
    .drop_duplicates(subset=["sales_tax_quarter"])
    .sort_values("sales_tax_quarter")
)

quarter_radio_options = []
qtr_display_to_num = {}
qtr_display_to_period = {}
default_qtr_idx = 0

for idx, row in enumerate(quarter_meta_df.itertuples()):
    q_num = int(row.sales_tax_quarter)
    base_label = row.quarter_label
    
    # Append "(Latest Quarter)" to the newest reported quarter and capture its index
    if q_num == latest_qtr_all:
        display_label = f"{base_label} :blue-badge[**Latest Quarter**]"
        default_qtr_idx = idx
    else:
        display_label = base_label
        
    quarter_radio_options.append(display_label)
    qtr_display_to_num[display_label] = q_num
    qtr_display_to_period[display_label] = row.selling_period

selected_qtr_label = st.radio(
    "Select Quarter for Historical Sector Breakdown:",
    options=quarter_radio_options,
    index=default_qtr_idx,  # Automatically defaults to the latest quarter
    horizontal=True,
    key="top_stacked_qtr_radio"
)

chosen_qtr_num = qtr_display_to_num[selected_qtr_label]
chosen_period_name = qtr_display_to_period[selected_qtr_label]

st.subheader(f"📊 Historical Q{chosen_qtr_num} ({chosen_period_name}) Stacked by 2-Digit NAICS Sector (All Sectors)")
st.caption("Stacked from **largest sector at the bottom** to **smallest at the top** across all available sales tax years.")

# Filter across all years for the chosen quarter
top_qtr_df = mod_df[mod_df["sales_tax_quarter"] == chosen_qtr_num].copy()
all_years_sorted = sorted(top_qtr_df["sales_tax_year"].dropna().unique().tolist())

def build_stacked_naics_chart(sub_df, title_text):
    agg_stack = (
        sub_df.groupby(["sales_tax_year", "naics_sector_label"], as_index=False)["taxable_sales_and_purchases"]
        .sum()
    )
    sector_bottom_to_top = (
        agg_stack.groupby("naics_sector_label")["taxable_sales_and_purchases"]
        .sum()
        .sort_values(ascending=False)
        .index.tolist()
    )

    # Top 5 largest sectors in distinct colors, remaining sectors in progressive shades of grey
    top_5_palette = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd"]
    sector_color_map = {}

    for idx, sector in enumerate(sector_bottom_to_top[:5]):
        sector_color_map[sector] = top_5_palette[idx]

    remaining_sectors = sector_bottom_to_top[5:]
    n_rem = len(remaining_sectors)
    if n_rem == 1:
        sector_color_map[remaining_sectors] = "#9E9E9E"
    elif n_rem > 1:
        grey_positions = [0.45 - (0.33 * i / (n_rem - 1)) for i in range(n_rem)]
        grey_shades = pc.sample_colorscale("Greys", grey_positions)
        for sector, shade in zip(remaining_sectors, grey_shades):
            sector_color_map[sector] = shade

    fig = px.bar(
        agg_stack,
        x="sales_tax_year",
        y="taxable_sales_and_purchases",
        color="naics_sector_label",
        barmode="stack",
        color_discrete_map=sector_color_map,
        category_orders={
            "sales_tax_year": all_years_sorted,
            "naics_sector_label": sector_bottom_to_top
        },
        title=title_text,
        labels={
            "sales_tax_year": "Sales Tax Year",
            "taxable_sales_and_purchases": f"Q{chosen_qtr_num} Taxable Sales ($)",
            "naics_sector_label": "2-Digit NAICS Sector"
        }
    )
    fig.update_layout(
        xaxis_title="Sales Tax Year",
        yaxis_title=f"Q{chosen_qtr_num} Taxable Sales ($)",
        legend_title="2-Digit NAICS (Largest First)",
        legend_traceorder="normal"
    )
    return fig

stack_col1, stack_col2 = st.columns(2)

with stack_col1:
    nyc_qtr_stack = top_qtr_df[top_qtr_df["jurisdiction"] == "NY CITY"]
    if not nyc_qtr_stack.empty:
        st.plotly_chart(
            build_stacked_naics_chart(
                nyc_qtr_stack,
                f"🗽 NYC Historical Q{chosen_qtr_num} ({chosen_period_name}) by 2-Digit NAICS"
            ),
            use_container_width=True,
            key="nyc_stacked_naics"
        )
    else:
        st.info(f"No NY CITY records available for Q{chosen_qtr_num}.")

with stack_col2:
    nys_qtr_stack = top_qtr_df[top_qtr_df["jurisdiction"] == "NY STATE"]
    if not nys_qtr_stack.empty:
        st.plotly_chart(
            build_stacked_naics_chart(
                nys_qtr_stack,
                f"🏛️ NYS Historical Q{chosen_qtr_num} ({chosen_period_name}) by 2-Digit NAICS"
            ),
            use_container_width=True,
            key="nys_stacked_naics"
        )
    else:
        st.info(f"No NY STATE records available for Q{chosen_qtr_num}.")

st.divider()
# ==============================================================================
# 3. INDUSTRY FILTERS (Bi-Directional Sync + Sorted Highest -> Lowest Sales)
# ==============================================================================
st.subheader("🎛️ Filter by Industry & Timeframe")

# Build lookup dictionaries between 4-digit description and 2-digit sector label
desc_to_sector = dict(zip(mod_df["description"], mod_df["naics_sector_label"]))

# Rank all 2-digit sectors and all 4-digit descriptions from highest -> lowest sales
all_sectors_ranked = (
    mod_df.groupby("naics_sector_label")["taxable_sales_and_purchases"]
    .sum()
    .sort_values(ascending=False)
    .index.tolist()
)
all_descs_ranked = (
    mod_df.groupby("description")["taxable_sales_and_purchases"]
    .sum()
    .sort_values(ascending=False)
    .index.tolist()
)

# Initialize session state keys if not present
if "sector_filter" not in st.session_state:
    st.session_state["sector_filter"] = []
if "desc_filter" not in st.session_state:
    st.session_state["desc_filter"] = []

# Callback 1: When 4-digit description changes -> automatically narrow 2-digit sector dropdown
def on_desc_change():
    chosen_descs = st.session_state["desc_filter"]
    if chosen_descs:
        matching_sectors = sorted({desc_to_sector[d] for d in chosen_descs if d in desc_to_sector})
        st.session_state["sector_filter"] = matching_sectors

# Callback 2: When 2-digit sector changes -> prune any 4-digit selections outside those sectors
def on_sector_change():
    chosen_sectors = st.session_state["sector_filter"]
    if chosen_sectors:
        st.session_state["desc_filter"] = [
            d for d in st.session_state["desc_filter"]
            if desc_to_sector.get(d) in chosen_sectors
        ]

col_f1, col_f2 = st.columns(2)

# Scope 2-digit options if 4-digit descriptions are selected; scope 4-digit options if 2-digit sectors are selected
if st.session_state["desc_filter"]:
    narrowed_sectors = sorted({desc_to_sector[d] for d in st.session_state["desc_filter"] if d in desc_to_sector})
    sector_options = [s for s in all_sectors_ranked if s in narrowed_sectors]
else:
    sector_options = all_sectors_ranked

if st.session_state["sector_filter"]:
    desc_pool_df = mod_df[mod_df["naics_sector_label"].isin(st.session_state["sector_filter"])]
    desc_options = (
        desc_pool_df.groupby("description")["taxable_sales_and_purchases"]
        .sum()
        .sort_values(ascending=False)
        .index.tolist()
    )
else:
    desc_options = all_descs_ranked

with col_f1:
    selected_sectors = st.multiselect(
        "Filter by 2-Digit NAICS Code or Sector Description",
        options=sector_options,
        placeholder="All 2-Digit NAICS Sectors (type code or name...)",
        key="sector_filter",
        on_change=on_sector_change
    )

with col_f2:
    selected_descriptions = st.multiselect(
        "Filter by Specific Industry Description (4-Digit NAICS)",
        options=desc_options,
        placeholder="All Specific Industries (type description...)",
        key="desc_filter",
        on_change=on_desc_change
    )

# Sales Tax Year Range Slider (Defaults to past 6 sales tax years)
all_tax_years = sorted(mod_df["sales_tax_year"].dropna().unique().tolist())

if len(all_tax_years) > 1:
    default_start_year = all_tax_years[-6] if len(all_tax_years) >= 6 else all_tax_years
    start_sty, end_sty = st.select_slider(
        "Select Sales Tax Year Range",
        options=all_tax_years,
        value=(default_start_year, all_tax_years[-1]),
        key="year_range_slider"
    )
    start_idx = all_tax_years.index(start_sty)
    end_idx = all_tax_years.index(end_sty)
    selected_years = all_tax_years[start_idx : end_idx + 1]
else:
    selected_years = all_tax_years

# Apply Filters
filtered_df = mod_df.copy()

if selected_sectors:
    filtered_df = filtered_df[filtered_df["naics_sector_label"].isin(selected_sectors)]

if selected_descriptions:
    filtered_df = filtered_df[filtered_df["description"].isin(selected_descriptions)]

if selected_years:
    filtered_df = filtered_df[filtered_df["sales_tax_year"].isin(selected_years)]

if filtered_df.empty:
    st.warning("No records match your current filter selection. Please adjust the filters above.")
    st.stop()

# Build dynamic title suffix
if selected_descriptions:
    active_labels = sorted(filtered_df["description"].unique().tolist())
elif selected_sectors:
    active_labels = sorted(filtered_df["naics_sector_label"].unique().tolist())
else:
    active_labels = ["All Industries"]

if len(active_labels) == 1:
    industry_title = active_labels
elif len(active_labels) <= 3:
    industry_title = ", ".join(active_labels)
else:
    industry_title = f"{active_labels} + {len(active_labels) - 1} More"

st.markdown(
    """
    <style>
    /* Positive Driver Buttons (type="primary") -> Green Shading */
    button[data-testid="stBaseButton-primary"],
    button[kind="primary"] {
        background-color: #e6f4ea !important;
        color: #137333 !important;
        border: 1.5px solid #34a853 !important;
        border-radius: 8px !important;
        text-align: left !important;
        justify-content: flex-start !important;
        padding: 0.65rem 0.95rem !important;
    }
    button[data-testid="stBaseButton-primary"] p,
    button[kind="primary"] p {
        color: #137333 !important;
        font-size: 1.05rem !important;
        font-weight: 700 !important;
    }
    button[data-testid="stBaseButton-primary"]:hover,
    button[kind="primary"]:hover {
        background-color: #ceead6 !important;
        border-color: #137333 !important;
    }

    /* Negative Driver Buttons (type="secondary") -> Red Shading */
    button[data-testid="stBaseButton-secondary"],
    button[kind="secondary"] {
        background-color: #fce8e6 !important;
        color: #c5221f !important;
        border: 1.5px solid #ea4335 !important;
        border-radius: 8px !important;
        text-align: left !important;
        justify-content: flex-start !important;
        padding: 0.65rem 0.95rem !important;
    }
    button[data-testid="stBaseButton-secondary"] p,
    button[kind="secondary"] p {
        color: #c5221f !important;
        font-size: 1.05rem !important;
        font-weight: 700 !important;
    }
    button[data-testid="stBaseButton-secondary"]:hover,
    button[kind="secondary"]:hover {
        background-color: #fad2cf !important;
        border-color: #c5221f !important;
    }
    </style>
    """,
    unsafe_allow_html=True
)
# ==============================================================================
# 4. SUMMARY METRICS & INTERACTIVE TOP Y/Y GROWTH DRIVERS
# ==============================================================================
st.divider()

all_sty_sorted = sorted(mod_df["sales_tax_year"].dropna().unique().tolist())
curr_sty_idx = all_sty_sorted.index(latest_year_all)
prev_sty_all = all_sty_sorted[curr_sty_idx - 1] if curr_sty_idx > 0 else None

# Callbacks to filter the dashboard when a user clicks a 2-digit or 4-digit driver
# Toggle Callback 1: Clicking an already-selected 2-digit sector clears the filter back to All Industries
def select_sector_driver(sector_label):
    if st.session_state.get("sector_filter") == [sector_label] and not st.session_state.get("desc_filter"):
        st.session_state["sector_filter"] = []
        st.session_state["desc_filter"] = []
    else:
        st.session_state["sector_filter"] = [sector_label]
        st.session_state["desc_filter"] = []

# Toggle Callback 2: Clicking an already-selected 4-digit industry steps back to its parent 2-digit sector
def select_4digit_driver(sector_label, desc_label):
    if st.session_state.get("desc_filter") == [desc_label]:
        st.session_state["sector_filter"] = [sector_label]
        st.session_state["desc_filter"] = []
    else:
        st.session_state["sector_filter"] = [sector_label]
        st.session_state["desc_filter"] = [desc_label]

def clear_driver_filters():
    st.session_state["sector_filter"] = []
    st.session_state["desc_filter"] = []

def analyze_jurisdiction_yoy(jurisdiction_name):
    """
    Computes latest-quarter taxable sales, Y/Y dollar & % change, share of total,
    top 3 positive 2-digit NAICS drivers, and the largest declining 2-digit sector (drag).
    """
    jur_all_df = mod_df[mod_df["jurisdiction"] == jurisdiction_name]
    
    jur_sel_df = jur_all_df.copy()
    if selected_sectors:
        jur_sel_df = jur_sel_df[jur_sel_df["naics_sector_label"].isin(selected_sectors)]
    if selected_descriptions:
        jur_sel_df = jur_sel_df[jur_sel_df["description"].isin(selected_descriptions)]

    curr_qtr_df = jur_sel_df[
        (jur_sel_df["sales_tax_year"] == latest_year_all) &
        (jur_sel_df["sales_tax_quarter"] == latest_qtr_all)
    ]
    curr_val = curr_qtr_df["taxable_sales_and_purchases"].sum()

    total_jur_latest_qtr = jur_all_df[
        (jur_all_df["sales_tax_year"] == latest_year_all) &
        (jur_all_df["sales_tax_quarter"] == latest_qtr_all)
    ]["taxable_sales_and_purchases"].sum()
    share_pct = (curr_val / total_jur_latest_qtr * 100) if total_jur_latest_qtr > 0 else 0.0

    if not prev_sty_all:
        return curr_val, None, None, share_pct, [], None

    prev_qtr_df = jur_sel_df[
        (jur_sel_df["sales_tax_year"] == prev_sty_all) &
        (jur_sel_df["sales_tax_quarter"] == latest_qtr_all)
    ]
    prev_val = prev_qtr_df["taxable_sales_and_purchases"].sum()

    yoy_diff = curr_val - prev_val
    yoy_pct = (yoy_diff / abs(prev_val) * 100) if prev_val != 0 else None

    # --- 2-Digit Sector Attribution ---
    c_sec = curr_qtr_df.groupby("naics_sector_label")["taxable_sales_and_purchases"].sum()
    p_sec = prev_qtr_df.groupby("naics_sector_label")["taxable_sales_and_purchases"].sum()
    sec_comp = pd.DataFrame({"curr": c_sec, "prev": p_sec}).fillna(0)
    sec_comp["diff"] = sec_comp["curr"] - sec_comp["prev"]
    sec_comp["pct"] = sec_comp.apply(
        lambda r: (r["diff"] / abs(r["prev"]) * 100) if r["prev"] != 0 else None, axis=1
    )

    # --- 4-Digit Industry Attribution ---
    c_ind = curr_qtr_df.groupby(["naics_sector_label", "naics_industry_group", "description"])["taxable_sales_and_purchases"].sum()
    p_ind = prev_qtr_df.groupby(["naics_sector_label", "naics_industry_group", "description"])["taxable_sales_and_purchases"].sum()
    ind_comp = pd.DataFrame({"curr": c_ind, "prev": p_ind}).fillna(0).reset_index()
    ind_comp["diff"] = ind_comp["curr"] - ind_comp["prev"]
    ind_comp["pct"] = ind_comp.apply(
        lambda r: (r["diff"] / abs(r["prev"]) * 100) if r["prev"] != 0 else None, axis=1
    )

    # Helper to format a sector entry + its top 3 sub-drivers in the same direction
    def build_sector_entry(sec_label, row, ascending_sub=False):
        sub_inds = (
            ind_comp[ind_comp["naics_sector_label"] == sec_label]
            .sort_values("diff", ascending=ascending_sub)
            .head(3)
        )
        sub_driver_items = [
            {
                "code": i_row["naics_industry_group"],
                "desc": i_row["description"],
                "diff_m": i_row["diff"] / 1_000_000,
                "pct": i_row["pct"]
            }
            for _, i_row in sub_inds.iterrows()
        ]
        return {
            "sector": sec_label,
            "diff_m": row["diff"] / 1_000_000,
            "pct": row["pct"],
            "sub_drivers": sub_driver_items
        }

    # 1. Top 3 Positive Growth Contributors (Green)
    pos_sectors = sec_comp[sec_comp["diff"] > 0].sort_values("diff", ascending=False).head(3)
    top_drivers = [
        build_sector_entry(sec_label, row, ascending_sub=False)
        for sec_label, row in pos_sectors.iterrows()
    ]

    # 2. Largest Declining Sector / Drag on Growth (Red) - only if any sector declined
    neg_sectors = sec_comp[sec_comp["diff"] < 0].sort_values("diff", ascending=True).head(1)
    largest_drag = None
    for drag_label, drag_row in neg_sectors.iterrows():
        largest_drag = build_sector_entry(drag_label, drag_row, ascending_sub=True)

    return curr_val, yoy_diff, yoy_pct, share_pct, top_drivers, largest_drag


nyc_curr, nyc_diff, nyc_pct, nyc_share, nyc_drivers, nyc_drag = analyze_jurisdiction_yoy("NY CITY")
nys_curr, nys_diff, nys_pct, nys_share, nys_drivers, nys_drag = analyze_jurisdiction_yoy("NY STATE")

head_col1, head_col2 = st.columns()
with head_col1:
    st.markdown(f"### 📌 Latest Quarter Snapshot ({latest_year_all} Q{latest_qtr_all} vs. {prev_sty_all} Q{latest_qtr_all}) — {industry_title}")
with head_col2:
    if selected_sectors or selected_descriptions:
        st.button("🔄 Reset Industry Filter", on_click=clear_driver_filters, type="tertiary", use_container_width=True)

# Top KPI Cards
m1, m2, m3, m4 = st.columns(4)

m1.metric(
    label=f"🗽 NYC Q{latest_qtr_all} Taxable Sales",
    value=f"${nyc_curr / 1_000_000:,.1f}M",
    delta=f"${nyc_diff / 1_000_000:+,.1f}M ({nyc_pct:+.1f}%) Y/Y" if nyc_diff is not None and nyc_pct is not None else None
)
m2.metric(
    label=f"🗽 NYC Share of Total Q{latest_qtr_all} Sales",
    value=f"{nyc_share:.1f}%"
)
m3.metric(
    label=f"🏛️ NYS Q{latest_qtr_all} Taxable Sales",
    value=f"${nys_curr / 1_000_000:,.1f}M",
    delta=f"${nys_diff / 1_000_000:+,.1f}M ({nys_pct:+.1f}%) Y/Y" if nys_diff is not None and nys_pct is not None else None
)
m4.metric(
    label=f"🏛️ NYS Share of Total Q{latest_qtr_all} Sales",
    value=f"{nys_share:.1f}%"
)

# Side-by-Side Interactive Driver Callout Boxes
drv_col1, drv_col2 = st.columns(2)

def render_driver_card(col, jur_prefix, title, total_diff, drivers, drag_driver):
    with col:
        direction_word = "Increase" if (total_diff is not None and total_diff >= 0) else "Decrease"
        diff_m = (total_diff / 1_000_000) if total_diff is not None else 0
        with st.container(border=True):
            st.markdown(f"**{title} — Top Sector Drivers of ${diff_m:+,.1f}M {direction_word}**")
            st.caption("Click any 2-digit sector button to toggle filter, or expand to inspect 4-digit drivers.")
            
            if not drivers and not drag_driver:
                st.caption("No prior-year comparison data available.")
            else:
                # 1. Render Top 3 Positive Contributors in Green (type="primary")
                for rank, d in enumerate(drivers, start=1):
                    pct_str = f"{d['pct']:+.1f}%" if pd.notna(d["pct"]) else "N/A"
                    st.button(
                        label=f"📈 #{rank}  {d['sector']}   |   ${d['diff_m']:+,.1f}M ({pct_str})",
                        key=f"{jur_prefix}_sec_btn_{rank}",
                        type="primary",
                        use_container_width=True,
                        on_click=select_sector_driver,
                        args=(d["sector"],)
                    )
                    if d["sub_drivers"]:
                        with st.expander(f"🔍 View Top 4-Digit Drivers in {d['sector']}"):
                            for sub_idx, sub in enumerate(d["sub_drivers"], start=1):
                                sub_pct_str = f"{sub['pct']:+.1f}%" if pd.notna(sub["pct"]) else "N/A"
                                sub_color = "green" if sub["diff_m"] >= 0 else "red"
                                st.markdown(
                                    f"**{sub['code']} — {sub['desc']}**: :{sub_color}[**${sub['diff_m']:+,.1f}M ({sub_pct_str})**]"
                                )
                                st.button(
                                    label=f"Filter to {sub['code']} - {sub['desc']}",
                                    key=f"{jur_prefix}_sub_btn_{rank}_{sub_idx}",
                                    type="tertiary",
                                    on_click=select_4digit_driver,
                                    args=(d["sector"], sub["desc"])
                                )

                # 2. Render Largest Declining Sector (Drag on Growth) in Red at the Bottom (type="secondary")
                if drag_driver is not None:
                    st.markdown("---")
                    st.caption("🔻 **Largest Drag on Growth (Biggest Declining Sector)**")
                    drag_pct_str = f"{drag_driver['pct']:+.1f}%" if pd.notna(drag_driver["pct"]) else "N/A"
                    st.button(
                        label=f"📉 Largest Drag:  {drag_driver['sector']}   |   ${drag_driver['diff_m']:+,.1f}M ({drag_pct_str})",
                        key=f"{jur_prefix}_drag_btn",
                        type="secondary",
                        use_container_width=True,
                        on_click=select_sector_driver,
                        args=(drag_driver["sector"],)
                    )
                    if drag_driver["sub_drivers"]:
                        with st.expander(f"🔍 View Largest Declining 4-Digit Industries in {drag_driver['sector']}"):
                            for sub_idx, sub in enumerate(drag_driver["sub_drivers"], start=1):
                                sub_pct_str = f"{sub['pct']:+.1f}%" if pd.notna(sub["pct"]) else "N/A"
                                sub_color = "green" if sub["diff_m"] >= 0 else "red"
                                st.markdown(
                                    f"**{sub['code']} — {sub['desc']}**: :{sub_color}[**${sub['diff_m']:+,.1f}M ({sub_pct_str})**]"
                                )
                                st.button(
                                    label=f"Filter to {sub['code']} - {sub['desc']}",
                                    key=f"{jur_prefix}_drag_sub_btn_{sub_idx}",
                                    type="tertiary",
                                    on_click=select_4digit_driver,
                                    args=(drag_driver["sector"], sub["desc"])
                                )

render_driver_card(drv_col1, "nyc", "🗽 New York City (NY CITY)", nyc_diff, nyc_drivers, nyc_drag)

nyc_curr, nyc_diff, nyc_pct, nyc_share, nyc_drivers = analyze_jurisdiction_yoy("NY CITY")
nys_curr, nys_diff, nys_pct, nys_share, nys_drivers = analyze_jurisdiction_yoy("NY STATE")

head_col1, head_col2 = st.columns([4, 1])
with head_col1:
    st.markdown(f"### 📌 Latest Quarter Snapshot ({latest_year_all} Q{latest_qtr_all} vs. {prev_sty_all} Q{latest_qtr_all}) — {industry_title}")
with head_col2:
    if selected_sectors or selected_descriptions:
        st.button("🔄 Reset Industry Filter", on_click=clear_driver_filters, use_container_width=True)

# Top KPI Cards
m1, m2, m3, m4 = st.columns(4)

m1.metric(
    label=f"🗽 NYC Q{latest_qtr_all} Taxable Sales",
    value=f"${nyc_curr / 1_000_000:,.1f}M",
    delta=f"${nyc_diff / 1_000_000:+,.1f}M ({nyc_pct:+.1f}%) Y/Y" if nyc_diff is not None and nyc_pct is not None else None
)
m2.metric(
    label=f"🗽 NYC Share of Total Q{latest_qtr_all} Sales",
    value=f"{nyc_share:.1f}%"
)
m3.metric(
    label=f"🏛️ NYS Q{latest_qtr_all} Taxable Sales",
    value=f"${nys_curr / 1_000_000:,.1f}M",
    delta=f"${nys_diff / 1_000_000:+,.1f}M ({nys_pct:+.1f}%) Y/Y" if nys_diff is not None and nys_pct is not None else None
)
m4.metric(
    label=f"🏛️ NYS Share of Total Q{latest_qtr_all} Sales",
    value=f"{nys_share:.1f}%"
)

# Side-by-Side Interactive Driver Callout Boxes
drv_col1, drv_col2 = st.columns(2)

def render_driver_card(col, jur_prefix, title, total_diff, drivers):
    with col:
        direction_word = "Increase" if (total_diff is not None and total_diff >= 0) else "Decrease"
        diff_m = (total_diff / 1_000_000) if total_diff is not None else 0
        with st.container(border=True):
            st.markdown(f"**{title} — Top 3 Sector Drivers of ${diff_m:+,.1f}M {direction_word}**")
            st.caption("Click any 2-digit sector button to filter charts below, or expand to inspect 4-digit drivers.")
            if not drivers:
                st.caption("No prior-year comparison data available.")
            else:
                for rank, d in enumerate(drivers, start=1):
                    pct_str = f"{d['pct']:+.1f}%" if pd.notna(d["pct"]) else "N/A"
                    is_positive = d["diff_m"] >= 0
                    btn_type = "primary" if is_positive else "secondary"
                    trend_icon = "📈" if is_positive else "📉"

                    # Bold, larger button-style badge shaded green (positive) or red (negative)
                    st.button(
                        label=f"{trend_icon} #{rank}  {d['sector']}   |   ${d['diff_m']:+,.1f}M ({pct_str})",
                        key=f"{jur_prefix}_sec_btn_{rank}",
                        type=btn_type,
                        use_container_width=True,
                        on_click=select_sector_driver,
                        args=(d["sector"],)
                    )

                    # Clickable 4-digit dropdown/expander beneath each 2-digit sector
                    if d["sub_drivers"]:
                        with st.expander(f"🔍 View Top 4-Digit Drivers in {d['sector']}"):
                            for sub_idx, sub in enumerate(d["sub_drivers"], start=1):
                                sub_pct_str = f"{sub['pct']:+.1f}%" if pd.notna(sub["pct"]) else "N/A"
                                sub_color = "green" if sub["diff_m"] >= 0 else "red"
                                st.markdown(
                                    f"**{sub['code']} — {sub['desc']}**: :{sub_color}[**${sub['diff_m']:+,.1f}M ({sub_pct_str})**]"
                                )
                                st.button(
                                    label=f"Filter to {sub['code']} - {sub['desc']}",
                                    key=f"{jur_prefix}_sub_btn_{rank}_{sub_idx}",
                                    on_click=select_4digit_driver,
                                    args=(d["sector"], sub["desc"])
                                )

render_driver_card(drv_col1, "nyc", "🗽 New York City (NY CITY)", nyc_diff, nyc_drivers)
render_driver_card(drv_col2, "nys", "🏛️ New York State (NY STATE)", nys_diff, nys_drivers)

st.divider()

nyc_df = filtered_df[filtered_df["jurisdiction"] == "NY CITY"]
nys_df = filtered_df[filtered_df["jurisdiction"] == "NY STATE"]


# ==============================================================================
# 5. SIDE-BY-SIDE CHARTS: QUARTERLY, YTD, ANNUAL & TREEMAP
# ==============================================================================
year_order = sorted(filtered_df["sales_tax_year"].dropna().unique().tolist())
quarter_order = (
    filtered_df[["sales_tax_quarter", "quarter_label"]]
    .dropna(subset=["sales_tax_quarter"])
    .drop_duplicates()
    .sort_values("sales_tax_quarter")["quarter_label"]
    .tolist()
)

# ------------------------------------------------------------------------------
# ROW A: QUARTERLY TAXABLE SALES BY YEAR (NYC vs. NYS)
# ------------------------------------------------------------------------------
st.subheader(f"2️⃣ Quarterly Taxable Sales by Year — {industry_title}")

def build_quarterly_chart(sub_df, title_text, color_palette):
    agg_df = (
        sub_df.groupby(["sales_tax_year", "sales_tax_quarter", "quarter_label"], as_index=False)["taxable_sales_and_purchases"]
        .sum()
        .sort_values(["sales_tax_year", "sales_tax_quarter"])
    )
    fig = px.bar(
        agg_df,
        x="sales_tax_year",
        y="taxable_sales_and_purchases",
        color="quarter_label",
        barmode="group",
        color_discrete_sequence=color_palette,
        category_orders={
            "sales_tax_year": year_order,
            "quarter_label": quarter_order
        },
        title=title_text,
        labels={
            "sales_tax_year": "Sales Tax Year",
            "taxable_sales_and_purchases": "Taxable Sales ($)",
            "quarter_label": "Quarter"
        }
    )
    fig.update_layout(
        xaxis_title="Sales Tax Year",
        yaxis_title="Taxable Sales ($)",
        legend_title="Quarter",
        bargap=0.18,
        bargroupgap=0.05
    )
    return fig

# ------------------------------------------------------------------------------
# ROW A: QUARTERLY TAXABLE SALES BY YEAR (NYC vs. NYS)
# ------------------------------------------------------------------------------
st.subheader(f"Quarterly Taxable Sales by Year — {industry_title}")

def build_quarterly_chart(sub_df, title_text, color_palette):
    agg_df = (
        sub_df.groupby(["sales_tax_year", "sales_tax_quarter", "quarter_label"], as_index=False)["taxable_sales_and_purchases"]
        .sum()
        .sort_values(["sales_tax_year", "sales_tax_quarter"])
    )
    fig = px.bar(
        agg_df,
        x="sales_tax_year",
        y="taxable_sales_and_purchases",
        color="quarter_label",
        barmode="group",
        color_discrete_sequence=color_palette,
        category_orders={
            "sales_tax_year": year_order,
            "quarter_label": quarter_order
        },
        title=title_text,
        labels={
            "sales_tax_year": "Sales Tax Year",
            "taxable_sales_and_purchases": "Taxable Sales ($)",
            "quarter_label": "Quarter"
        }
    )
    fig.update_layout(
        xaxis_title="Sales Tax Year",
        yaxis_title="Taxable Sales ($)",
        legend_title="Quarter",
        bargap=0.18,
        bargroupgap=0.05
    )
    return fig

q_col1, q_col2 = st.columns(2)
with q_col1:
    if not nyc_df.empty:
        st.plotly_chart(
            build_quarterly_chart(nyc_df, f"🗽 NYC Quarterly Sales — {industry_title}", px.colors.qualitative.Set2),
            use_container_width=True,
            key="nyc_qtr_bar"
        )
    else:
        st.info("No NY CITY records available.")

with q_col2:
    if not nys_df.empty:
        st.plotly_chart(
            build_quarterly_chart(nys_df, f"🏛️ NYS Quarterly Sales — {industry_title}", px.colors.qualitative.Bold),
            use_container_width=True,
            key="nys_qtr_bar"
        )
    else:
        st.info("No NY STATE records available.")

st.divider()
# ------------------------------------------------------------------------------
# ROW B: SALES TAX YEAR-TO-DATE (YTD) COMPARISON (NYC vs. NYS)
# ------------------------------------------------------------------------------
# Detect the latest quarter reported in the most recent selected sales tax year
latest_sty = year_order[-1]
latest_qtr_num = int(filtered_df[filtered_df["sales_tax_year"] == latest_sty]["sales_tax_quarter"].max())
ytd_qtr_labels = [f"Q{q}" for q in range(1, latest_qtr_num + 1)]
ytd_span_text = f"Q1–Q{latest_qtr_num}" if latest_qtr_num > 1 else "Q1"

st.subheader(f"Sales Tax Year-to-Date ({ytd_span_text}) Comparison — {industry_title}")
st.caption(f"Comparing cumulative **{ytd_span_text}** taxable sales across every selected year to match the latest reporting period ({latest_sty} Q{latest_qtr_num}).")

def build_ytd_chart(sub_df, title_text, bar_color):
    ytd_sub = sub_df[sub_df["sales_tax_quarter"] <= latest_qtr_num]
    agg_ytd = (
        ytd_sub.groupby("sales_tax_year", as_index=False)["taxable_sales_and_purchases"]
        .sum()
        .sort_values("sales_tax_year")
    )
    agg_ytd["yoy_pct"] = agg_ytd["taxable_sales_and_purchases"].pct_change() * 100
    agg_ytd["text_label"] = agg_ytd["yoy_pct"].apply(lambda x: f"{x:+.1f}%" if pd.notna(x) else "")

    fig = px.bar(
        agg_ytd,
        x="sales_tax_year",
        y="taxable_sales_and_purchases",
        text="text_label",
        category_orders={"sales_tax_year": year_order},
        title=title_text,
        labels={
            "sales_tax_year": "Sales Tax Year",
            "taxable_sales_and_purchases": f"YTD ({ytd_span_text}) Taxable Sales ($)"
        }
    )
    fig.update_traces(marker_color=bar_color, textposition="outside")
    fig.update_layout(
        xaxis_title="Sales Tax Year",
        yaxis_title=f"YTD ({ytd_span_text}) Taxable Sales ($)",
        uniformtext_minsize=8,
        uniformtext_mode="hide"
    )
    return fig

ytd_col1, ytd_col2 = st.columns(2)
with ytd_col1:
    if not nyc_df.empty:
        st.plotly_chart(
            build_ytd_chart(nyc_df, f"🗽 NYC YTD ({ytd_span_text}) Sales — {industry_title}", "#1f77b4"),
            use_container_width=True,
            key="nyc_ytd_bar"
        )
    else:
        st.info("No NY CITY YTD records available.")

with ytd_col2:
    if not nys_df.empty:
        st.plotly_chart(
            build_ytd_chart(nys_df, f"🏛️ NYS YTD ({ytd_span_text}) Sales — {industry_title}", "#2ca02c"),
            use_container_width=True,
            key="nys_ytd_bar"
        )
    else:
        st.info("No NY STATE YTD records available.")

st.divider()

# ------------------------------------------------------------------------------
# ROW C: FULL ANNUAL TAXABLE SALES BY YEAR (NYC vs. NYS)
# ------------------------------------------------------------------------------
st.subheader(f"Annual Taxable Sales by Sales Tax Year — {industry_title}")

def build_annual_chart(sub_df, title_text, bar_color):
    agg_ann = (
        sub_df.groupby("sales_tax_year", as_index=False)
        .agg(
            taxable_sales_and_purchases=("taxable_sales_and_purchases", "sum"),
            quarters_reported=("sales_tax_quarter", "nunique")
        )
        .sort_values("sales_tax_year")
    )
    # Only calculate YoY % on full 4-quarter years (or show partial-year note)
    agg_ann["yoy_pct"] = agg_ann["taxable_sales_and_purchases"].pct_change() * 100
    agg_ann["bar_label"] = agg_ann.apply(
        lambda r: f"{r['yoy_pct']:+.1f}%" if (pd.notna(r["yoy_pct"]) and r["quarters_reported"] == 4)
        else (f"({int(r['quarters_reported'])}Q)" if r["quarters_reported"] < 4 else ""),
        axis=1
    )

    fig = px.bar(
        agg_ann,
        x="sales_tax_year",
        y="taxable_sales_and_purchases",
        text="bar_label",
        category_orders={"sales_tax_year": year_order},
        title=title_text,
        labels={
            "sales_tax_year": "Sales Tax Year",
            "taxable_sales_and_purchases": "Annual Taxable Sales ($)"
        }
    )
    fig.update_traces(marker_color=bar_color, textposition="outside")
    fig.update_layout(
        xaxis_title="Sales Tax Year",
        yaxis_title="Annual Taxable Sales ($)",
        uniformtext_minsize=8,
        uniformtext_mode="hide"
    )
    return fig

ann_col1, ann_col2 = st.columns(2)
with ann_col1:
    if not nyc_df.empty:
        st.plotly_chart(
            build_annual_chart(nyc_df, f"🗽 NYC Annual Taxable Sales — {industry_title}", "#0b4f6c"),
            use_container_width=True,
            key="nyc_ann_bar"
        )
    else:
        st.info("No NY CITY annual records available.")

with ann_col2:
    if not nys_df.empty:
        st.plotly_chart(
            build_annual_chart(nys_df, f"🏛️ NYS Annual Taxable Sales — {industry_title}", "#145a32"),
            use_container_width=True,
            key="nys_ann_bar"
        )
    else:
        st.info("No NY STATE annual records available.")

# ------------------------------------------------------------------------------
# ROW D2: SIDE-BY-SIDE TREEMAP BY INDUSTRY DESCRIPTION (LATEST QUARTER)
# ------------------------------------------------------------------------------
# Identify the most recent Sales Tax Year and Quarter across the full dataset
latest_year_all = sorted(mod_df["sales_tax_year"].dropna().unique().tolist())[-1]
latest_qtr_all = int(mod_df[mod_df["sales_tax_year"] == latest_year_all]["sales_tax_quarter"].max())
latest_period_name = (
    mod_df[
        (mod_df["sales_tax_year"] == latest_year_all) & 
        (mod_df["sales_tax_quarter"] == latest_qtr_all)
    ]["selling_period"].iloc[0]
)

st.subheader(f"Industry Breakdown Treemap — Latest Quarter ({latest_year_all} Q{latest_qtr_all}: {latest_period_name})")

top_n = st.slider(
    "Number of Top Industries to Display in Treemap",
    min_value=10,
    max_value=50,
    value=25,
    step=5,
    key="treemap_top_n"
)

latest_qtr_df = mod_df[
    (mod_df["sales_tax_year"] == latest_year_all) &
    (mod_df["sales_tax_quarter"] == latest_qtr_all) &
    (mod_df["taxable_sales_and_purchases"] > 0)
].copy()

# Derive 2-digit NAICS Sector code for clean hierarchical grouping in the treemap
latest_qtr_df["naics_sector"] = "NAICS " + latest_qtr_df["naics_industry_group"].str[:2]

def build_treemap_chart(sub_df, title_text, color_scale):
    agg_tree = (
        sub_df.groupby(["naics_sector", "description"], as_index=False)["taxable_sales_and_purchases"]
        .sum()
        .sort_values("taxable_sales_and_purchases", ascending=False)
        .head(top_n)
    )
    fig = px.treemap(
        agg_tree,
        path=[px.Constant("All Displayed Industries"), "naics_sector", "description"],
        values="taxable_sales_and_purchases",
        color="taxable_sales_and_purchases",
        color_continuous_scale=color_scale,
        title=title_text,
        labels={"taxable_sales_and_purchases": "Taxable Sales ($)"}
    )
    fig.update_traces(
        textinfo="label+percent root",
        hovertemplate="<b>%{label}</b><br>Taxable Sales: $%{value:,.0f}<br>Share of Displayed: %{percentRoot:.1%}<extra></extra>"
    )
    fig.update_layout(margin=dict(t=50, l=10, r=10, b=10))
    fig.update_coloraxes(showscale=False)
    return fig

tree_col1, tree_col2 = st.columns(2)

with tree_col1:
    nyc_latest = latest_qtr_df[latest_qtr_df["jurisdiction"] == "NY CITY"]
    if not nyc_latest.empty:
        st.plotly_chart(
            build_treemap_chart(
                nyc_latest,
                f"🗽 NYC Top {top_n} Industries ({latest_year_all} Q{latest_qtr_all})",
                "Blues"
            ),
            use_container_width=True,
            key="nyc_treemap"
        )
    else:
        st.info("No NY CITY records available for the latest quarter.")

with tree_col2:
    nys_latest = latest_qtr_df[latest_qtr_df["jurisdiction"] == "NY STATE"]
    if not nys_latest.empty:
        st.plotly_chart(
            build_treemap_chart(
                nys_latest,
                f"🏛️ NYS Top {top_n} Industries ({latest_year_all} Q{latest_qtr_all})",
                "Greens"
            ),
            use_container_width=True,
            key="nys_treemap"
        )
    else:
        st.info("No NY STATE records available for the latest quarter.")

# ==============================================================================
# 6. UNDERLYING DATA TABLE & CSV DOWNLOAD
# ==============================================================================
with st.expander(f"View & Download Filtered Sales Tax Data ({len(filtered_df):,} rows)"):
    display_cols = [
        "sales_tax_year", "sales_tax_quarter", "selling_period",
        "jurisdiction", "naics_industry_group", "description",
        "taxable_sales_and_purchases", "status"
    ]
    export_df = filtered_df[display_cols].sort_values(
        ["sales_tax_year", "sales_tax_quarter", "jurisdiction"],
        ascending=[False, False, True]
    )
    st.download_button(
        label="📥 Download Filtered Data as CSV",
        data=export_df.to_csv(index=False).encode("utf-8"),
file_name="nyc_nys_quarterly_sales_tax.csv",
mime="text/csv"
)
st.dataframe(export_df, use_container_width=True)
