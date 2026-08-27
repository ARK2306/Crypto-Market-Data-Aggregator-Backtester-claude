"""Tests for the headless chart renderer."""

from __future__ import annotations

from pathlib import Path

import matplotlib

from crypto_backtest import backtest, charts
from tests.conftest import make_candles


class TestCharts:
    def test_agg_backend_is_selected(self):
        assert matplotlib.get_backend().lower() == "agg"

    def test_writes_a_png(self, tmp_path):
        result = backtest.run_backtest(make_candles(range(100, 160)), 5, 20, 10000.0)
        output = tmp_path / "chart.png"
        path = charts.plot_backtest(result, "BTCUSDT", "1d", output_path=output)
        assert Path(path).exists() and output.stat().st_size > 1000

    def test_png_magic_bytes(self, tmp_path):
        result = backtest.run_backtest(make_candles(range(100, 160)), 5, 20, 10000.0)
        output = tmp_path / "chart.png"
        charts.plot_backtest(result, output_path=output)
        assert output.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"

    def test_handles_empty_result(self, tmp_path):
        result = backtest.run_backtest([], 5, 20, 10000.0)
        output = tmp_path / "empty.png"
        charts.plot_backtest(result, "BTCUSDT", "1d", output_path=output)
        assert output.exists()

    def test_handles_result_without_trades(self, tmp_path):
        result = backtest.run_backtest(make_candles([100] * 60), 5, 20, 10000.0)
        output = tmp_path / "flat.png"
        charts.plot_backtest(result, output_path=output)
        assert result.trades == [] and output.exists()

    def test_handles_insufficient_data(self, tmp_path):
        result = backtest.run_backtest(make_candles(range(100, 110)), 5, 20, 10000.0)
        output = tmp_path / "short.png"
        charts.plot_backtest(result, output_path=output)
        assert output.exists()

    def test_creates_missing_directories(self, tmp_path):
        result = backtest.run_backtest(make_candles(range(100, 160)), 5, 20, 10000.0)
        output = tmp_path / "nested" / "dir" / "chart.png"
        charts.plot_backtest(result, output_path=output)
        assert output.exists()

    def test_overwrites_existing_file(self, tmp_path):
        result = backtest.run_backtest(make_candles(range(100, 160)), 5, 20, 10000.0)
        output = tmp_path / "chart.png"
        output.write_bytes(b"stale")
        charts.plot_backtest(result, output_path=output)
        assert output.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"

    def test_default_title_mentions_windows_and_return(self):
        result = backtest.run_backtest(make_candles(range(100, 160)), 5, 20, 10000.0)
        title = charts._default_title(result, "BTCUSDT", "1d")
        assert "BTCUSDT 1d" in title and "SMA 5/20" in title and "%" in title

    def test_figures_are_closed(self, tmp_path):
        import matplotlib.pyplot as plt

        result = backtest.run_backtest(make_candles(range(100, 160)), 5, 20, 10000.0)
        for index in range(3):
            charts.plot_backtest(result, output_path=tmp_path / f"chart{index}.png")
        assert plt.get_fignums() == []
