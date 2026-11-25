import pytest

from corporate_event_store import create_event, create_events, delete_event, list_events


def event():
    return {
        "ticker": "BBCA", "event_type": "EX_DIVIDEND",
        "event_date": "2026-12-01", "status": "CONFIRMED",
        "source": "Issuer", "retrieved_at": "2026-11-25T00:00:00+00:00",
    }


def test_corporate_events_are_persisted_and_owner_scoped(tmp_path):
    db = str(tmp_path / "events.sqlite")
    event_id = create_event("issuer|user1", event(), path=db)
    assert len(list_events("issuer|user1", path=db)) == 1
    assert list_events("issuer|user2", path=db) == []
    assert delete_event("issuer|user2", event_id, path=db) is False
    assert len(list_events("issuer|user1", path=db)) == 1
    assert delete_event("issuer|user1", event_id, path=db) is True
    assert list_events("issuer|user1", path=db) == []


def test_corporate_events_require_owner_and_provenance(tmp_path):
    db = str(tmp_path / "events.sqlite")
    with pytest.raises(ValueError, match="Owner dan daftar event"):
        create_event("", event(), path=db)
    with pytest.raises(ValueError, match="wajib"):
        create_event("owner", {"ticker": "BBCA"}, path=db)


def test_corporate_event_bulk_import_is_atomic_on_validation_error(tmp_path):
    db = str(tmp_path / "events.sqlite")
    valid = event()
    invalid = {**event(), "source": ""}
    with pytest.raises(ValueError, match="wajib"):
        create_events("owner", [valid, invalid], path=db)
    assert list_events("owner", path=db) == []


def test_corporate_event_bulk_import_persists_all_rows(tmp_path):
    db = str(tmp_path / "events.sqlite")
    ids = create_events("owner", [event(), {**event(), "ticker": "BBRI"}], path=db)
    assert len(ids) == 2
    assert len(list_events("owner", path=db)) == 2
