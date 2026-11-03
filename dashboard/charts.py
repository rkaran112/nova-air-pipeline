"""One consistent, quiet look for every chart: thin marks, light grid, one blue."""

BLUE = "#2a78d6"
ORANGE = "#eb6834"
AQUA = "#1baf7a"
TEXT = "#52514e"
GRID = "#e8e7e3"
# Sequential blue, light (little delay) to dark (a lot).
BLUES = ("#eef4fc", "#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95",
         "#0d366b")


def style(figure, height=340, percent_axis=None):
    """Apply the shared layout. percent_axis is 'x' or 'y' for a 0-100% axis."""
    figure.update_layout(
        height=height,
        margin={"l": 8, "r": 8, "t": 8, "b": 8},
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        font={"color": TEXT, "size": 13},
        showlegend=False,
        hoverlabel={"bgcolor": "white"},
    )
    figure.update_xaxes(showgrid=False, linecolor=GRID, title=None)
    figure.update_yaxes(gridcolor=GRID, zeroline=False, title=None)
    if percent_axis == "x":
        figure.update_xaxes(tickformat=".0%")
    if percent_axis == "y":
        figure.update_yaxes(tickformat=".0%")
    return figure


def crores(value):
    """Indian convention: 1 crore = 10 million rupees."""
    return f"₹{value / 1e7:,.1f} cr"
