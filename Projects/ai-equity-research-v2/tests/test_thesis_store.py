import pytest

from thesis_store import create_thesis, delete_thesis, get_thesis, list_theses, update_thesis


def content():
    return {
        "bull_case": "Revenue growth accelerates",
        "base_case": "Margins normalize",
        "bear_case": "Commodity price shock",
        "catalysts": ["New capacity"],
        "risks": ["Debt refinancing"],
        "invalidation": "FCF remains negative for 3 years",
        "target_price": 1500,
        "currency": "IDR",
    }


def test_thesis_create_update_and_version_history(tmp_path):
    db = str(tmp_path / "thesis.sqlite")
    thesis_id = create_thesis("issuer|user1", "TPIA", "IDX", "TPIA investment thesis",
                              content(), review_date="2027-01-31", path=db)
    assert len(list_theses("issuer|user1", path=db)) == 1
    version = update_thesis("issuer|user1", thesis_id, title="Updated TPIA thesis",
                            content={**content(), "target_price": 1800},
                            status="ACTIVE", review_date="2027-02-28", path=db)
    assert version == 2
    saved = get_thesis("issuer|user1", thesis_id, path=db)
    assert saved["content"]["target_price"] == 1800
    assert [item["version"] for item in saved["versions"]] == [1, 2]


def test_thesis_data_is_owner_scoped(tmp_path):
    db = str(tmp_path / "thesis.sqlite")
    thesis_id = create_thesis("issuer|user1", "BBCA", "IDX", "BBCA thesis", content(), path=db)
    assert list_theses("issuer|user2", path=db) == []
    with pytest.raises(KeyError):
        get_thesis("issuer|user2", thesis_id, path=db)
    assert delete_thesis("issuer|user2", thesis_id, path=db) is False
    assert len(list_theses("issuer|user1", path=db)) == 1


def test_thesis_requires_valid_identity_and_market(tmp_path):
    with pytest.raises(ValueError, match="Owner identity"):
        create_thesis("", "BBCA", "IDX", "Title", content(), path=str(tmp_path / "x.db"))
    with pytest.raises(ValueError, match="IDX/US"):
        create_thesis("owner", "BBCA", "SG", "Title", content(), path=str(tmp_path / "x.db"))


def test_thesis_rejects_unknown_status_and_invalid_review_date(tmp_path):
    with pytest.raises(ValueError, match="Status"):
        create_thesis("owner", "BBCA", "IDX", "Title", content(), status="UNKNOWN", path=str(tmp_path / "x.db"))
    with pytest.raises(ValueError, match="ISO"):
        create_thesis("owner", "BBCA", "IDX", "Title", content(), review_date="next week", path=str(tmp_path / "x.db"))


def test_thesis_delete_is_owner_scoped_and_removes_versions(tmp_path):
    db = str(tmp_path / "thesis.sqlite")
    thesis_id = create_thesis("owner", "NVDA", "US", "NVDA thesis", content(), path=db)
    assert delete_thesis("owner", thesis_id, path=db)
    assert list_theses("owner", path=db) == []
    with pytest.raises(KeyError):
        get_thesis("owner", thesis_id, path=db)
