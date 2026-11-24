import json
import math

import pytest

from research_run_store import delete_run, get_run, list_runs, save_run


def test_research_runs_are_scoped_to_owner_and_can_be_reloaded(tmp_path):
    database = str(tmp_path / "research-runs.sqlite3")
    run_id = save_run(
        owner_id="issuer-a|subject-a",
        run_type="single_ticker",
        market="IDX",
        symbols=["BBCA"],
        parameters={"period": "5y", "fee_bps": 10},
        result={"total_return_pct": 12.5, "equity_curve": [{"date": "2026-01-01", "equity": 112.5}]},
        path=database,
    )

    rows = list_runs("issuer-a|subject-a", path=database)
    assert len(rows) == 1
    assert rows[0]["id"] == run_id
    assert rows[0]["symbols"] == ["BBCA"]

    saved = get_run("issuer-a|subject-a", run_id, path=database)
    assert saved["result"]["total_return_pct"] == 12.5
    assert list_runs("issuer-b|subject-b", path=database) == []
    with pytest.raises(KeyError):
        get_run("issuer-b|subject-b", run_id, path=database)


def test_research_run_delete_is_owner_scoped(tmp_path):
    database = str(tmp_path / "research-runs.sqlite3")
    run_id = save_run(
        owner_id="owner-a", run_type="multi_asset", market="US",
        symbols=["AAPL", "MSFT"], parameters={"max_positions": 2},
        result={"sharpe_ratio": 1.1}, path=database,
    )

    assert delete_run("owner-b", run_id, path=database) is False
    assert get_run("owner-a", run_id, path=database)["id"] == run_id
    assert delete_run("owner-a", run_id, path=database) is True
    with pytest.raises(KeyError):
        get_run("owner-a", run_id, path=database)


def test_research_run_json_sanitizes_non_finite_metrics(tmp_path):
    database = str(tmp_path / "research-runs.sqlite3")
    run_id = save_run(
        owner_id="owner-a", run_type="walk_forward", market="IDX",
        symbols=["BBRI"], parameters={"period": "5y"},
        result={"profit_factor": math.inf, "nested": {"metric": math.nan}},
        path=database,
    )

    saved = get_run("owner-a", run_id, path=database)
    assert saved["result"]["profit_factor"] is None
    assert saved["result"]["nested"]["metric"] is None
    json.dumps(saved["result"], allow_nan=False)



def test_research_run_requires_at_least_one_nonblank_symbol(tmp_path):
    database = str(tmp_path / "research-runs.sqlite3")
    with pytest.raises(ValueError, match="ticker valid"):
        save_run(
            owner_id="owner-a", run_type="single_ticker", market="IDX",
            symbols=[" ", ""], parameters={}, result={}, path=database,
        )
