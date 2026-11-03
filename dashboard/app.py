"""Nova Air operations dashboard.

    streamlit run dashboard/app.py

Reads only the files the pipeline exports to data/exports. Run the pipeline first.
"""

import queries
import streamlit as st
from views import data_health, delays, overview, routes

st.set_page_config(page_title="Nova Air operations", page_icon="✈", layout="wide")

CABINS = (("ALL", "All cabins"), ("ECONOMY", "Economy"), ("PLUS", "Plus"))


def sidebar_filters(con):
    first, last = queries.date_bounds(con)
    st.sidebar.header("Filters")
    picked = st.sidebar.date_input("Flight dates", (first, last), min_value=first,
                                   max_value=last)
    # While the user is still choosing, the date input holds only a start date.
    start, end = (picked[0], picked[-1]) if picked else (first, last)
    chosen_routes = st.sidebar.multiselect("Routes", queries.route_codes(con),
                                           placeholder="All routes")
    cabin = st.sidebar.radio("Cabin", [code for code, _ in CABINS],
                             format_func=dict(CABINS).get)
    st.sidebar.caption("Punctuality and cancellations are per flight, so the cabin "
                       "filter does not change them.")
    return queries.Filters(start, end, tuple(chosen_routes), cabin)


def main():
    if not (queries.EXPORT_DIR / "gold" / "fact_flight.parquet").exists():
        st.error(f"No exports found in {queries.EXPORT_DIR}. Run the pipeline first: "
                 "python -m pipeline.run --start 2025-07-01 --end 2025-12-31")
        st.stop()
    # A fresh in-memory connection per page view: it only defines views over the
    # Parquet files, so it is cheap, and it always shows the latest export.
    con = queries.connect()
    filters = sidebar_filters(con)
    pages = [
        st.Page(lambda: overview.render(con, filters), title="Executive overview",
                url_path="overview", default=True),
        st.Page(lambda: routes.render(con, filters), title="Route performance",
                url_path="routes"),
        st.Page(lambda: delays.render(con, filters), title="Delay analysis",
                url_path="delays"),
        st.Page(lambda: data_health.render(con, filters), title="Data health",
                url_path="data-health"),
    ]
    st.navigation(pages).run()


main()
