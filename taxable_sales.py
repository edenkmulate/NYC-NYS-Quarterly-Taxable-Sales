import streamlit as st
import pandas as pd
import plotly.express as px
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import time

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

    return df

mod_df = load_sales_tax_data()

if mod_df.empty:
    st.error("No data was retrieved from the NY Open Data API.")
    st.stop()

# ==============================================================================
# 3. INDUSTRY FILTERS (Description & NAICS Industry Group)
# ==============================================================================
st.subheader("🎛️ Filter by Industry")

col_f1, col_f2, col_f3 = st.columns([2, 1.2, 1.3])

# Build sorted options
all_descriptions = sorted(mod_df["description"].dropna().unique().tolist())
all_naics = sorted(mod_df["naics_industry_group"].dropna().unique().tolist())
all_tax_years = sorted(mod_df["sales_tax_year"].dropna().unique().tolist())

# Default to a prominent sector (e.g., Restaurants and Other Eating Places - 7225)
default_desc = ["Restaurants and Other Eating Places"] if "Restaurants and Other Eating Places" in all_descriptions else [all_descriptions[0]]

with col_f1:
    selected_descriptions = st.multiselect(
        "Filter by Industry Description",
        options=all_descriptions,
        default=default_desc,
        key="desc_filter"
    )

with col_f2:
    selected_naics = st.multiselect(
        "Filter by NAICS Industry Group",
        options=all_naics,
        default=[],
        placeholder="All NAICS codes (optional)",
        key="naics_filter"
    )

with col_f3:
    # Default to the most recent 6 sales tax years so bars aren't cramped
    default_years = all_tax_years[-6:] if len(all_tax_years) >= 6 else all_tax_years
    selected_years = st.multiselect(
        "Filter by Sales Tax Year",
        options=all_tax_years,
        default=default_years,
        key="year_filter"
    )

# Apply Industry & Year Filters
filtered_df = mod_df.copy()

if selected_descriptions and selected_naics:
    # If user selects both, match records belonging to either selection
    filtered_df = filtered_df[
        (filtered_df["description"].isin(selected_descriptions)) |
        (filtered_df["naics_industry_group"].isin(selected_naics))
    ]
elif selected_descriptions:
    filtered_df = filtered_df[filtered_df["description"].isin(selected_descriptions)]
elif selected_naics:
    filtered_df = filtered_df[filtered_df["naics_industry_group"].isin(selected_naics)]

if selected_years:
    filtered_df = filtered_df[filtered_df["sales_tax_year"].isin(selected_years)]

if filtered_df.empty:
    st.warning("No records match your current filter selection. Please adjust the filters above.")
    st.stop()

# Build dynamic title suffix for selected industries
active_labels = sorted(filtered_df["description"].unique().tolist())
if len(active_labels) == 1:
    industry_title = active_labels[0]
elif len(active_labels) <= 3:
    industry_title = ", ".join(active_labels)
else:
    industry_title = f"{active_labels[0]} + {len(active_labels) - 1} Other Industries"

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
# 5. SIDE-BY-SIDE BAR CHARTS BY QUARTER BY YEAR (NYC vs. NYS)
# ==============================================================================
st.subheader(f"📊 Quarterly Taxable Sales by Year — {industry_title}")

# Ensure consistent chronological ordering of years and quarters (Q1 -> Q4)
year_order = sorted(filtered_df["sales_tax_year"].unique().tolist())
quarter_order = (
    filtered_df[["sales_tax_quarter", "quarter_label"]]
    .drop_duplicates()
    .sort_values("sales_tax_quarter")["quarter_label"]
    .tolist()
)

def build_jurisdiction_chart(sub_df, title_text, color_palette):
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
            "taxable_sales_and_purchases": "Taxable Sales & Purchases ($)",
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

chart_col1, chart_col2 = st.columns(2)

with chart_col1:
    if not nyc_df.empty:
        fig_nyc = build_jurisdiction_chart(
            nyc_df,
            f"🗽 New York City (NY CITY) — {industry_title}",
            px.colors.qualitative.Set2
        )
        st.plotly_chart(fig_nyc, use_container_width=True, key="nyc_qtr_bar")
    else:
        st.info("No NY CITY records available for this selection.")

with chart_col2:
    if not nys_df.empty:
        fig_nys = build_jurisdiction_chart(
            nys_df,
            f"🏛️ New York State (NY STATE) — {industry_title}",
            px.colors.qualitative.Bold
        )
        st.plotly_chart(fig_nys, use_container_width=True, key="nys_qtr_bar")
    else:
        st.info("No NY STATE records available for this selection.")

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
