# Project: Stock Data Ingestion & Visualization System

I need to design a system to fetch and save stock information. It must have the following features: 

## 1. Fetch stock data
fetch stock historical prices (OHLC), volume, financial indicators such as PE etc, and technical indicators from a given resource. The resource can be yahoo finance or alpha vantage. The resource is defined in a config file. The Alpha Vantage API key is also defined in the config file. The begin and end date is provided in the command line. The default begin date is 2000/1/1. The default end date is today. 

## 2. Store data into a database 
Design tables to save these information. Use MySQL for storage. Choose the most popular ORM such as sqlalchemy to access the database. But feel free to pick a better one. 

## 3. Web app to visulize data
Design a web-based app to display the stored information. The app provides an interface for customer to choose a stock and display its historical prices in an interactive graph, together with other information on the same page. 

## 4. Data refresh
I need to be able to fetch the latest price every day incrementally, means only the latest prices that are not in the database are fetched every day and saved into the database. If the other information has been updated in the resource side, fetch those information and update the database as well. 

# System Architecture Overview
- Ingestion Engine: A modular service that reads config.yaml, handles API rate limiting (especially for Alpha Vantage), and performs incremental updates.

- Database (MySQL): Optimized schema with indexing on symbol and date to ensure fast retrieval of historical data.

- ORM Layer: SQLAlchemy 2.0 using the "Unified" declarative style for modern, type-safe database interactions.

- Web Dashboard: A Streamlit application using Plotly for interactive Candlestick/OHLC charts.

# Project details

## 1. Project Structure
- `config.yaml`: Configuration for API keys and data sources.
- `models.py`: SQLAlchemy database models.
- `fetcher.py`: Logic for Alpha Vantage/Yahoo Finance fetching.
- `database.py`: Database connection and session management.
- `main.py`: CLI entry point for fetching data.
- `app.py`: Streamlit web application.

## 2. Database Schema (MySQL)
Design three main tables:
- `stocks`: Metadata about the tickers (id, symbol, company_name, sector).
- `daily_prices`: Historical OHLCV data. 
    - Columns: `id`, `stock_id`, `date` (Unique index on stock_id+date), `open`, `high`, `low`, `close`, `volume`.
- `stock_indicators`: Fundamental data.
    - Columns: `id`, `stock_id`, `pe_ratio`, `market_cap`, `dividend_yield`, `last_updated`.

## 3. Configuration (`config.yaml`)
```yaml
source: "alpha_vantage" # or "yahoo"
alpha_vantage:
  api_key: "YOUR_KEY_HERE"
database:
  url: "mysql+pymysql://user:pass@localhost/stock_db"
```

## 4. Implementation Requirements
Fetching Logic (fetcher.py & main.py)
Use argparse for CLI: --symbol, --start (default: 2000-01-01), --end (default: today).

Incremental Logic: Before fetching, query the DB for the max(date) for the given symbol. Fetch only from max(date) + 1 to today.

If the source is alpha_vantage, use the TIME_SERIES_DAILY_ADJUSTED and OVERVIEW functions.

If yahoo, use the yfinance library.

ORM Layer (models.py)
Use SQLAlchemy 2.0.

Implement an upsert (Update or Insert) logic for stock_indicators. If the record exists, update the values and the last_updated timestamp.

Web App (app.py)
Sidebar: Search box for Stock Symbol.

Main Panel:

Interactive Candlestick chart using plotly.graph_objects.

Metric cards for current PE Ratio, Market Cap, and Volume.

A dataframe view of the recent historical data.

## 5. Incremental Update Strategy
Check daily_prices for the latest entry per symbol.

Request data from API starting from that date.

Use mysql.connector or SQLAlchemy's ON DUPLICATE KEY UPDATE to handle cases where indicators might have changed even if the price date is the same.