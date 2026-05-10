from fetcher.base import FetcherBase


def create_fetcher(config: dict) -> FetcherBase:
    source = config.get("source", "alpha_vantage")
    if source == "alpha_vantage":
        from fetcher.alpha_vantage import AlphaVantageFetcher
        return AlphaVantageFetcher(api_key=config["alpha_vantage"]["api_key"])
    elif source == "yahoo":
        from fetcher.yahoo import YahooFetcher
        return YahooFetcher()
    else:
        raise ValueError(f"Unknown source: {source}")
