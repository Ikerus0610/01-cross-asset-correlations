"""Streamlit entry point. Run with streamlit run app.py."""

from hashlib import sha256
from lab.yahoo import market_prices

import pandas as pd
import streamlit as st

from lab import charts
from lab.data import DataError, PROXIES, TICKERS, load_csv
from lab.stats import (
    WINDOWS,
    correlation,
    downside_summary,
    pair_matrix,
    rolling_correlations,
    tail_sample,
)

st.set_page_config(
    page_title="Cross-Asset Correlation Lab", layout="wide", page_icon="📊"
)
st.html("""<style>
.stMainBlockContainer {max-width:1280px;padding-top:4rem;padding-bottom:3rem}
[data-testid="stDateInput"] input {font-size:0.85rem}
[data-testid="stSidebar"] {border-right:1px solid #d5e2df}
[data-testid="stSidebar"] .stSidebarBlockContainer {padding-top:2rem}
h1,h2,h3 {letter-spacing:-.035em}
.mast {display:flex;align-items:center;gap:10px;font-size:12px;font-weight:700;line-height:1.4;letter-spacing:.11em;color:#287768}
.mark {display:inline-flex;align-items:end;height:19px;gap:3px}
.mark i {width:5px;background:#287768}.mark i:nth-child(1){height:8px}
.mark i:nth-child(2){height:13px}.mark i:nth-child(3){height:19px}
.lab-title {font-size:clamp(32px,3.7vw,54px);font-weight:680;letter-spacing:-.055em;line-height:1.1;margin:.4rem 0 .45rem}
.st-key-signal {background:#123C3C;border-radius:10px;padding:1.05rem 1.35rem;color:#fff}
.st-key-signal p,.st-key-signal h3 {color:#fff}
.st-key-signal h3 {font-size:1.65rem;line-height:1.1}
.st-key-signal [data-testid="stCaptionContainer"] p {color:#C0DDD7}
.st-key-navigation div[role="radiogroup"] {gap:.4rem}
.st-key-navigation label {border:1px solid #ccdcd7;border-radius:6px;padding:.35rem .75rem;margin:0}
.st-key-navigation label:has(input:checked) {background:#e6f4ef;border-color:#19776b}
.st-key-navigation label:focus-within {outline:2px solid #19776b}
.st-key-navigation label>div:first-child {width:0;overflow:hidden;margin:0}
</style>""")


def span(frame):
    if frame.empty:
        return "No observations"
    return f"{frame.index[0]:%d %b %Y} – {frame.index[-1]:%d %b %Y}"


def pct(v, digits=2):
    return "N/D" if pd.isna(v) else f"{v:+.{digits}%}"


def coefficient(v):
    return "N/D" if pd.isna(v) else f"{v:+.3f}"


def chart(fig):
    st.plotly_chart(fig, width="stretch", theme=None, config={"displayModeBar": False})


def range_picker(title, idx, default, key):
    selection = st.date_input(
        title,
        value=default,
        min_value=idx[0].date(),
        max_value=idx[-1].date(),
        key=key,
        format="YYYY-MM-DD",
    )
    if len(selection) != 2:
        st.info(f"Choose an end date for {title.lower()}.")
        st.stop()
    return selection


def detail(sample, title):
    with st.expander(f"{title} · {len(sample)} sessions"):
        if sample.empty:
            st.write("No sessions meet this condition.")
            return
        st.caption(
            "One row per qualifying SPY session, worst first. Returns are percentages. N/D denotes a missing return."
        )
        rows = sample.sort_values("SPY", kind="stable").copy()
        rows.index = rows.index.strftime("%Y-%m-%d")
        formatted = rows.map(lambda v: "N/D" if pd.isna(v) else f"{v * 100:+.5f}%")
        st.dataframe(formatted, width="stretch")
        st.download_button(
            "Download session returns (decimal CSV)",
            rows.to_csv().encode(),
            file_name="selected_session_returns.csv",
            key=f"download_{title}",
        )


def summary_table(summary):
    rows = summary.copy()
    rows.insert(0, "Proxy", rows.index.map(PROXIES))
    rows["mean"] = rows["mean"].map(pct)
    rows["median"] = rows["median"].map(pct)
    rows["positive"] = rows["positive"].map(
        lambda x: "N/D" if pd.isna(x) else f"{x:.1%}"
    )
    rows["corr"] = [
        coefficient(v) if not why else f"N/D · {why}"
        for v, why in zip(rows["corr"], rows.reason)
    ]
    st.dataframe(
        rows.drop(columns="reason")
        .rename_axis("Ticker")
        .rename(
            columns={
                "n": "Valid days",
                "mean": "Mean",
                "median": "Median",
                "positive": "Positive %",
                "positive_n": "Positive days",
                "corr": "Pearson vs SPY",
            }
        ),
        width="stretch",
    )


def downside(periods, rule, fall):
    blocks = []
    for name, period in periods:
        sample, cutoff = tail_sample(period, rule, fall)
        blocks.append((name, period, sample, cutoff, downside_summary(sample)))
    name, period, sample, cutoff, stats = blocks[0]
    medians = stats["median"].dropna()
    with st.container(key="signal"):
        st.caption(
            ("PERIOD A  /  " if len(blocks) > 1 else "")
            + "HIGHEST MEDIAN ON SELECTED SPY SESSIONS"
        )
        if medians.empty:
            st.subheader("No qualifying returns")
            st.write("Try a longer period or a less restrictive threshold.")
        else:
            winners = medians[medians == medians.max()].index
            st.subheader(f"{' / '.join(winners)}   {pct(medians.max())}")
            evidence = " · ".join(
                f"{int(stats.loc[w, 'n'])} valid {w} returns" for w in winners
            )
            st.write(
                f"{', '.join(PROXIES[t] for t in winners)}  ·  {evidence}  ·  {len(sample)} qualifying SPY sessions  ·  "
                f"Effective SPY cutoff ≤ {pct(cutoff, 4)}"
            )
    if len(blocks) > 1:
        st.caption(
            "Each percentile cutoff is recalculated within its own period."
            if rule != "Fixed decline"
            else "The same fixed decline threshold applies to both periods."
        )
    for name, period, sample, cutoff, stats in blocks:
        st.caption(
            f"{name}  ·  {span(period)}  ·  {period.SPY.count():,} valid SPY returns  ·  "
            f"{len(sample)} selected  ·  SPY ≤ {pct(cutoff, 4)}"
        )
        detail(sample, f"Inspect {name.lower()} dates and returns")
    st.subheader("Median return by asset")
    chart(charts.median_chart([(b[0], b[-1]) for b in blocks]))
    st.subheader("Conditional return statistics")
    st.caption(
        "Mean and median measure the size of the return. Positive % counts gains among valid days. Pearson measures co-movement within those same sessions."
    )
    for name, _, _, _, stats in blocks:
        if len(blocks) > 1:
            st.markdown(f"**{name}**")
        summary_table(stats)


def instrument_label(ticker):
    return f"{ticker} · {PROXIES[ticker]}"


def pair_view(period):
    c1, c2, c3 = st.columns(3)
    a = c1.selectbox("First asset", TICKERS, format_func=instrument_label)
    others = [t for t in TICKERS if t != a]
    b = c2.selectbox(
        "Second asset",
        others,
        index=others.index("IEF") if "IEF" in others else 0,
        format_func=instrument_label,
    )
    method = c3.selectbox(
        "Correlation method", ["Pearson", "Spearman"], key="pair_method"
    )
    points = period[[a, b]].dropna()
    estimate = correlation(period[a], period[b], method)
    series = {w: rolling_correlations(period[a], period[b], w, method) for w in WINDOWS}
    st.subheader(f"{a} × {b}")
    st.caption(f"Selected interval  ·  {span(period)}  ·  {method} correlation")
    rows = [
        {
            "Estimate": "Full period",
            "Correlation": coefficient(estimate.value),
            "Valid pairs": estimate.n,
            "Observation interval": span(points),
            "Status": estimate.reason or "Available",
        }
    ]
    for w, values in series.items():
        available = values.dropna()
        if len(available):
            end = values.index.get_loc(available.index[-1])
            window = period.iloc[end - w + 1 : end + 1]
            rows.append(
                {
                    "Estimate": f"Latest {w} sessions",
                    "Correlation": coefficient(available.iloc[-1]),
                    "Valid pairs": w,
                    "Observation interval": span(window),
                    "Status": "Available",
                }
            )
        else:
            last = period.iloc[-w:]
            rows.append(
                {
                    "Estimate": f"Latest {w} sessions",
                    "Correlation": "N/D",
                    "Valid pairs": len(last[[a, b]].dropna()),
                    "Observation interval": span(last),
                    "Status": f"No complete, nonconstant {w}-session window",
                }
            )
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    st.subheader("Rolling correlation")
    st.caption(
        "Each point uses a complete trailing window inside the selected period. Gaps indicate an unavailable estimate."
    )
    chart(charts.rolling_chart(series))
    st.subheader("Daily return scatter")
    st.caption(f"{len(points):,} paired observations  ·  {span(points)}")
    chart(charts.scatter_chart(points, a, b))


def matrix_view(period, rule, fall):
    assets = st.multiselect(
        "Assets", TICKERS, default=TICKERS, format_func=instrument_label
    )
    c1, c2 = st.columns(2)
    scope = c1.radio(
        "Sample", ["All sessions", "SPY downside sessions"], horizontal=True
    )
    method = c2.radio("Correlation method", ["Pearson", "Spearman"], horizontal=True)
    if not assets:
        st.info("Choose at least one asset.")
        return
    sample = period
    cutoff_text = ""
    if scope == "SPY downside sessions":
        sample, cutoff = tail_sample(period, rule, fall)
        cutoff_text = (
            f"  ·  SPY ≤ {pct(cutoff, 4)}  ·  {period.SPY.count()} valid SPY returns"
        )
    st.subheader(f"{method} correlation matrix")
    st.caption(
        f"{span(period)}  ·  Session dates in scope: {len(sample)}{cutoff_text}. Each cell shows its own valid pair count."
    )
    values, counts, reasons = pair_matrix(sample[assets], method)
    chart(charts.heatmap(values, counts, reasons))
    missing = [
        (a, b, reasons.loc[a, b], counts.loc[a, b])
        for i, a in enumerate(assets)
        for b in assets[i:]
        if reasons.loc[a, b]
    ]
    if missing:
        st.caption(
            "N/D · Fewer than three paired observations or zero variance in at least one series."
        )
        st.dataframe(
            pd.DataFrame(missing, columns=["First", "Second", "Reason", "Valid pairs"]),
            hide_index=True,
        )


def main():
    with st.sidebar:
        st.markdown("### Research controls")
        blob, through = market_prices(TICKERS)
        identity = sha256(blob).hexdigest()
        try:
            if st.session_state.get("dataset_id") != identity:
                st.session_state["dataset"] = load_csv(blob)
                st.session_state["dataset_id"] = identity
            dataset = st.session_state["dataset"]
        except DataError as exc:
            st.error(str(exc))
            st.stop()
        idx = dataset.prices.index
        source = "Yahoo Finance · yfinance"
        st.caption(f"{source} · Last available date: {idx[-1]:%Y-%m-%d}")
        if idx[-1] < through:
            st.warning(f"Yahoo has not supplied the latest completed session ({through:%Y-%m-%d}).")
    st.html(
        '<div class="mast"><span class="mark"><i></i><i></i><i></i></span> QUANTITATIVE RESEARCH PORTFOLIO / 01</div><h1 class="lab-title">Cross-Asset Correlation Lab</h1>'
    )
    st.write(
        "What held up on the worst S&P 500 sessions, and did that relationship change over time?"
    )
    st.caption(
        f"{source.upper()}   /   Daily adjusted closes   /   Historical descriptive analysis"
    )
    view = st.radio(
        "Research view",
        ["Downside behavior", "Pair explorer", "Correlation matrix"],
        horizontal=True,
        label_visibility="collapsed",
        key="navigation",
    )
    with st.sidebar:
        st.divider()
        compare = view == "Downside behavior" and st.toggle("Compare two periods")
        middle = (len(idx) + 1) // 2
        key = identity[:16]
        dates = range_picker(
            "Period A" if compare else "Analysis period",
            idx,
            (idx[0].date(), idx[middle - 1 if compare else -1].date()),
            f"range_{key}_{compare}",
        )
        periods = [
            (
                "Period A" if compare else "Analysis period",
                dataset.returns.loc[str(dates[0]) : str(dates[1])],
            )
        ]
        if compare:
            other = range_picker(
                "Period B", idx, (idx[middle].date(), idx[-1].date()), f"second_{key}"
            )
            periods.append(
                ("Period B", dataset.returns.loc[str(other[0]) : str(other[1])])
            )
        rule, fall = "Worst 5%", 1.0
        if view != "Pair explorer":
            rule = st.selectbox(
                "SPY downside rule", ["Worst 5%", "Worst 10%", "Fixed decline"]
            )
            if rule == "Fixed decline":
                fall = st.number_input(
                    "SPY decline of at least (%)",
                    min_value=0.01,
                    max_value=100.0,
                    value=1.0,
                    step=0.25,
                )
        gap_count = len(dataset.missing_dates)
        blanks = int(dataset.missing_cells.sum())
        if gap_count or blanks:
            st.warning(
                f"{gap_count} missing sessions · {blanks} missing prices in supplied rows."
            )
        if dataset.returns.count().min() < 3:
            st.warning("At least one asset has fewer than three valid daily returns.")
        with st.expander("Data quality & coverage"):
            st.caption(
                "Full dataset. Missing sessions break the return on that date and the next session."
            )
            st.write(
                f"{len(idx) - gap_count:,} supplied dates · {gap_count} missing sessions"
            )
            if gap_count:
                st.write(
                    ", ".join(dataset.missing_dates.strftime("%Y-%m-%d")[:15])
                    + (" …" if gap_count > 15 else "")
                )
            st.dataframe(
                pd.DataFrame(
                    {
                        "Missing prices in rows": dataset.missing_cells,
                        "Valid returns": dataset.returns.count(),
                    }
                ),
                width="stretch",
            )
        with st.expander("Instrument guide"):
            for ticker, desc in PROXIES.items():
                st.write(f"**{ticker}** · {desc}")
            st.caption(
                "UUP reflects a futures basket against six currencies. USO rolls WTI contracts. Carry, collateral and fees can affect returns."
            )
    if view == "Downside behavior":
        downside(periods, rule, fall)
    elif view == "Pair explorer":
        pair_view(periods[0][1])
    else:
        matrix_view(periods[0][1], rule, fall)


if __name__ == "__main__":
    main()
