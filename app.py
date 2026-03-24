import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import json
import os
from datetime import datetime, timedelta
import math

st.set_page_config(
    page_title="Nifty 50 Dip Buying Simulator",
    page_icon="📉",
    layout="wide",
)

# ── Dark theme CSS ──
st.markdown("""
<style>
    .stMetric .st-emotion-cache-1wivap2 { font-family: 'SF Mono', 'Fira Code', monospace; }
    div[data-testid="stMetricValue"] { font-size: 1.8rem; font-weight: 700; }
    div[data-testid="stMetricDelta"] { font-size: 0.9rem; }
</style>
""", unsafe_allow_html=True)


@st.cache_data
def load_data():
    """Load all Nifty OHLC JSON files."""
    data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
    files = sorted(f for f in os.listdir(data_dir) if f.startswith("NIFTY_FUT_") and f.endswith(".json"))
    all_records = []
    for f in files:
        with open(os.path.join(data_dir, f)) as fh:
            records = json.load(fh)
            all_records.extend(records)
    df = pd.DataFrame(all_records)
    df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)
    df = df.sort_values("date").drop_duplicates(subset="date").reset_index(drop=True)
    return df


def compute_xirr(cashflows_dates, cashflows_amounts, final_value, final_date):
    """XIRR via Newton-Raphson. cashflows are negative (investments), final_value is positive."""
    dates = list(cashflows_dates) + [final_date]
    amounts = list(cashflows_amounts) + [final_value]
    if len(dates) < 2:
        return None
    d0 = dates[0]
    year_fracs = [(d - d0).days / 365.25 for d in dates]

    def npv(r):
        return sum(a / (1 + r) ** t for a, t in zip(amounts, year_fracs))

    def dnpv(r):
        return sum(-t * a / (1 + r) ** (t + 1) for a, t in zip(amounts, year_fracs) if t != 0)

    rate = 0.1
    for _ in range(200):
        f = npv(rate)
        df = dnpv(rate)
        if abs(df) < 1e-12:
            break
        new_rate = rate - f / df
        if abs(new_rate - rate) < 1e-9:
            rate = new_rate
            break
        rate = max(-0.99, min(10, new_rate))

    if abs(npv(rate)) > 1:
        return None
    return rate * 100


def run_simulation(df, start_date, end_date, buy_amount, dip_threshold, strategy):
    """Run the dip-buying simulation."""
    mask = (df["date"].dt.date >= start_date) & (df["date"].dt.date <= end_date)
    data = df[mask].copy().reset_index(drop=True)
    if data.empty:
        return None, None

    # Compute ATH from all data up to start_date
    pre = df[df["date"].dt.date <= start_date]
    ath = pre["close"].max() if not pre.empty else 0

    purchases = []
    daily_records = []
    total_units = 0.0
    total_invested = 0.0
    last_buy_level = 0

    for _, row in data.iterrows():
        price = row["close"]
        dt = row["date"]
        ath = max(ath, price)
        drawdown_pct = ((ath - price) / ath) * 100 if ath > 0 else 0
        bought = False

        if strategy == "Cumulative":
            current_level = int(drawdown_pct // dip_threshold)
            while current_level > last_buy_level:
                last_buy_level += 1
                units = buy_amount / price
                total_units += units
                total_invested += buy_amount
                purchases.append({
                    "date": dt, "price": price, "ath": ath,
                    "drawdown_pct": last_buy_level * dip_threshold,
                    "amount": buy_amount, "units": units,
                    "total_invested": total_invested,
                    "portfolio_value": total_units * price,
                })
                bought = True
            if price >= ath:
                last_buy_level = 0
        else:  # Incremental
            current_level = int(drawdown_pct // dip_threshold)
            if current_level > last_buy_level and drawdown_pct >= dip_threshold:
                for lvl in range(last_buy_level + 1, current_level + 1):
                    units = buy_amount / price
                    total_units += units
                    total_invested += buy_amount
                    purchases.append({
                        "date": dt, "price": price, "ath": ath,
                        "drawdown_pct": lvl * dip_threshold,
                        "amount": buy_amount, "units": units,
                        "total_invested": total_invested,
                        "portfolio_value": total_units * price,
                    })
                    bought = True
            last_buy_level = current_level

        daily_records.append({
            "date": dt, "price": price, "ath": ath,
            "drawdown_pct": drawdown_pct,
            "portfolio_value": total_units * price,
            "total_invested": total_invested, "bought": bought,
        })

    daily_df = pd.DataFrame(daily_records)
    purchases_df = pd.DataFrame(purchases) if purchases else pd.DataFrame()
    return daily_df, purchases_df


# ── UI ──

st.title("📉 Nifty 50 Dip Buying Simulator")
st.caption("Buy ₹X of Nifty 50 ETF for every -Y% fall from all-time high. Backtest with real data from 2010–2026.")

df = load_data()
min_date = df["date"].min().date()
max_date = df["date"].max().date()

# Controls
col1, col2, col3, col4, col5 = st.columns([1, 1, 1, 1, 1.5])
with col1:
    start_date = st.date_input("Start Date", value=datetime(2020, 1, 1).date(), min_value=min_date, max_value=max_date)
with col2:
    end_date = st.date_input("End Date", value=max_date, min_value=min_date, max_value=max_date)
with col3:
    buy_amount = st.number_input("Buy Amount (₹)", value=100000, step=10000, min_value=1000)
with col4:
    dip_threshold = st.number_input("Dip Threshold (%)", value=1.0, step=0.5, min_value=0.5, max_value=20.0)
with col5:
    strategy = st.selectbox("Strategy", ["Cumulative", "Incremental"],
                            help="Cumulative: buy at each -N% level from ATH. Incremental: buy on each fresh -N% drop.")

daily_df, purchases_df = run_simulation(df, start_date, end_date, buy_amount, dip_threshold, strategy)

if daily_df is None or daily_df.empty:
    st.warning("No data in selected date range.")
    st.stop()

# ── Stats ──
last = daily_df.iloc[-1]
total_invested = last["total_invested"]
current_value = last["portfolio_value"]
pnl = current_value - total_invested
pnl_pct = (pnl / total_invested * 100) if total_invested > 0 else 0
max_dd = daily_df["drawdown_pct"].max()
n_purchases = len(purchases_df)
years = (daily_df["date"].iloc[-1] - daily_df["date"].iloc[0]).days / 365.25

total_units = purchases_df["units"].sum() if not purchases_df.empty else 0
avg_buy = total_invested / total_units if total_units > 0 else 0

xirr = None
if not purchases_df.empty:
    xirr = compute_xirr(
        purchases_df["date"].tolist(),
        [-a for a in purchases_df["amount"].tolist()],
        current_value,
        daily_df["date"].iloc[-1],
    )

st.divider()

c1, c2, c3, c4, c5, c6, c7 = st.columns(7)
c1.metric("Total Invested", f"₹{total_invested:,.0f}", f"{n_purchases} purchases / {years:.1f}y")
c2.metric("Current Value", f"₹{current_value:,.0f}", f"@ Nifty {last['price']:,.0f}")
c3.metric("Absolute Return", f"{pnl_pct:+.1f}%", f"₹{abs(pnl):,.0f} {'profit' if pnl >= 0 else 'loss'}")
c4.metric("XIRR (IRR)", f"{xirr:.1f}%" if xirr is not None else "N/A", "annualized, time-weighted")
c5.metric("Avg Buy Price", f"₹{avg_buy:,.0f}", f"{((last['price'] - avg_buy) / avg_buy * 100):+.1f}% vs current")
c6.metric("Max Drawdown", f"{max_dd:.1f}%", "from ATH")
c7.metric("Total Units", f"{total_units:,.2f}", "Nifty 50 ETF")

st.divider()

# ── Charts ──
chart_col1, chart_col2 = st.columns(2)

with chart_col1:
    st.subheader("Nifty 50 Price & Buy Points")
    fig1 = go.Figure()
    fig1.add_trace(go.Scatter(
        x=daily_df["date"], y=daily_df["price"],
        name="Nifty 50", line=dict(color="#7c5cfc", width=1.5),
    ))
    fig1.add_trace(go.Scatter(
        x=daily_df["date"], y=daily_df["ath"],
        name="ATH", line=dict(color="rgba(255,192,72,0.4)", width=1, dash="dash"),
    ))
    if not purchases_df.empty:
        fig1.add_trace(go.Scatter(
            x=purchases_df["date"], y=purchases_df["price"],
            name=f"Buy (₹{buy_amount:,.0f})", mode="markers",
            marker=dict(color="#00d26a", size=7, symbol="triangle-up"),
            hovertemplate="Buy @ %{y:,.0f}<br>%{x}<extra></extra>",
        ))
    fig1.update_layout(
        template="plotly_dark", height=400, margin=dict(l=0, r=0, t=10, b=0),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
        yaxis=dict(gridcolor="rgba(255,255,255,0.05)"),
        xaxis=dict(gridcolor="rgba(255,255,255,0.05)"),
    )
    st.plotly_chart(fig1, use_container_width=True)

with chart_col2:
    st.subheader("Portfolio Value vs Total Invested")
    fig2 = go.Figure()
    fig2.add_trace(go.Scatter(
        x=daily_df["date"], y=daily_df["portfolio_value"],
        name="Portfolio Value", line=dict(color="#00d26a", width=1.5),
        fill="tozeroy", fillcolor="rgba(0,210,106,0.08)",
    ))
    fig2.add_trace(go.Scatter(
        x=daily_df["date"], y=daily_df["total_invested"],
        name="Total Invested", line=dict(color="#ff4757", width=1.5, dash="dash"),
    ))
    fig2.update_layout(
        template="plotly_dark", height=400, margin=dict(l=0, r=0, t=10, b=0),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
        yaxis=dict(gridcolor="rgba(255,255,255,0.05)", tickprefix="₹"),
        xaxis=dict(gridcolor="rgba(255,255,255,0.05)"),
    )
    st.plotly_chart(fig2, use_container_width=True)

# Drawdown chart
st.subheader("Drawdown from ATH (%)")
fig3 = go.Figure()
fig3.add_trace(go.Scatter(
    x=daily_df["date"], y=-daily_df["drawdown_pct"],
    name="Drawdown", line=dict(color="#ff4757", width=1.5),
    fill="tozeroy", fillcolor="rgba(255,71,87,0.1)",
))
max_levels = min(int(max_dd // dip_threshold), 10)
for i in range(1, max_levels + 1):
    fig3.add_hline(y=-(i * dip_threshold), line_dash="dot",
                   line_color="rgba(255,71,87,0.2)", line_width=1,
                   annotation_text=f"-{i * dip_threshold:.0f}%",
                   annotation_font_color="rgba(255,71,87,0.4)")
fig3.update_layout(
    template="plotly_dark", height=350, margin=dict(l=0, r=0, t=10, b=0),
    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
    yaxis=dict(gridcolor="rgba(255,255,255,0.05)", ticksuffix="%"),
    xaxis=dict(gridcolor="rgba(255,255,255,0.05)"),
    showlegend=False,
)
st.plotly_chart(fig3, use_container_width=True)

# ── Purchase Log ──
st.subheader("Purchase Log")
if not purchases_df.empty:
    display_df = purchases_df.copy()
    display_df["#"] = range(1, len(display_df) + 1)
    display_df["pnl_pct"] = ((display_df["portfolio_value"] - display_df["total_invested"]) / display_df["total_invested"] * 100)
    display_df["date"] = display_df["date"].dt.strftime("%Y-%m-%d")
    display_df = display_df.rename(columns={
        "date": "Date", "price": "Nifty Price", "ath": "ATH",
        "drawdown_pct": "Drawdown %", "amount": "Amount",
        "units": "Units", "total_invested": "Cumulative Invested",
        "portfolio_value": "Portfolio Value", "pnl_pct": "P&L %",
    })
    st.dataframe(
        display_df[["#", "Date", "Nifty Price", "ATH", "Drawdown %", "Amount",
                     "Units", "Cumulative Invested", "Portfolio Value", "P&L %"]],
        use_container_width=True,
        height=400,
        column_config={
            "Nifty Price": st.column_config.NumberColumn(format="₹%,.0f"),
            "ATH": st.column_config.NumberColumn(format="₹%,.0f"),
            "Drawdown %": st.column_config.NumberColumn(format="-%.1f%%"),
            "Amount": st.column_config.NumberColumn(format="₹%,.0f"),
            "Units": st.column_config.NumberColumn(format="%.2f"),
            "Cumulative Invested": st.column_config.NumberColumn(format="₹%,.0f"),
            "Portfolio Value": st.column_config.NumberColumn(format="₹%,.0f"),
            "P&L %": st.column_config.NumberColumn(format="%+.2f%%"),
        },
        hide_index=True,
    )
else:
    st.info("No purchases triggered in this date range with the selected threshold.")
