# Feature Descriptions

The model uses a 5-day rolling input window. Features are named `d{1–5}_{name}` where `d1` is the oldest day and `d5` is the most recent. All price features are normalised relative to the first day of the window.

## Price Features (25 features)

| Feature Name | Description |
|---|---|
| `d{1–5}_open` | Daily open price as % change relative to `d1` close. Measures gap between open and the window's anchor price. |
| `d{1–5}_high` | Daily high as % change relative to `d1` close. Captures intraday upside range. |
| `d{1–5}_low` | Daily low as % change relative to `d1` close. Captures intraday downside range. |
| `d{1–5}_close` | Daily close as % change relative to `d1` close. Primary price momentum signal across the window. |
| `d{1–5}_volume` | Daily volume as % change relative to `d1` volume. Measures trading activity intensity vs the window baseline. |

## Technical Indicator Features (135 features)

Each indicator is recorded on each of the 5 days (`d1_INDICATOR` … `d5_INDICATOR`), giving the model visibility into how the indicator evolved over the input window.

### Trend — Moving Averages

| Feature Name | Description |
|---|---|
| `d{1–5}_SMA_20` | 20-day Simple Moving Average. Arithmetic mean of closing prices over the past 20 sessions. Smooths short-term noise; price above SMA_20 signals near-term uptrend. |
| `d{1–5}_SMA_50` | 50-day Simple Moving Average. Medium-term trend benchmark. The 50/200 crossover ("Golden Cross" / "Death Cross") is one of the most-watched trend signals in technical analysis. |
| `d{1–5}_SMA_200` | 200-day Simple Moving Average. Long-term trend baseline used by institutional investors. Price above SMA_200 is a widely accepted bull-market indicator. |
| `d{1–5}_EMA_12` | 12-day Exponential Moving Average. Weights recent prices more heavily than an SMA, reacts faster to new information. The faster of the two MACD components. |
| `d{1–5}_EMA_26` | 26-day Exponential Moving Average. Slower EMA component used as the baseline in MACD calculations. |

### Momentum — Oscillators

| Feature Name | Description |
|---|---|
| `d{1–5}_RSI_14` | 14-day Relative Strength Index (0–100). Measures the speed and magnitude of recent price changes. Above 70 is conventionally overbought; below 30 is oversold. Useful for spotting reversals and confirming trend strength. |
| `d{1–5}_MACD_12_26_9` | MACD line — difference between EMA_12 and EMA_26. Positive values indicate near-term momentum exceeds long-term; negative values indicate the reverse. The core trend-following momentum signal. |
| `d{1–5}_MACDs_12_26_9` | MACD Signal line — 9-day EMA of the MACD line. Crossovers between the MACD line and its signal line are the canonical buy/sell triggers. |
| `d{1–5}_MACDh_12_26_9` | MACD Histogram — difference between MACD line and signal line. Positive histogram means MACD is above its signal (bullish momentum building); negative means bearish. Growing histogram = accelerating momentum. |
| `d{1–5}_STOCHk_14_3_3` | Stochastic %K (14-day). Positions the current close relative to the high–low range over 14 days, expressed as 0–100. High values mean close is near the top of its range. |
| `d{1–5}_STOCHd_14_3_3` | Stochastic %D — 3-day SMA of %K, acting as the signal line. %K crossing above %D is a bullish signal; crossing below is bearish. |
| `d{1–5}_MOM_10` | 10-day Momentum. Raw difference between current close and the close 10 days earlier. Direct measure of price change velocity; sign shows direction, magnitude shows speed. |
| `d{1–5}_ROC_10` | 10-day Rate of Change (%). Percentage change in price over 10 days. Normalised version of momentum; comparable across stocks at different price levels. |
| `d{1–5}_TSI` | True Strength Index. Double-smoothed ratio of price change to absolute price change. Oscillates between roughly −100 and +100; zero-line crossovers and divergences signal trend changes. |
| `d{1–5}_UO` | Ultimate Oscillator. Weighted average of three oscillators with different lookback periods (7, 14, 28 days) to reduce false signals caused by a single timeframe. Values above 70 suggest overbought; below 30 suggest oversold. |
| `d{1–5}_TRIX_18` | TRIX (18-day). Percentage change of the triple-smoothed 18-day EMA. The triple smoothing filters noise, leaving only significant trend moves. Positive = uptrend; negative = downtrend. |

### Volatility

| Feature Name | Description |
|---|---|
| `d{1–5}_BBL_20_2.0` | Bollinger Band Lower — 20-day SMA minus 2 standard deviations. Price touching the lower band signals potential oversold condition or high volatility. |
| `d{1–5}_BBU_20_2.0` | Bollinger Band Upper — 20-day SMA plus 2 standard deviations. Price touching the upper band signals potential overbought condition. The gap between bands (bandwidth) measures volatility contraction and expansion. |
| `d{1–5}_ATRr_14` | Average True Range (14-day, relative). Measures average daily price range as a fraction of the close. Pure volatility measure with no directional bias — larger values mean larger expected moves. |
| `d{1–5}_STDEV_20` | 20-day standard deviation of closing prices. Direct measure of dispersion in absolute price terms. |
| `d{1–5}_ZSCORE_20` | 20-day Z-Score. How many standard deviations the current close is above or below its 20-day mean. Extreme Z-scores (+2 / −2) indicate statistically unusual price levels. |
| `d{1–5}_KURTOSIS_20` | 20-day kurtosis of returns. Measures the "fat-tailedness" of recent return distribution. High kurtosis indicates occasional extreme moves (gap-ups/downs); low kurtosis means steadier drift. |

### Trend Strength

| Feature Name | Description |
|---|---|
| `d{1–5}_ADX_14` | Average Directional Index (14-day, 0–100). Quantifies trend strength regardless of direction — does not indicate up or down. Below 20 = weak/ranging market; above 25 = trending; above 40 = strong trend. |
| `d{1–5}_CCI_14` | Commodity Channel Index (14-day). Measures deviation of price from its statistical mean, scaled by typical volatility. Above +100 signals a strong uptrend; below −100 signals a strong downtrend. |
| `d{1–5}_WILLR_14` | Williams %R (14-day, 0 to −100). Inverse of Stochastic %K. Values near 0 indicate overbought conditions; values near −100 indicate oversold. Useful for spotting short-term reversals. |

### Volume & Money Flow

| Feature Name | Description |
|---|---|
| `d{1–5}_OBV` | On-Balance Volume. Cumulative volume indicator — adds volume on up days, subtracts on down days. OBV rising alongside price confirms the trend; divergence (price up, OBV flat/down) is a bearish warning. |
| `d{1–5}_CMF_20` | Chaikin Money Flow (20-day). Measures the volume-weighted accumulation/distribution over 20 days (range −1 to +1). Positive values indicate buying pressure (accumulation); negative indicate selling pressure (distribution). |

## Sector Features (one-hot encoded)

| Feature Name | Description |
|---|---|
| `sector_{NAME}` | Binary indicator (1 or 0) for the stock's GICS sector. One column per distinct sector present in the training data (e.g. `sector_Technology`, `sector_Healthcare`, `sector_Energy`). Only one `sector_*` column is 1 for any given stock; all others are 0. Allows the model to learn sector-specific growth base rates. Stocks with an unknown or missing sector are encoded as `sector_Unknown`. |
