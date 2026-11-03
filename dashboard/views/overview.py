"""Executive overview: the headline numbers and how they move month to month."""

import charts
import plotly.express as px
import queries
import streamlit as st


def percent(value):
    return "–" if value is None else f"{value:.1%}"


def render(con, filters):
    st.title("Executive overview")
    st.caption("How is Nova Air performing on revenue, passengers, load factor and punctuality?")

    kpis = queries.headline_kpis(con, filters)
    cards = st.columns(5)
    cards[0].metric("Revenue", charts.crores(kpis["revenue"] or 0),
                    help="Fares plus extras on flights that operated. Refunds excluded.")
    cards[1].metric("Passengers flown", f"{int(kpis['passengers'] or 0):,}")
    cards[2].metric("Load factor", percent(kpis["load_factor"]),
                    help="Passengers flown ÷ seats offered on operated flights (sum ÷ sum).")
    cards[3].metric("On-time performance", percent(kpis["on_time"]),
                    help="Share of operated flights arriving within 15 minutes of schedule.")
    cards[4].metric("Cancellation rate", percent(kpis["cancellation"]),
                    help="Cancelled flights ÷ scheduled flights.")

    trend = queries.monthly_trends(con, filters)
    st.subheader("Is revenue growing month by month?")
    st.caption("Each bar is total revenue for flights departing in that month.")
    figure = px.bar(trend, x="month_label", y="revenue",
                    color_discrete_sequence=[charts.BLUE],
                    hover_data={"revenue": ":,.0f", "month_label": False})
    st.plotly_chart(charts.style(figure, 300), use_container_width=True)

    left, right = st.columns(2)
    with left:
        st.subheader("Are planes fuller some months?")
        st.caption("Load factor per month: higher means fewer empty seats.")
        figure = px.line(trend, x="month_label", y="load_factor", markers=True,
                         color_discrete_sequence=[charts.BLUE])
        st.plotly_chart(charts.style(figure, 280, "y"), use_container_width=True)
    with right:
        st.subheader("Are we more punctual some months?")
        st.caption("On-time performance per month: share arriving within 15 minutes.")
        figure = px.line(trend, x="month_label", y="on_time", markers=True,
                         color_discrete_sequence=[charts.ORANGE])
        st.plotly_chart(charts.style(figure, 280, "y"), use_container_width=True)

    st.subheader("Which weeks brought in the most revenue?")
    st.caption("Revenue per full week (Monday to Sunday) of departure. Look for weeks "
               "that stand out from the line.")
    weekly = queries.weekly_revenue(con, filters)
    figure = px.line(weekly, x="week_start", y="revenue", markers=True,
                     color_discrete_sequence=[charts.BLUE])
    st.plotly_chart(charts.style(figure, 280), use_container_width=True)
