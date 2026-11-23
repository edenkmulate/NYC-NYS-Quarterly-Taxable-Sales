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
    page_icon="🛍️",
    layout="wide"
)

st.title("🛍️ NYC & NYS Quarterly Taxable Sales & Purchases by Industry")
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
# 3. INDUSTRY FILTERS (Sorted Highest -> Lowest Taxable Sales)
# ==============================================================================
st.subheader("🎛️ Filter by Industry & Timeframe")

col_f1, col_f2, col_f3 = st.columns([1.8, 1.8, 1.2])

# 1. Rank 2-Digit NAICS Sectors from highest to lowest total taxable sales
sector_ranked = (
    mod_df.groupby("naics_sector_label")["taxable_sales_and_purchases"]
    .sum()
    .sort_values(ascending=False)
    .index.tolist()
)

with col_f1:
    selected_sectors = st.multiselect(
        "Filter by 2-Digit NAICS Code or Sector Description",
        options=sector_ranked,
        default=[],
        placeholder="All 2-Digit NAICS Sectors (type code or name...)",
        key="sector_filter"
    )

# 2. Scope 4-Digit Industry Descriptions to selected 2-digit sectors (if any) & sort by sales
desc_pool_df = mod_df[mod_df["naics_sector_label"].isin(selected_sectors)] if selected_sectors else mod_df
desc_ranked = (
    desc_pool_df.groupby("description")["taxable_sales_and_purchases"]
    .sum()
    .sort_values(ascending=False)
    .index.tolist()
)

# Default to top-ranked industry (or Accommodation/Food if no 2-digit filter is active)
if not selected_sectors:
    default_desc = ["Restaurants and Other Eating Places"] if "Restaurants and Other Eating Places" in desc_ranked else ([desc_ranked[0]] if desc_ranked else [])
else:
    default_desc = []  # Show the entire selected 2-digit sector unless narrowed down

with col_f2:
    selected_descriptions = st.multiselect(
        "Filter by Specific Industry Description (4-Digit NAICS)",
        options=desc_ranked,
        default=default_desc,
        placeholder="All industries within selected sector...",
        key="desc_filter"
    )

# 3. Sales Tax Year Filter
all_tax_years = sorted(mod_df["sales_tax_year"].dropna().unique().tolist())
default_years = all_tax_years[-6:] if len(all_tax_years) >= 6 else all_tax_years

with col_f3:
    selected_years = st.multiselect(
        "Filter by Sales Tax Year",
        options=all_tax_years,
        default=default_years,
        key="year_filter"
    )

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

# Build dynamic title suffix based on active 2-digit sector or 4-digit description
if selected_descriptions:
    active_labels = sorted(filtered_df["description"].unique().tolist())
elif selected_sectors:
    active_labels = sorted(filtered_df["naics_sector_label"].unique().tolist())
else:
    active_labels = ["All Industries"]

if len(active_labels) == 1:
    industry_title = active_labels[0]
elif len(active_labels) <= 3:
    industry_title = ", ".join(active_labels)
else:
    industry_title = f"{active_labels[0]} + {len(active_labels) - 1} More"

# ==============================================================================
# 4. SUMMARY METRICS (NYC vs. NYS)
# ==============================================================================
st.divider()

nyc_df = filtered_df[filtered_df["jurisdiction"] == "NY CITY"]
nys_df = filtered_df[filtered_df["jurisdiction"] == "NY STATE"]

nyc_total = nyc_df["taxable_sales_and_purchases"].sum()
nys_total = nys_df["taxable_sales_and_purchases"].sum()
nyc_share = (nyc_total / nys_total * 100) if nys_total > 0 else 0

m1, m2, m3 = st.columns(3)
m1.metric("🗽 NYC Total Taxable Sales (Selected Period)", f"${nyc_total / 1_000_000:,.1f}M")
m2.metric("🏛️ NYS Total Taxable Sales (Selected Period)", f"${nys_total / 1_000_000:,.1f}M")
m3.metric("📊 NYC Share of Statewide Sales", f"{nyc_share:.1f}%")

st.divider()

# ==============================================================================
# 5. SIDE-BY-SIDE CHARTS: QUARTERLY, YTD, AND ANNUAL (NYC vs. NYS)
# ==============================================================================
year_order = sorted(filtered_df["sales_tax_year"].unique().tolist())
quarter_order = (
    filtered_df[["sales_tax_quarter", "quarter_label"]]
    .drop_duplicates()
    .sort_values("sales_tax_quarter")["quarter_label"]
    .tolist()
)

# ------------------------------------------------------------------------------
# ROW A: QUARTERLY TAXABLE SALES BY YEAR (NYC vs. NYS)
# ------------------------------------------------------------------------------
st.subheader(f"1️⃣ Quarterly Taxable Sales by Year — {industry_title}")

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

st.subheader(f"2️⃣ Sales Tax Year-to-Date ({ytd_span_text}) Comparison — {industry_title}")
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
st.subheader(f"3️⃣ Annual Taxable Sales by Sales Tax Year — {industry_title}")

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
# ROW D1: HISTORICAL LATEST-QUARTER STACKED BAR BY 2-DIGIT NAICS (LARGEST AT BOTTOM)
# ------------------------------------------------------------------------------
# Detect the latest quarter reported in the most recent year across the dataset
latest_year_all = sorted(mod_df["sales_tax_year"].dropna().unique().tolist())[-1]
latest_qtr_all = int(mod_df[mod_df["sales_tax_year"] == latest_year_all]["sales_tax_quarter"].max())
latest_period_name = (
    mod_df[
        (mod_df["sales_tax_year"] == latest_year_all) & 
        (mod_df["sales_tax_quarter"] == latest_qtr_all)
    ]["selling_period"].iloc
)

st.subheader(f"4️⃣ Historical Q{latest_qtr_all} ({latest_period_name}) Stacked by 2-Digit NAICS Sector")
st.caption("Stacked from **largest sector at the bottom** to **smallest at the top** across selected sales tax years.")

# Filter to the same quarter across all selected years (respects active sector/industry filters)
qtr_hist_df = filtered_df[filtered_df["sales_tax_quarter"] == latest_qtr_all].copy()

def build_stacked_naics_chart(sub_df, title_text):
    agg_stack = (
        sub_df.groupby(["sales_tax_year", "naics_sector_label"], as_index=False)["taxable_sales_and_purchases"]
        .sum()
    )
    # Sort sectors from LARGEST to SMALLEST so Plotly stacks largest at the bottom -> smallest at the top
    sector_bottom_to_top = (
        agg_stack.groupby("naics_sector_label")["taxable_sales_and_purchases"]
        .sum()
        .sort_values(ascending=False)
        .index.tolist()
    )

    # 1. Assign 5 distinct bold colors to the top 5 largest sectors (bottom 5 blocks of the stack)
    top_5_palette = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd"]
    sector_color_map = {}

    for idx, sector in enumerate(sector_bottom_to_top[:5]):
        sector_color_map[sector] = top_5_palette[idx]

    # 2. Assign progressive shades of grey to all remaining sectors (6th largest -> smallest at top)
    remaining_sectors = sector_bottom_to_top[5:]
    n_rem = len(remaining_sectors)
    if n_rem == 1:
        sector_color_map[remaining_sectors[0]] = "#9E9E9E"
    elif n_rem > 1:
        # Sample medium-dark grey (#757575) to light grey (#E0E0E0) so every slice stays distinguishable
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
            "sales_tax_year": year_order,
            "naics_sector_label": sector_bottom_to_top  # Largest at bottom -> smallest at top
        },
        title=title_text,
        labels={
            "sales_tax_year": "Sales Tax Year",
            "taxable_sales_and_purchases": f"Q{latest_qtr_all} Taxable Sales ($)",
            "naics_sector_label": "2-Digit NAICS Sector"
        }
    )
    fig.update_layout(
        xaxis_title="Sales Tax Year",
        yaxis_title=f"Q{latest_qtr_all} Taxable Sales ($)",
        legend_title="2-Digit NAICS (Top 5 Highlighted)",
        legend_traceorder="normal"
    )
    return fig

stack_col1, stack_col2 = st.columns(2)

with stack_col1:
    nyc_qtr_stack = qtr_hist_df[qtr_hist_df["jurisdiction"] == "NY CITY"]
    if not nyc_qtr_stack.empty:
        st.plotly_chart(
            build_stacked_naics_chart(
                nyc_qtr_stack,
                f"🗽 NYC Historical Q{latest_qtr_all} ({latest_period_name}) by 2-Digit NAICS"
            ),
            use_container_width=True,
            key="nyc_stacked_naics"
        )
    else:
        st.info(f"No NY CITY records available for Q{latest_qtr_all}.")

with stack_col2:
    nys_qtr_stack = qtr_hist_df[qtr_hist_df["jurisdiction"] == "NY STATE"]
    if not nys_qtr_stack.empty:
        st.plotly_chart(
            build_stacked_naics_chart(
                nys_qtr_stack,
                f"🏛️ NYS Historical Q{latest_qtr_all} ({latest_period_name}) by 2-Digit NAICS"
            ),
            use_container_width=True,
            key="nys_stacked_naics"
        )
    else:
        st.info(f"No NY STATE records available for Q{latest_qtr_all}.")
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
    ]["selling_period"].iloc
)

st.subheader(f"4️⃣ Industry Breakdown Treemap — Latest Quarter ({latest_year_all} Q{latest_qtr_all}: {latest_period_name})")

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
