import pandas as pd

from portfolio_store import delete_book, list_books, load_book, save_book


def test_portfolio_book_round_trip_and_weighted_average_cost(tmp_path):
    db_path = str(tmp_path / "portfolio.sqlite3")
    positions = pd.DataFrame([
        {"Market": "IDX", "Ticker": "BBCA", "Shares": 100, "Average Cost": 9000},
        {"Market": "IDX", "Ticker": "BBCA", "Shares": 300, "Average Cost": 10000},
        {"Market": "US", "Ticker": "NVDA", "Shares": 2, "Average Cost": 100},
    ])
    assert save_book("book-1", "Core", positions, path=db_path) == 2
    books = list_books(path=db_path)
    assert len(books) == 1 and books[0]["name"] == "Core"
    loaded = load_book("book-1", path=db_path)
    bbca = loaded[loaded["Ticker"] == "BBCA"].iloc[0]
    assert bbca["Shares"] == 400
    assert bbca["Average Cost"] == 9750
    assert delete_book("book-1", path=db_path)
    assert list_books(path=db_path) == []



def test_portfolio_store_rejects_infinite_holdings(tmp_path):
    import pytest

    db_path = str(tmp_path / "portfolio.sqlite3")
    positions = pd.DataFrame([
        {"Market": "IDX", "Ticker": "BBCA", "Shares": float("inf"), "Average Cost": 9000}
    ])
    with pytest.raises(ValueError, match="finite"):
        save_book("book-invalid", "Invalid", positions, path=db_path)
