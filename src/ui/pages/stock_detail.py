from __future__ import annotations

import streamlit as st


@st.dialog("Stock Details", width="large")
def render(ctx, symbol: str):
    """Dialog showing basic info, fundamentals, and technical indicators for a stock."""
    from repository import StockRepository

    _repo = StockRepository()
    stock = _repo.find_stock(symbol)
    if not stock:
        st.warning(f"Stock **{symbol}** not found in database.")
        return

    indicator = _repo.get_indicator(stock.id)
    snapshot = _repo.get_snapshot(stock.id)

    def _abbr(v):
        """Abbreviate large numbers: 1.5B, 300M, 50K."""
        if v is None:
            return "N/A"
        v = float(v)
        sign = "-" if v < 0 else ""
        v = abs(v)
        if v >= 1e12:
            return f"{sign}${v/1e12:.2f}T"
        if v >= 1e9:
            return f"{sign}${v/1e9:.2f}B"
        if v >= 1e6:
            return f"{sign}${v/1e6:.0f}M"
        if v >= 1e3:
            return f"{sign}${v/1e3:.0f}K"
        return f"{sign}${v:,.0f}"

    # ── Header ──
    st.markdown(f"## {symbol} — {stock.name or 'N/A'}")
    st.caption(f"Exchange: {stock.exchange or 'N/A'}  |  Sector: {stock.sector or 'N/A'}  |  Industry: {stock.industry or 'N/A'}")

    st.divider()

    t1, t2, t3 = st.tabs(["Company", "Fundamentals", "Technical"])

    # ── Tab 1: Company Info ──
    with t1:
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**General**")
            rows = [
                ("Country", stock.country),
                ("Currency", stock.currency),
                ("CIK", stock.cik),
                ("Fiscal Year End", stock.fiscal_year_end),
            ]
            for label, val in rows:
                st.caption(f"{label}: {val or 'N/A'}")

        with c2:
            st.markdown("**Shares**")
            shares_rows = [
                ("Outstanding", f"{stock.shares_outstanding:,}" if stock.shares_outstanding else None),
                ("Float", f"{stock.shares_float:,}" if stock.shares_float else None),
                ("Insiders %", f"{indicator.pct_insiders:.2f}%" if indicator and indicator.pct_insiders else None),
                ("Institutions %", f"{indicator.pct_institutions:.2f}%" if indicator and indicator.pct_institutions else None),
            ]
            for label, val in shares_rows:
                st.caption(f"{label}: {val or 'N/A'}")

        if stock.description:
            with st.expander("Description", expanded=False):
                st.markdown(stock.description or "")

    # ── Tab 2: Fundamentals ──
    with t2:
        if indicator is None:
            st.info("No fundamental data available.")
        else:
            _fmt_num = lambda v, decimals=2: f"{v:,.{decimals}f}" if v is not None else "N/A"
            _fmt_pct = lambda v: f"{v:.2f}%" if v is not None else "N/A"

            c1, c2 = st.columns(2)
            with c1:
                st.markdown("**Valuation**")
                val_fields = [
                    ("Market Cap", _abbr(indicator.market_cap) if indicator.market_cap else "N/A"),
                    ("PE Ratio", _fmt_num(indicator.pe_ratio)),
                    ("Forward PE", _fmt_num(indicator.forward_pe)),
                    ("PEG Ratio", _fmt_num(indicator.peg_ratio)),
                    ("Price/Book", _fmt_num(indicator.price_to_book)),
                    ("Price/Sales", _fmt_num(indicator.price_to_sales_ttm)),
                    ("EV/EBITDA", _fmt_num(indicator.ev_to_ebitda)),
                    ("Dividend Yield", _fmt_pct(indicator.dividend_yield)),
                ]
                for label, val in val_fields:
                    st.caption(f"{label}: {val}")

                st.markdown("**Profitability**")
                prof_fields = [
                    ("EPS", _fmt_num(indicator.eps)),
                    ("ROE", _fmt_pct(indicator.roe_ttm)),
                    ("ROA", _fmt_pct(indicator.roa_ttm)),
                    ("Profit Margin", _fmt_pct(indicator.profit_margin)),
                    ("Operating Margin", _fmt_pct(indicator.operating_margin_ttm)),
                ]
                for label, val in prof_fields:
                    st.caption(f"{label}: {val}")

            with c2:
                st.markdown("**Financials**")
                fin_fields = [
                    ("Revenue (TTM)", _abbr(indicator.revenue_ttm) if indicator.revenue_ttm else "N/A"),
                    ("Gross Profit (TTM)", _abbr(indicator.gross_profit_ttm) if indicator.gross_profit_ttm else "N/A"),
                    ("EBITDA", _abbr(indicator.ebitda) if indicator.ebitda else "N/A"),
                    ("Book Value/Share", _fmt_num(indicator.book_value)),
                    ("Rev/Share (TTM)", _fmt_num(indicator.revenue_per_share_ttm)),
                    ("DPS", _fmt_num(indicator.dividend_per_share)),
                ]
                for label, val in fin_fields:
                    st.caption(f"{label}: {val}")

                st.markdown("**Growth**")
                growth_fields = [
                    ("Earnings Growth YoY", _fmt_pct(indicator.qtr_earnings_growth_yoy)),
                    ("Revenue Growth YoY", _fmt_pct(indicator.qtr_revenue_growth_yoy)),
                ]
                for label, val in growth_fields:
                    st.caption(f"{label}: {val}")

                st.markdown("**Analyst Consensus**")
                if indicator.analyst_target_price:
                    buys = (indicator.analyst_strong_buy or 0) + (indicator.analyst_buy or 0)
                    total = buys + (indicator.analyst_hold or 0) + (indicator.analyst_sell or 0) + (indicator.analyst_strong_sell or 0)
                    consensus = (
                        f"{buys} Buy / "
                        f"{indicator.analyst_hold or 0} Hold / "
                        f"{(indicator.analyst_sell or 0) + (indicator.analyst_strong_sell or 0)} Sell"
                        if total > 0 else "N/A"
                    )
                    st.caption(f"Target Price: ${_fmt_num(indicator.analyst_target_price)}")
                    st.caption(f"Consensus: {consensus}")
                else:
                    st.caption("No analyst data")

    # ── Tab 3: Technical Indicators ──
    with t3:
        if snapshot is None:
            st.info("No snapshot data available. Run the daily pipeline first.")
        else:
            c1, c2 = st.columns(2)
            with c1:
                st.markdown("**Price**")
                price_fields = [
                    ("Latest Close", _fmt_num(snapshot.close) if snapshot.close else "N/A"),
                    ("Latest Date", str(snapshot.latest_date) if snapshot.latest_date else "N/A"),
                    ("Volume", f"{snapshot.volume:,}" if snapshot.volume else "N/A"),
                ]
                for label, val in price_fields:
                    st.caption(f"{label}: {val}")

                st.markdown("**Momentum**")
                mom_fields = [
                    ("RSI (14)", _fmt_num(snapshot.rsi_14)),
                    ("MACD", _fmt_num(snapshot.macd, 4) if snapshot.macd else "N/A"),
                    ("SMA 20", _fmt_num(snapshot.sma_20)),
                    ("SMA 50", _fmt_num(snapshot.sma_50)),
                ]
                for label, val in mom_fields:
                    st.caption(f"{label}: {val}")

            with c2:
                st.markdown("**Risk & Valuation**")
                risk_fields = [
                    ("Beta", _fmt_num(snapshot.beta)),
                    ("PE Ratio", _fmt_num(snapshot.pe_ratio)),
                    ("ROE", _fmt_pct(snapshot.roe_ttm) if snapshot.roe_ttm else "N/A"),
                    ("Dividend Yield", _fmt_pct(snapshot.dividend_yield) if snapshot.dividend_yield else "N/A"),
                ]
                for label, val in risk_fields:
                    st.caption(f"{label}: {val}")

                if indicator:
                    st.markdown("**52-Week Range**")
                    st.caption(f"High: ${_fmt_num(indicator.week_52_high) if indicator.week_52_high else 'N/A'}")
                    st.caption(f"Low: ${_fmt_num(indicator.week_52_low) if indicator.week_52_low else 'N/A'}")
                    st.caption(f"MA 50: ${_fmt_num(indicator.ma_50_day) if indicator.ma_50_day else 'N/A'}")
                    st.caption(f"MA 200: ${_fmt_num(indicator.ma_200_day) if indicator.ma_200_day else 'N/A'}")
