import sys
import yaml
from pathlib import Path

_config: dict | None = None


def load_config() -> dict:
    global _config
    if _config is not None:
        return _config

    config_path = Path(__file__).parent / "config.yaml"
    if not config_path.exists():
        print(
            "config.yaml not found. Copy config.yaml.example to config.yaml "
            "and fill in values.",
            file=sys.stderr,
        )
        sys.exit(1)
    with open(config_path) as f:
        _config = yaml.safe_load(f)
    return _config
