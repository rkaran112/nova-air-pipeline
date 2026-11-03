"""Data health: can we trust today's numbers?"""

import charts
import plotly.express as px
import queries
import streamlit as st


def render(con, filters):
    st.title("Data health")
    st.caption("Can we trust today's data? What arrived, what was rejected, and did "
               "every row add up?")

    run = queries.last_run(con)
    failed = run[run["status"] != "succeeded"]
    if failed.empty:
        st.success(f"✔ Last run {run['run_id'].iloc[0]}: all {len(run)} recorded steps "
                   "succeeded.")
    else:
        st.error(f"✖ Last run {run['run_id'].iloc[0]}: step {failed['step'].iloc[0]} "
                 f"failed. {failed['message'].iloc[0]}")

    latest_flight, latest_file, loaded_at = queries.freshness(con)
    cards = st.columns(3)
    cards[0].metric("Latest flight date in the dashboard", str(latest_flight))
    cards[1].metric("Latest file received", str(latest_file))
    cards[2].metric("Last file loaded at (UTC)", loaded_at.strftime("%d %b %Y %H:%M"))

    st.subheader("Did every row add up?")
    st.caption("For every batch: rows in = loaded + exact duplicates + older versions + "
               "quarantined. A batch that does not balance stops the pipeline.")
    recon = queries.reconciliation_summary(con)
    balanced, total = int(recon["balanced_batches"].sum()), int(recon["batches"].sum())
    if balanced == total:
        st.success(f"✔ {balanced} of {total} batches balanced.")
    else:
        st.error(f"✖ Only {balanced} of {total} batches balanced.")
    st.dataframe(recon, hide_index=True, use_container_width=True)

    left, right = st.columns(2)
    with left:
        st.subheader("How many rows are in each layer?")
        st.caption("Bronze keeps everything that arrived; silver keeps one clean row per "
                   "key; gold holds the reporting tables.")
        layers = queries.layer_counts(con)
        layers["table"] = layers["layer"] + "." + layers["table_name"]
        figure = px.bar(layers, x="row_count", y="table", orientation="h",
                        color_discrete_sequence=[charts.BLUE],
                        hover_data={"row_count": ":,", "table": False})
        figure.update_yaxes(categoryorder="array", categoryarray=list(layers["table"])[::-1])
        st.plotly_chart(charts.style(figure, 380), use_container_width=True)
    with right:
        st.subheader("Why were rows quarantined?")
        st.caption("Rows held back from silver, by reason. 'released' rows waited for "
                   "their flight and were loaded later.")
        reasons = queries.quarantine_reasons(con)
        reasons["reason"] = reasons["reason_code"] + " (" + reasons["status"] + ")"
        figure = px.bar(reasons.sort_values("row_count"), x="row_count", y="reason",
                        orientation="h", color_discrete_sequence=[charts.ORANGE],
                        hover_data={"source": True, "row_count": ":,", "reason": False})
        st.plotly_chart(charts.style(figure, 380), use_container_width=True)

    outliers = queries.fare_outliers(con, filters)
    st.metric("Fares flagged as outliers (kept, not deleted)",
              f"{int(outliers['outliers'] or 0):,} of {int(outliers['bookings'] or 0):,}",
              help="Far outside the normal range for the same route and cabin.")

    st.subheader("Which checks fired?")
    st.caption("block stops the run; warn means the numbers are right but worth a look; "
               "info counts rows fixed by a documented rule.")
    st.dataframe(queries.check_results(con), hide_index=True, use_container_width=True)
