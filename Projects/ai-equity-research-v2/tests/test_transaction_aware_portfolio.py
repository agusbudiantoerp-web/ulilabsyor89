import pandas as pd
import pytest

from transaction_aware_portfolio import run_transaction_aware_portfolio


def test_transaction_replay_marks_partial_sell_and_dividend_into_portfolio_value():
    dates = pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-03"])
    result = run_transaction_aware_portfolio(
        {"AAA": pd.Series([100.0, 110.0, 120.0], index=dates)},
        {"AAA": "IDR"},
        [
            {"date": "2026-01-01", "event_type": "DEPOSIT", "amount": 1000},
            {"date": "2026-01-01", "event_type": "BUY", "amount": 1000, "ticker": "AAA", "quantity": 10, "price": 100},
            {"date": "2026-01-03", "event_type": "SELL", "amount": 600, "ticker": "AAA", "quantity": 5, "price": 120},
            {"date": "2026-01-03", "event_type": "DIVIDEND", "amount": 10, "ticker": "AAA"},
        ],
        base_currency="IDR",
    )
    assert result["ending_cash"] == pytest.approx(610)
    assert result["ending_market_value"] == pytest.approx(600)
    assert result["ending_portfolio_value"] == pytest.approx(1210)
    assert result["ending_positions"]["AAA"] == pytest.approx(5)
    assert result["curve"]["daily_twr_return"].iloc[1] == pytest.approx(0.10)
    assert result["total_twr_pct"] == pytest.approx(21.0)


def test_transaction_replay_removes_external_deposits_from_twr():
    dates = pd.to_datetime(["2026-01-01", "2026-01-02"])
    result = run_transaction_aware_portfolio(
        {"AAA": pd.Series([100.0, 100.0], index=dates)},
        {"AAA": "IDR"},
        [
            {"date": "2026-01-01", "event_type": "DEPOSIT", "amount": 1000},
            {"date": "2026-01-01", "event_type": "BUY", "amount": 1000, "ticker": "AAA", "quantity": 10, "price": 100},
            {"date": "2026-01-02", "event_type": "DEPOSIT", "amount": 1000},
        ],
    )
    assert result["ending_portfolio_value"] == pytest.approx(2000)
    assert result["total_twr_pct"] == pytest.approx(0.0)


def test_transaction_replay_converts_usd_asset_and_cash_flows_to_idr():
    dates = pd.to_datetime(["2026-01-01", "2026-01-02"])
    result = run_transaction_aware_portfolio(
        {"US": pd.Series([1.0, 1.0], index=dates)},
        {"US": "USD"},
        [
            {"date": "2026-01-01", "event_type": "DEPOSIT", "amount": 15000},
            {"date": "2026-01-01", "event_type": "BUY", "amount": 15000, "ticker": "US", "quantity": 1, "price": 1, "amount_currency": float("nan")},
        ],
        base_currency="IDR",
        usd_idr_close=pd.Series([15000.0, 16500.0], index=dates),
    )
    assert result["ending_portfolio_value"] == pytest.approx(16500)
    assert result["total_twr_pct"] == pytest.approx(10.0)


def test_transaction_replay_rejects_stale_fx_and_short_sale():
    dates = pd.to_datetime(["2026-01-01", "2026-01-10"])
    prices = {"US": pd.Series([1.0, 1.0], index=dates)}
    fx = pd.Series([15000.0], index=dates[:1])
    events = [
        {"date": "2026-01-01", "event_type": "DEPOSIT", "amount": 15000},
        {"date": "2026-01-01", "event_type": "BUY", "amount": 1, "ticker": "US", "quantity": 1, "price": 1},
    ]
    with pytest.raises(ValueError, match="stale"):
        run_transaction_aware_portfolio(prices, {"US": "USD"}, events,
                                        usd_idr_close=fx, max_fx_gap_days=3)
    with pytest.raises(ValueError, match="melebihi"):
        run_transaction_aware_portfolio(
            {"AAA": pd.Series([100.0, 100.0], index=dates)},
            {"AAA": "IDR"},
            [{"date": "2026-01-01", "event_type": "SELL", "amount": 100, "ticker": "AAA", "quantity": 1, "price": 100}],
        )


def test_transaction_replay_rejects_insufficient_cash_and_future_lookahead():
    dates = pd.to_datetime(["2026-01-01", "2026-01-02"])
    prices = {"AAA": pd.Series([100.0, 100.0], index=dates)}
    with pytest.raises(ValueError, match="Cash tersedia tidak cukup"):
        run_transaction_aware_portfolio(
            prices, {"AAA": "IDR"},
            [{"date": "2026-01-01", "event_type": "BUY", "amount": 100, "ticker": "AAA", "quantity": 1, "price": 100}],
        )
    with pytest.raises(ValueError, match="look-ahead dilarang"):
        run_transaction_aware_portfolio(
            {"AAA": pd.Series([100.0], index=pd.to_datetime(["2026-01-02"]))},
            {"AAA": "IDR"},
            [{"date": "2026-01-01", "event_type": "DEPOSIT", "amount": 0}],
            initial_positions={"AAA": 1},
        )



def test_transaction_replay_separates_trade_date_positions_from_settlement_cash():
    dates = pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04"])
    result = run_transaction_aware_portfolio(
        {"AAA": pd.Series([100.0, 110.0, 120.0, 130.0], index=dates)},
        {"AAA": "IDR"},
        [
            {"date": "2026-01-01", "event_type": "DEPOSIT", "amount": 1000},
            {"date": "2026-01-01", "event_type": "BUY", "amount": 1000, "ticker": "AAA", "quantity": 10, "price": 100, "settlement_date": "2026-01-03"},
            {"date": "2026-01-03", "event_type": "SELL", "amount": 600, "ticker": "AAA", "quantity": 5, "price": 120, "settlement_date": "2026-01-04"},
        ],
    )
    assert result["curve"].loc[pd.Timestamp("2026-01-02"), "cash_balance"] == pytest.approx(1000)
    assert result["curve"].loc[pd.Timestamp("2026-01-02"), "available_cash"] == pytest.approx(0)
    assert result["curve"].loc[pd.Timestamp("2026-01-02"), "unsettled_payables"] == pytest.approx(1000)
    assert result["curve"].loc[pd.Timestamp("2026-01-03"), "unsettled_payables"] == pytest.approx(0)
    assert result["curve"].loc[pd.Timestamp("2026-01-03"), "unsettled_receivables"] == pytest.approx(600)
    assert result["ending_cash"] == pytest.approx(600)
    assert result["ending_available_cash"] == pytest.approx(600)
    assert result["ending_unsettled_receivables"] == pytest.approx(0)
    assert result["pending_settlements"].empty
    assert result["ending_portfolio_value"] == pytest.approx(1250)


def test_transaction_replay_reserves_cash_for_unsettled_buy_payables():
    dates = pd.to_datetime(["2026-01-01", "2026-01-02"])
    with pytest.raises(ValueError, match="Cash tersedia tidak cukup"):
        run_transaction_aware_portfolio(
            {"AAA": pd.Series([100.0, 100.0], index=dates)},
            {"AAA": "IDR"},
            [
                {"date": "2026-01-01", "event_type": "DEPOSIT", "amount": 1000},
                {"date": "2026-01-01", "event_type": "BUY", "amount": 800, "ticker": "AAA", "quantity": 8, "price": 100, "settlement_date": "2026-01-02"},
                {"date": "2026-01-02", "event_type": "BUY", "amount": 300, "ticker": "AAA", "quantity": 3, "price": 100},
            ],
        )


def test_transaction_replay_rejects_settlement_before_trade_date():
    dates = pd.to_datetime(["2026-01-01", "2026-01-02"])
    with pytest.raises(ValueError, match="tidak boleh lebih awal"):
        run_transaction_aware_portfolio(
            {"AAA": pd.Series([100.0, 100.0], index=dates)},
            {"AAA": "IDR"},
            [{"date": "2026-01-02", "event_type": "BUY", "amount": 100, "ticker": "AAA", "quantity": 1, "price": 100, "settlement_date": "2026-01-01"}],
            initial_cash=100,
        )



def test_transaction_replay_keeps_settlement_pending_after_market_data_ends():
    dates = pd.to_datetime(["2026-01-01", "2026-01-02"])
    result = run_transaction_aware_portfolio(
        {"AAA": pd.Series([100.0, 100.0], index=dates)},
        {"AAA": "IDR"},
        [
            {"date": "2026-01-01", "event_type": "DEPOSIT", "amount": 1000},
            {"date": "2026-01-01", "event_type": "BUY", "amount": 1000, "ticker": "AAA", "quantity": 10, "price": 100, "settlement_date": "2026-01-03"},
        ],
    )
    assert result["ending_unsettled_payables"] == pytest.approx(1000)
    assert result["ending_available_cash"] == pytest.approx(0)
    assert len(result["pending_settlements"]) == 1



def test_transaction_replay_rejects_implicit_foreign_currency_cash_conversion():
    dates = pd.to_datetime(["2026-01-01", "2026-01-02"])
    with pytest.raises(ValueError, match="konversi kas lintas mata uang tidak dilakukan otomatis"):
        run_transaction_aware_portfolio(
            {"US": pd.Series([1.0, 1.0], index=dates)},
            {"US": "USD"},
            [
                {"date": "2026-01-01", "event_type": "DEPOSIT", "amount": 15000},
                {"date": "2026-01-01", "event_type": "BUY", "amount": 1, "ticker": "US", "quantity": 1, "price": 1, "amount_currency": "USD"},
            ],
            base_currency="IDR",
            usd_idr_close=pd.Series([15000.0, 15000.0], index=dates),
        )


@pytest.mark.parametrize("index", [
    pd.Index(["2026-01-01", "not-a-date"]),
    pd.to_datetime(["2026-01-01", "2026-01-01"]),
])
def test_transaction_replay_rejects_invalid_or_duplicate_market_data_dates(index):
    with pytest.raises(ValueError, match="Index tanggal close AAA"):
        run_transaction_aware_portfolio(
            {"AAA": pd.Series([100.0, 101.0], index=index)},
            {"AAA": "IDR"},
            [{"date": "2026-01-01", "event_type": "DEPOSIT", "amount": 1000}],
        )


@pytest.mark.parametrize("gap", [-1, 1.5, float("inf"), "invalid"])
def test_transaction_replay_rejects_invalid_price_gap_configuration(gap):
    dates = pd.to_datetime(["2026-01-01", "2026-01-02"])
    with pytest.raises(ValueError, match="max_price_gap_days"):
        run_transaction_aware_portfolio(
            {"AAA": pd.Series([100.0, 101.0], index=dates)},
            {"AAA": "IDR"},
            [],
            max_price_gap_days=gap,
        )


@pytest.mark.parametrize("kwargs", [
    {"initial_cash": True},
    {"initial_positions": {"AAA": True}},
    {"max_price_gap_days": True},
    {"max_fx_gap_days": False},
])
def test_transaction_replay_rejects_boolean_numeric_inputs(kwargs):
    dates = pd.to_datetime(["2026-01-01", "2026-01-02"])
    with pytest.raises(ValueError, match="boolean|bilangan bulat"):
        run_transaction_aware_portfolio(
            {"AAA": pd.Series([100.0, 101.0], index=dates)},
            {"AAA": "IDR"},
            [],
            **kwargs,
        )



def test_transaction_replay_normalizes_ticker_keys_consistently():
    dates = pd.to_datetime(["2026-01-01", "2026-01-02"])
    result = run_transaction_aware_portfolio(
        {"aaa": pd.Series([100.0, 110.0], index=dates)},
        {"AAA": "IDR"},
        [{"date": "2026-01-01", "event_type": "DEPOSIT", "amount": 1000}],
        initial_positions={"aaa": 2},
    )
    assert result["ending_positions"] == {"AAA": pytest.approx(2)}
    assert result["ending_market_value"] == pytest.approx(220)


@pytest.mark.parametrize("price_closes, currencies", [
    ({"aaa": pd.Series([100.0, 101.0], index=pd.to_datetime(["2026-01-01", "2026-01-02"])),
      "AAA": pd.Series([100.0, 101.0], index=pd.to_datetime(["2026-01-01", "2026-01-02"]))},
     {"AAA": "IDR"}),
    ({"AAA": pd.Series([100.0, 101.0], index=pd.to_datetime(["2026-01-01", "2026-01-02"]))},
     {"aaa": "IDR", "AAA": "USD"}),
])
def test_transaction_replay_rejects_ticker_collisions_after_normalization(price_closes, currencies):
    with pytest.raises(ValueError, match="duplikat setelah normalisasi"):
        run_transaction_aware_portfolio(price_closes, currencies, [])
