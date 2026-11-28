import pytest

from thesis_store import (create_thesis, delete_thesis, get_thesis, list_theses, update_thesis,
                          request_review, list_reviews_for_thesis, list_reviews_for_reviewer,
                          get_review_for_reviewer, decide_review)


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


def test_thesis_review_is_assigned_to_reviewer_and_versioned(tmp_path):
    db = str(tmp_path / "reviews.sqlite")
    thesis_id = create_thesis("issuer|owner", "BBCA", "IDX", "BBCA thesis", content(), path=db)
    review_id = request_review("issuer|owner", thesis_id, "issuer|reviewer", path=db)
    assert len(list_reviews_for_thesis("issuer|owner", thesis_id, path=db)) == 1
    assert len(list_reviews_for_reviewer("issuer|reviewer", path=db)) == 1
    assert list_reviews_for_reviewer("issuer|other", path=db) == []
    review = get_review_for_reviewer("issuer|reviewer", review_id, path=db)
    assert review["content"]["bull_case"] == "Revenue growth accelerates"
    with pytest.raises(KeyError):
        get_review_for_reviewer("issuer|other", review_id, path=db)
    with pytest.raises(KeyError):
        decide_review("issuer|other", review_id, "APPROVED", "Unauthorized decision", path=db)
    assert list_reviews_for_thesis("issuer|owner", thesis_id, path=db)[0]["status"] == "PENDING"
    assert decide_review("issuer|reviewer", review_id, "CHANGES_REQUESTED", "Please refine downside case", path=db) == "CHANGES_REQUESTED"
    assert list_reviews_for_thesis("issuer|owner", thesis_id, path=db)[0]["status"] == "CHANGES_REQUESTED"
    with pytest.raises(KeyError):
        decide_review("issuer|reviewer", review_id, "APPROVED", "second decision", path=db)


def test_thesis_review_rejects_self_review_and_duplicate_pending_request(tmp_path):
    db = str(tmp_path / "reviews.sqlite")
    thesis_id = create_thesis("issuer|owner", "BBCA", "IDX", "BBCA thesis", content(), path=db)
    with pytest.raises(ValueError, match="tidak dapat menjadi reviewer"):
        request_review("issuer|owner", thesis_id, "issuer|owner", path=db)
    request_review("issuer|owner", thesis_id, "issuer|reviewer", path=db)
    with pytest.raises(ValueError, match="masih menunggu"):
        request_review("issuer|owner", thesis_id, "issuer|reviewer", path=db)


def test_thesis_owner_cannot_request_review_for_another_users_thesis(tmp_path):
    db = str(tmp_path / "reviews.sqlite")
    thesis_id = create_thesis("issuer|alice", "BBCA", "IDX", "BBCA thesis", content(), path=db)
    with pytest.raises(KeyError):
        request_review("issuer|bob", thesis_id, "issuer|reviewer", path=db)


def test_thesis_update_supersedes_pending_review_of_old_version(tmp_path):
    db = str(tmp_path / "reviews.sqlite")
    thesis_id = create_thesis("issuer|owner", "BBCA", "IDX", "BBCA thesis", content(), path=db)
    review_id = request_review("issuer|owner", thesis_id, "issuer|reviewer", path=db)
    update_thesis(
        "issuer|owner", thesis_id, title="Updated thesis",
        content={**content(), "target_price": 14000}, status="ACTIVE", path=db,
    )
    reviews = list_reviews_for_thesis("issuer|owner", thesis_id, path=db)
    assert reviews[0]["status"] == "SUPERSEDED"
    with pytest.raises(KeyError):
        decide_review("issuer|reviewer", review_id, "APPROVED", path=db)
    new_review = request_review("issuer|owner", thesis_id, "issuer|reviewer", path=db)
    assert new_review != review_id
    assert list_reviews_for_thesis("issuer|owner", thesis_id, path=db)[0]["version"] == 2

def test_thesis_update_is_rejected_for_another_owner(tmp_path):
    db = str(tmp_path / "thesis.sqlite")
    thesis_id = create_thesis(
        "issuer|alice", "BBCA", "IDX", "Alice thesis", content(), path=db,
    )
    with pytest.raises(KeyError):
        update_thesis(
            "issuer|bob", thesis_id, title="Hijacked thesis",
            content={**content(), "target_price": 1}, status="CLOSED", path=db,
        )
    saved = get_thesis("issuer|alice", thesis_id, path=db)
    assert saved["title"] == "Alice thesis"
    assert saved["content"]["target_price"] == 1500
    assert [item["version"] for item in saved["versions"]] == [1]
