import sys
from pathlib import Path

from pipeline.config import ConfigLoader

_config: dict | None = None
_config_mtime: float = 0.0


def load_config(force: bool = False) -> dict:
    """Return cached config from config.yaml. Revalidates when file changes."""
    global _config, _config_mtime

    config_path = Path(__file__).parent.parent / "config.yaml"
    if not config_path.exists():
        print(
            "config.yaml not found. Copy config.yaml.example to config.yaml "
            "and fill in values.",
            file=sys.stderr,
        )
        sys.exit(1)

    current_mtime = config_path.stat().st_mtime
    if not force and _config is not None and current_mtime == _config_mtime:
        return _config

    _config_mtime = current_mtime
    loader = ConfigLoader(config_path)
    _config = loader.load()
    return _config
