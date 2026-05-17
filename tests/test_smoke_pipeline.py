import pytest


@pytest.mark.smoke
def test_pipeline_thread_import() -> None:
    """Verify finrl_pipeline imports work in a thread (mirrors _pipeline_thread_target)."""
    import sys
    import threading

    errors: list[str] = []

    def _thread_import():
        try:
            from finrl_pipeline import (
                MODELS_DIR,
                run_pipeline_and_save_report,
                run_predict_only,
            )
            assert callable(run_pipeline_and_save_report)
            assert callable(run_predict_only)
            assert MODELS_DIR.name == "models"
        except Exception as exc:
            errors.append(str(exc))

    t = threading.Thread(target=_thread_import)
    t.start()
    t.join(timeout=10)
    assert not t.is_alive(), "thread hung on import"
    assert not errors, f"thread import failed: {errors[0]}"


@pytest.mark.smoke
def test_pipeline_thread_target_importable() -> None:
    """app._pipeline_thread_target and app._predict_only_thread_target are importable."""
    from app import _pipeline_thread_target, _predict_only_thread_target
    assert callable(_pipeline_thread_target)
    assert callable(_predict_only_thread_target)
