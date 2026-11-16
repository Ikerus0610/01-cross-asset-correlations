import numpy as np
import pandas as pd
import plotly.graph_objects as go

TEAL = "#19776B"
RUST = "#AE5845"
INK = "#173A3D"
GRID = "#DCE6E3"
COLORS = [TEAL, "#CB793D", "#586AA3"]


def canvas(fig, height, **kwargs):
    fig.update_layout(
        template="plotly_white",
        height=height,
        font=dict(
            family='"Source Sans", "Source Sans Pro", sans-serif', color=INK, size=13
        ),
        margin=dict(l=10, r=14, t=20, b=12),
        paper_bgcolor="white",
        plot_bgcolor="white",
        legend=dict(orientation="h", yanchor="bottom", y=1.01),
        **kwargs,
    )
    fig.update_xaxes(gridcolor=GRID)
    fig.update_yaxes(gridcolor=GRID)
    return fig


def median_chart(summaries):
    fig = go.Figure()
    order = summaries[0][1].sort_values("median", ascending=False).index
    for i, (label, summary) in enumerate(summaries):
        data = summary.loc[order]
        palette = [TEAL if v >= 0 else RUST for v in data["median"]]
        fig.add_bar(
            name=label,
            x=order,
            y=data["median"],
            customdata=data.n,
            marker_color=palette if len(summaries) == 1 else COLORS[i],
            text=[f"{v:+.2%}" if pd.notna(v) else "N/D" for v in data["median"]],
            textposition="outside",
            cliponaxis=False,
            hovertemplate="%{x} · %{y:+.3%}<br>Valid sessions: %{customdata}<extra>%{fullData.name}</extra>",
        )
    canvas(fig, 285, showlegend=len(summaries) > 1, barmode="group", bargap=0.42)
    vals = pd.concat([s["median"] for _, s in summaries]).dropna()
    lo, hi = (min(0, vals.min()), max(0, vals.max())) if len(vals) else (-0.01, 0.01)
    pad = max((hi - lo) * 0.16, 0.0001)
    fig.update_yaxes(tickformat=".1%", range=[lo - pad, hi + pad], zerolinecolor=INK)
    fig.update_xaxes(showgrid=False)
    return fig


def rolling_chart(series):
    fig = go.Figure()
    for color, (window, values) in zip(COLORS, series.items()):
        fig.add_scatter(
            x=values.index,
            y=values,
            mode="lines",
            name=f"{window} sessions",
            connectgaps=False,
            line=dict(width=1.7, color=color),
            hovertemplate="%{x|%Y-%m-%d} · %{y:.3f}<extra>%{fullData.name}</extra>",
        )
    canvas(fig, 330, hovermode="x unified")
    fig.add_hline(y=0, line_color=INK, line_dash="dot")
    fig.update_yaxes(range=[-1.03, 1.03], title="Correlation")
    return fig


def scatter_chart(points, a, b):
    fig = go.Figure(
        go.Scattergl(
            x=points[a],
            y=points[b],
            mode="markers",
            customdata=points.index.strftime("%Y-%m-%d"),
            marker=dict(size=6, color=TEAL, opacity=0.48),
            hovertemplate="%{customdata}<br>"
            + a
            + " %{x:.2%}<br>"
            + b
            + " %{y:.2%}<extra></extra>",
        )
    )
    canvas(fig, 330)
    fig.update_xaxes(tickformat=".1%", title=f"{a} daily return", zerolinecolor=INK)
    fig.update_yaxes(tickformat=".1%", title=f"{b} daily return", zerolinecolor=INK)
    return fig


def heatmap(values, counts, reasons):
    fig = go.Figure(
        go.Heatmap(
            z=values.to_numpy(),
            x=values.columns,
            y=values.index,
            zmin=-1,
            zmax=1,
            colorscale=[[0, RUST], [0.5, "#F4F6F3"], [1, TEAL]],
            xgap=3,
            ygap=3,
            customdata=counts.to_numpy(),
            colorbar=dict(title="ρ", tickvals=[-1, -0.5, 0, 0.5, 1]),
            hovertemplate="%{y} × %{x}<br>Correlation %{z:.3f}<br>n = %{customdata}<extra></extra>",
        )
    )
    for a in values:
        for b in values:
            v = values.loc[a, b]
            label = "N/D" if np.isnan(v) else f"{v:+.2f}"
            fig.add_annotation(
                x=b,
                y=a,
                text=f"<b>{label}</b><br>n={counts.loc[a, b]}",
                showarrow=False,
                hovertext=reasons.loc[a, b] or None,
                font=dict(color="white" if abs(v) > 0.65 else INK, size=13),
            )
    canvas(fig, max(265, 68 * len(values) + 70))
    fig.update_yaxes(autorange="reversed", showgrid=False)
    fig.update_xaxes(side="top", showgrid=False)
    return fig
