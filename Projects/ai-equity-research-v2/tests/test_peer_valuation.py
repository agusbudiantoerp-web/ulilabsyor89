import pytest

from peer_valuation import build_peer_comparison, compare_company_to_peers


def peers():
    return [
        {"ticker": "AAA", "industry": "Banks", "currency": "IDR", "pe_ttm": 10, "pb": 1.2, "roe": 0.12},
        {"ticker": "BBB", "industry": "Banks", "currency": "IDR", "pe_ttm": 20, "pb": 1.8, "roe": 0.15},
        {"ticker": "CCC", "industry": "Banks", "currency": "IDR", "pe_ttm": -5, "pb": 0, "roe": None},
        {"ticker": "USD1", "industry": "Banks", "currency": "USD", "pe_ttm": 8, "pb": 1, "roe": 0.1},
        {"ticker": "TECH", "industry": "Technology", "currency": "IDR", "pe_ttm": 30, "pb": 4, "roe": 0.2},
    ]


def test_peer_comparison_filters_industry_and_currency():
    result = build_peer_comparison(peers(), industry="Banks", currency="IDR")
    assert result["peer_count"] == 3
    assert result["tickers"] == ["AAA", "BBB", "CCC"]
    assert result["metrics"]["pe_ttm"]["median"] == 15
    assert result["metrics"]["pe_ttm"]["coverage_pct"] == pytest.approx(200 / 3)


def test_peer_comparison_excludes_negative_and_zero_valuation_denominators():
    result = build_peer_comparison(peers(), industry="Banks", currency="IDR")
    assert result["metrics"]["pe_ttm"]["coverage"] == 2
    assert result["metrics"]["pb"]["coverage"] == 2


def test_company_peer_premium_discount_is_explicit():
    result = build_peer_comparison(peers(), industry="Banks", currency="IDR")
    compared = compare_company_to_peers(result, "AAA")
    assert compared["metrics"]["pe_ttm"]["peer_median"] == 15
    assert compared["metrics"]["pe_ttm"]["premium_discount_pct"] == pytest.approx(-100 / 3)


def test_peer_comparison_rejects_missing_or_unmatched_peer_group():
    with pytest.raises(ValueError, match="ticker, industry"):
        build_peer_comparison([{"ticker": "A"}], industry="Banks", currency="IDR")
    with pytest.raises(ValueError, match="Tidak ada peer"):
        build_peer_comparison(peers(), industry="Insurance", currency="IDR")


def test_company_lookup_requires_member_of_peer_group():
    result = build_peer_comparison(peers(), industry="Banks", currency="IDR")
    with pytest.raises(KeyError):
        compare_company_to_peers(result, "NOPE")
