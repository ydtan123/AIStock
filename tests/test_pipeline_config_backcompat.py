"""Back-compat mapping: legacy config.yaml keys still load."""
import logging
import textwrap

from pipeline.config import ConfigLoader


def write_config(tmp_path, content):
    p = tmp_path / "config.yaml"
    p.write_text(textwrap.dedent(content), encoding="utf-8")
    return p


def test_legacy_finrl_pipeline_key_maps_to_stock_selection(tmp_path, caplog):
    cfg_path = write_config(tmp_path, """
        finrl_pipeline:
          source: AISTOCK_DB
          start_date: "2020-01-01"
    """)
    with caplog.at_level(logging.WARNING):
        cfg = ConfigLoader(cfg_path).load()
    assert cfg["stock_selection"]["backend"] == "finrl"
    assert cfg["stock_selection"]["finrl"]["source"] == "AISTOCK_DB"
    assert any("deprecated" in r.message.lower() for r in caplog.records)


def test_legacy_ai_hedge_fund_key_maps_to_fast_evaluation(tmp_path):
    cfg_path = write_config(tmp_path, """
        ai_hedge_fund:
          model_name: deepseek-v4-pro
          selected_analysts: [warren_buffett]
    """)
    cfg = ConfigLoader(cfg_path).load()
    assert cfg["fast_evaluation"]["backend"] == "ai_hedge_fund"
    assert cfg["fast_evaluation"]["ai_hedge_fund"]["model_name"] == "deepseek-v4-pro"


def test_legacy_top_level_source_maps_to_data_update(tmp_path):
    cfg_path = write_config(tmp_path, """
        source: alpha_vantage
        alpha_vantage:
          api_key: KEY
    """)
    cfg = ConfigLoader(cfg_path).load()
    assert cfg["data_update"]["source"] == "alpha_vantage"
    assert cfg["data_update"]["alpha_vantage"]["api_key"] == "KEY"


def test_new_keys_take_precedence_over_legacy(tmp_path):
    cfg_path = write_config(tmp_path, """
        ai_hedge_fund:
          model_name: legacy-model
        fast_evaluation:
          backend: ai_hedge_fund
          ai_hedge_fund:
            model_name: new-model
    """)
    cfg = ConfigLoader(cfg_path).load()
    assert cfg["fast_evaluation"]["ai_hedge_fund"]["model_name"] == "new-model"
