---

# AAPL Comprehensive Technical Analysis — May 15, 2026

## Indicator Selection Rationale

I selected **8 indicators** spanning three complementary domains — **trend, momentum, and volatility** — to provide a multi-dimensional view without redundancy:

| # | Indicator | Category | Role |
|---|-----------|----------|------|
| 1 | `close_50_sma` | Trend | Medium-term trend direction & dynamic support |
| 2 | `close_200_sma` | Trend | Long-term strategic trend benchmark; Golden/Death Cross |
| 3 | `close_10_ema` | Trend | Short-term momentum & pullback entry zones |
| 4 | `rsi` | Momentum | Overbought/oversold extremes & divergence signals |
| 5 | `macd` | Momentum | Trend-change crossovers & momentum strength |
| 6 | `macds` | Momentum | Signal-line crossovers to trigger MACD trades |
| 7 | `boll_ub` | Volatility | Overbought/breakout zone identification |
| 8 | `boll_lb` | Volatility | Oversold/support zone identification |

**Why these avoid redundancy:** I deliberately omitted `macdh` (histogram) because it is trivially derived from `macd − macds` and provides no additional net information. I omitted `boll` (middle band / 20 SMA) because the 10 EMA and 50 SMA already serve as dynamic midpoints, making a third central average redundant. I omitted volume-based indicators (VWMA) and ATR because the Bollinger Bands already encode volatility structurally, and volume analysis is better done on raw volume bars for this report's scope.

---

## 1. Trend Architecture — Bullish Alignment Across All Timeframes

### The Golden Cross & Strategic Backdrop

The **50 SMA ($265.17)** sits comfortably above the **200 SMA ($258.19)** — a textbook **Golden Cross** configuration that has been in place for the entire analysis window. This is the foundational bullish signal: the medium-term trend is structurally stronger than the long-term trend, meaning momentum is compounding.

However, a nuanced observation: the **gap is narrowing**. On March 16, the spread was **$16.73** (50 SMA $261.96 vs. 200 SMA $245.23). By May 14, it had compressed to **$6.98**. The 200 SMA is steepening (+$12.96 over the period vs. the 50 SMA's +$3.21), meaning the long-term average is *catching up* to price. This is not bearish per se — it reflects an accelerating long-term trend — but when the 50/200 gap compresses too far, the market becomes vulnerable to a "whipsaw" if momentum falters. Traders should monitor whether the 50 SMA's slope continues to rise; if it flattens, the Golden Cross could be at risk.

### Short-Term Momentum: 10 EMA Rocketing

The **10 EMA** has surged from **$257.68 (March 16)** to **$289.68 (May 14)** — a gain of **$32.00 or +12.4% in two months**. The slope has *steepened* in recent weeks:

| Period | 10 EMA Change | 
|--------|--------------|
| Mar 16 – Apr 7 (22 days) | –$3.97 (dip) |
| Apr 7 – Apr 30 (23 days) | +$15.24 |
| Apr 30 – May 14 (14 days) | +$20.73 |

The acceleration is unmistakable. Price ($298.21) is **$8.53 above the 10 EMA** — a healthy but not extreme premium (~2.9%), suggesting the short-term trend has room to breathe without being dangerously stretched relative to its own EMA.

### Price Relative to All MAs — Bullish Hierarchy

```
Price ($298.21) > 10 EMA ($289.68) > 50 SMA ($265.17) > 200 SMA ($258.19)
```

This is the ideal bullish stack. Each faster average is above the slower one, and price is above them all. Historically, pullbacks to the 10 EMA in such a configuration tend to be bought — it serves as a "decision line" for trend-following entries.

---

## 2. Momentum Deep-Dive — Strength With Early Caution Flags

### RSI: Overbought But Not Yet Extreme

The **RSI sits at 74.83**, firmly in overbought territory (>70). It has been above 70 since **May 8** — now six consecutive trading days. The trajectory:

- **April 7:** 46.90 (near the price low of ~253.50)
- **April 15:** 62.26 (first push above 60)
- **May 8:** 72.94 (enters overbought)
- **May 13:** 75.98 (peak)
- **May 14:** 74.83 (slight tick down)

Critically, RSI has **not yet reached extreme levels** (80+). In powerful uptrends, RSI can oscillate between 65–85 for weeks without a meaningful reversal. The slight downtick on May 14 (from 75.98 to 74.83) while price only dipped fractionally ($298.87 → $298.21) is a very subtle negative divergence worth flagging but **not yet actionable**.

### MACD Analysis — Powerful Trend, Histogram Watch

The MACD complex tells a compelling story of momentum acceleration followed by potential stabilization:

| Date | MACD Line | Signal Line | Histogram (implied) |
|------|-----------|-------------|---------------------|
| Apr 7 | –1.66 | –2.65 | +0.99 |
| Apr 15 | +0.96 | –0.59 | +1.56 |
| Apr 23 | +3.92 | +2.11 | +1.81 |
| May 1 | +4.36 | +3.45 | +0.91 |
| May 8 | +7.29 | +5.31 | +1.99 |
| May 12 | +8.28 | +6.30 | +1.98 |
| May 13 | +8.89 | +6.82 | +2.07 |
| **May 14** | **+9.21** | **+7.30** | **+1.91** |

Key observations:

1. **Bullish crossover** occurred around April 7–8 when the MACD line decisively crossed above the signal line. This has been sustained for over five weeks — a durable signal.

2. **The MACD line is at +9.21** — an unusually high absolute value, underscoring how powerful this rally has been. The last time readings were this elevated would likely have been during prior parabolic advances.

3. **Histogram peaked at +2.07 on May 13 and ticked down to +1.91 on May 14.** This is the first contraction after several days of expansion. Isolated, one day of histogram contraction is meaningless noise, but if it continues to shrink over the next 2–3 sessions while the MACD line continues rising, it would constitute **momentum deceleration divergence** — a warning that the rate of change is slowing even as the trend persists.

4. **Both MACD and Signal lines are still rising** — the trend is intact. The histogram contraction is an early whisper, not a shout.

---

## 3. Volatility & Bollinger Band Analysis — Riding the Upper Band

### Band Structure

The Bollinger Bands are **widening aggressively**, reflecting the surge in realized volatility:

| Date | Upper Band | Lower Band | Band Width |
|------|-----------|-----------|------------|
| Mar 16 | $274.27 | $250.45 | $23.83 |
| Apr 7 | $260.71 | $245.15 | $15.56 |
| Apr 23 | $275.67 | $244.83 | $30.84 |
| May 8 | $291.12 | $254.80 | $36.32 |
| **May 14** | **$301.44** | **$258.25** | **$43.19** |

Band width has nearly **tripled** since early April. This is classic **expansion volatility** — price is trending strongly, stretching the bands outward. 

### Price Position Within Bands

Price ($298.21) is **$3.23 below the upper band ($301.44)** — just **1.1% away**. This is the closest the price has been to the upper band throughout the entire analysis window. In strong trends, prices can "ride the band" — repeatedly tagging or slightly exceeding it without reversing. However, this also means:

- **Any intraday push above $300–$301** would constitute a Bollinger Band breakout, which could trigger accelerated buying (band expansion continues) or a mean-reversion snap back toward the middle (~$279.85).
- The lower band at $258.25 aligns remarkably well with the 200 SMA at $258.19 — creating a **confluence support zone** around $258. This would be the "worst-case" retracement target in a pullback scenario.

---

## 4. Price Action Synthesis — The $300 Resistance Battle

The last three sessions tell a micro-story:

| Date | Open | High | Low | Close | Notes |
|------|------|------|-----|-------|-------|
| May 12 | $292.56 | $295.27 | $292.56 | $294.80 | Tight range, steady grind up |
| May 13 | $293.50 | **$300.92** | $293.50 | $298.87 | Pierced $300, closed below |
| May 14 | $299.82 | **$300.45** | $295.38 | $298.21 | Opened near $300, rejected again |

**Two consecutive days** with intraday highs above $300 but closes below. This suggests:
- **Psychological resistance at $300.** Round numbers act as magnets and barriers. The market is testing this level.
- The lower close on May 14 ($298.21) vs. May 13 ($298.87) despite a higher open ($299.82 vs. $293.50) indicates **selling pressure emerging at the highs**.
- The wider range on May 14 (high $300.45, low $295.38, range $5.07) vs. May 12 (range $2.71) shows **increased intraday volatility** — traders are fighting over direction near the round number.

---

## 5. Integrated Assessment — Bullish With Guarded Near-Term Caution

### Bullish Pillars (Medium-to-Long Term)
- **Golden Cross** firmly intact; all MAs rising in bullish alignment
- **MACD** deeply positive and still trending up — no crossover signal in sight
- **Price structure:** higher highs and higher lows across daily, weekly timeframes
- **Bollinger Bands expanding** — confirming trend strength, not contraction/coiling

### Caution Flags (Near-Term / Tactical)
- **RSI > 70 for six sessions** — overbought but not extreme; historically can persist
- **$300 psychological resistance** with two failed daily closes above
- **MACD histogram** ticked down for the first time — watch for continuation
- **50/200 SMA spread compressing** — if the 50 SMA flattens, the Golden Cross could weaken
- **Price hugging the upper Bollinger Band** — mean-reversion risk increases the longer it stays there

### Potential Scenarios

| Scenario | Trigger | Target | Probability Assessment |
|----------|---------|--------|----------------------|
| **Continuation** | Decisive close above $301 (upper band) | $310–$315 | Moderate — needs volume confirmation |
| **Consolidation** | Range-bound $290–$300 | 10 EMA ($289.68) as support | Higher probability near-term |
| **Pullback** | Close below 10 EMA ($289.68) | 50 SMA ($265) as magnet | Low but rising if RSI rolls over |
| **Reversal** | MACD bearish crossover + break below 50 SMA | 200 SMA ($258) | Low — no evidence yet |

---

## 6. Key Metrics Summary Table

| Metric | Latest Value | Signal | Interpretation |
|--------|-------------|--------|----------------|
| **Price (Close)** | $298.21 | — | Battling $300 resistance |
| **10 EMA** | $289.68 | 🟢 Bullish | Price +2.9% above; steep slope |
| **50 SMA** | $265.17 | 🟢 Bullish | Rising; medium-term support |
| **200 SMA** | $258.19 | 🟢 Bullish | Steepening; long-term support |
| **50/200 Spread** | +$6.98 | 🟡 Watch | Narrowing; monitor for whipsaw |
| **RSI (14)** | 74.83 | 🟡 Overbought | >70 for 6 days; not yet extreme (80+) |
| **MACD Line** | +9.21 | 🟢 Strong | Multi-month highs; momentum robust |
| **MACD Signal** | +7.30 | 🟢 Bullish | Rising in sync |
| **MACD Histogram** | +1.91 | 🟡 Watch | First contraction after expansion streak |
| **Bollinger Upper** | $301.44 | 🟡 Resistance | Price 1.1% below; breakout or rejection zone |
| **Bollinger Lower** | $258.25 | 🟢 Support | Confluence w/ 200 SMA at $258 |
| **Band Width** | $43.19 | 🟢 Expansion | Trend volatility increasing; healthy |
| **$300 Level** | — | 🔴 Resistance | Two intraday pierces, zero daily closes above |

---

### Bottom Line

AAPL's technical posture is **structurally bullish** with a textbook Golden Cross, ascending moving averages, and powerful MACD momentum. The rally from the early-April lows (~$253) to current levels (~$298) represents a ~17.6% gain in roughly five weeks — a torrid pace that has pushed RSI into overbought territory and drawn price within a hair of the upper Bollinger Band. The $300 round-number level is acting as near-term resistance, with two failed daily closes above it. The prudent stance is to **hold existing longs** and use any pullback toward the 10 EMA ($289–$290) or 50 SMA ($265) as potential re-entry or add-on zones. A decisive close above $301 (upper Bollinger Band) would signal the next leg higher; a close below the 10 EMA would warrant reducing exposure and waiting for a deeper reset.