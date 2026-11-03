"""Delay analysis: where, when and why departures run late."""

import charts
import plotly.express as px
import plotly.graph_objects as go
import queries
import streamlit as st


def heatmap(table, column, row, labels=None, every_column=None):
    grid = table.pivot(index=row, columns=column, values="avg_delay")
    if every_column is not None:
        # One column per hour, even hours with no departures, so cells stay equal width.
        grid = grid.reindex(columns=every_column)
    figure = go.Figure(go.Heatmap(
        z=grid.values, x=labels or list(grid.columns), y=list(grid.index),
        colorscale=list(charts.BLUES), xgap=2, ygap=2,
        hovertemplate="%{y} · %{x}<br>%{z:.0f} min average delay<extra></extra>",
        colorbar={"title": "min"}))
    return figure


def render(con, filters):
    st.title("Delay analysis")
    st.caption("Where and why do delays happen, and when are they worst? "
               "Delay here means minutes late leaving the gate; early departures count as 0.")
    by_leg = queries.delay_by_leg(con, filters)
    if by_leg.empty:
        st.info("No operated flights match these filters.")
        return

    st.subheader("What causes the most delay minutes?")
    st.caption("Total departure delay minutes by the cause recorded on the flight. "
               "'Reactionary' means the aircraft arrived late from its previous flight.")
    causes = queries.delay_causes(con, filters).sort_values("delay_minutes")
    figure = px.bar(causes, x="delay_minutes", y="category", orientation="h",
                    color_discrete_sequence=[charts.BLUE],
                    hover_data={"delay_minutes": ":,", "flights": ":,", "category": False})
    st.plotly_chart(charts.style(figure, 300), use_container_width=True)

    st.subheader("Where and at what time of day are departures most delayed?")
    st.caption("Average departure delay by airport and scheduled departure hour (IST). "
               "Darker cells are later. Empty cells have no departures at that hour.")
    by_hour = queries.delay_by_airport_hour(con, filters)
    hours = range(int(by_hour["hour"].min()), int(by_hour["hour"].max()) + 1)
    figure = heatmap(by_hour, "hour", "airport", every_column=list(hours))
    figure.update_xaxes(dtick=1)
    st.plotly_chart(charts.style(figure, 420),
                    use_container_width=True)

    st.subheader("Which airports have bad months?")
    st.caption("Average departure delay by airport and month. Read across a row to see "
               "an airport's season; read down a column to compare airports.")
    by_month = queries.delay_by_airport_month(con, filters)
    month_labels = by_month.drop_duplicates("month").sort_values("month")["month_label"]
    st.plotly_chart(charts.style(heatmap(by_month, "month", "airport", list(month_labels)), 420),
                    use_container_width=True)

    st.subheader("Do delays build up through an aircraft's day?")
    st.caption("Average departure delay by which flight of the day it is for that aircraft "
               "(1 = its first flight). A rising line means lateness is passed along.")
    figure = px.line(by_leg, x="leg", y="avg_delay", markers=True,
                     color_discrete_sequence=[charts.BLUE],
                     hover_data={"flights": ":,", "on_time": ":.1%"})
    figure.update_xaxes(dtick=1)
    st.plotly_chart(charts.style(figure, 300), use_container_width=True)
