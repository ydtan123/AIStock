from abc import ABC, abstractmethod
from datetime import date
import pandas as pd


class FetcherBase(ABC):

    @abstractmethod
    def get_daily(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        """Return DataFrame with columns: date, open, high, low, close, adj_close, volume, dividend_amount, split_coefficient."""

    @abstractmethod
    def get_overview(self, symbol: str) -> dict:
        """Return dict of fundamental data fields matching OVERVIEW schema."""

    @abstractmethod
    def get_listing(self) -> pd.DataFrame:
        """Return DataFrame with columns: symbol, name, exchange, asset_type, status."""
