"""Route performance: which routes make or lose money per seat flown."""

import charts
import plotly.express as px
import queries
import streamlit as st


def render(con, filters):
    st.title("Route performance")
    st.caption("Which routes make or lose the most money per available seat?")
    table = queries.route_performance(con, filters)
    if table.empty:
        st.info("No operated flights match these filters.")
        return

    st.subheader("Which routes earn the most per seat flown?")
    st.caption("RASK = all revenue ÷ available seat-kilometres (₹ per seat per km). "
               "Longer bars earn more from every seat they fly, full or empty. Short routes "
               "naturally score higher, so compare routes of similar length.")
    ranked = table.sort_values("rask")
    figure = px.bar(ranked, x="rask", y="route_code", orientation="h",
                    color_discrete_sequence=[charts.BLUE],
                    hover_data={"rask": ":.2f", "load_factor": ":.1%", "route_code": False})
    st.plotly_chart(charts.style(figure, 520), use_container_width=True)

    st.subheader("Which routes fill their seats but still earn little?")
    st.caption("Each dot is a route. Further right = fuller planes; higher = more revenue "
               "per seat-km. Bottom-right dots are full but cheap; left-hand dots fly "
               "empty seats.")
    # Label only the routes at the edges; the crowded middle is readable on hover.
    edges = (set(table.nsmallest(2, "rask")["route_code"])
             | set(table.nlargest(2, "rask")["route_code"])
             | set(table.nsmallest(2, "load_factor")["route_code"]))
    table = table.sort_values("rask")
    table["label"] = table["route_code"].where(table["route_code"].isin(edges), "")
    figure = px.scatter(table, x="load_factor", y="rask", text="label",
                        color_discrete_sequence=[charts.BLUE],
                        hover_name="route_code",
                        hover_data={"rask": ":.2f", "load_factor": ":.1%",
                                    "passengers": ":,", "label": False})
    # A route and its return sit almost on top of each other: alternate label sides.
    sides = ["top center" if i % 2 else "bottom center" for i in range(len(table))]
    figure.update_traces(marker={"size": 11}, textposition=sides)
    st.plotly_chart(charts.style(figure, 440, "x"), use_container_width=True)

    st.subheader("Route table")
    st.caption("Yield = fare revenue ÷ revenue passenger-km: what each passenger pays per km.")
    st.dataframe(
        table.sort_values("rask", ascending=False),
        hide_index=True,
        use_container_width=True,
        column_config={
            "route_code": "Route",
            "passengers": st.column_config.NumberColumn("Passengers", format="%d"),
            "revenue": st.column_config.NumberColumn("Revenue (₹)", format="%.0f"),
            "load_factor": st.column_config.NumberColumn("Load factor", format="percent"),
            "rask": st.column_config.NumberColumn("RASK (₹)", format="%.2f"),
            "yield_per_rpk": st.column_config.NumberColumn("Yield (₹)", format="%.2f"),
            "ask": None,
            "label": None,
        },
    )
