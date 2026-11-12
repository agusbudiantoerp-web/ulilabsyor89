
import sys
import json
import tempfile
from pathlib import Path

import pandas as pd

# Arahkan Python ke folder modul TSFA
PROJECT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_DIR / "time-series"))

from tsfa_storage_engine import TSFAStorageEngine
from tsfa_version_manager import TSFAVersionManager


def make_dataset():
    dates = pd.bdate_range(
        start="2026-01-01",
        periods=40
    )

    close = [100 + i * 0.1 for i in range(40)]

    data = pd.DataFrame(
        {
            "Open": [x - 0.02 for x in close],
            "High": [x + 0.05 for x in close],
            "Low": [x - 0.05 for x in close],
            "Close": close,
            "Adj Close": close,
            "Volume": [100000] * 40,
        },
        index=dates,
    )

    data.index.name = "Date"
    return data


def run_test():
    with tempfile.TemporaryDirectory(
        prefix="TSFA_VERSION_TEST_"
    ) as temp_dir:

        print("\n=== TSFA VERSION MANAGER TEST ===")
        print("Temporary directory:", temp_dir)

        engine = TSFAStorageEngine(
            base_dir=temp_dir
        )
        manager = TSFAVersionManager(engine)

        ticker = "TESTTSFA"
        market = "indonesia"

        # TEST 1: Simpan dataset pertama
        data_v1 = make_dataset()

        result_v1 = engine.save_dataset(
            ticker,
            market,
            data_v1,
            provider="Synthetic Test",
        )

        print("\nTEST 1 - CREATE V0001")
        print(result_v1["status"], result_v1.get("version_id"))

        assert result_v1["status"] == "PASS"
        assert result_v1["version_id"] == "V0001"

        # TEST 2: Buat dataset kedua dengan perubahan
        data_v2 = data_v1.copy()

        changed_date = data_v2.index[20]
        new_close = data_v2.loc[changed_date, "Close"] + 0.05

        data_v2.loc[changed_date, "Open"] = new_close - 0.02
        data_v2.loc[changed_date, "High"] = new_close + 0.05
        data_v2.loc[changed_date, "Low"] = new_close - 0.05
        data_v2.loc[changed_date, "Close"] = new_close
        data_v2.loc[changed_date, "Adj Close"] = new_close

        new_date = data_v2.index[-1] + pd.offsets.BDay(1)
        next_close = data_v2.iloc[-1]["Close"] + 0.1

        data_v2.loc[new_date] = {
            "Open": next_close - 0.02,
            "High": next_close + 0.05,
            "Low": next_close - 0.05,
            "Close": next_close,
            "Adj Close": next_close,
            "Volume": 100000,
        }

        data_v2 = data_v2.sort_index()

        result_v2 = engine.save_dataset(
            ticker,
            market,
            data_v2,
            provider="Synthetic Test",
        )

        print("\nTEST 2 - CREATE V0002")
        print(result_v2["status"], result_v2.get("version_id"))

        assert result_v2["status"] == "PASS"
        assert result_v2["version_id"] == "V0002"

        # TEST 3: Periksa active pointer V0002
        active_v2 = manager.get_active_version(
            ticker,
            market
        )

        print("\nTEST 3 - ACTIVE POINTER")
        print(active_v2["active_version"])

        assert active_v2["active_version"] == "V0002"

        # TEST 4: Bandingkan V0001 dengan V0002
        comparison = manager.compare_versions(
            ticker,
            market,
            "V0001",
            "V0002",
        )

        print("\nTEST 4 - COMPARE")
        print("Rows V1:", comparison["rows_a"])
        print("Rows V2:", comparison["rows_b"])
        print("Added dates:", len(comparison["added_dates"]))
        print("Changed columns:", list(comparison["changed_values"]))

        assert comparison["rows_b"] == comparison["rows_a"] + 1
        assert len(comparison["added_dates"]) == 1
        assert "Close" in comparison["changed_values"]

        # TEST 5: Rollback ke V0001
        rollback = manager.rollback(
            ticker,
            market,
            "V0001",
        )

        print("\nTEST 5 - ROLLBACK")
        print(rollback)

        assert rollback["status"] == "ROLLBACK_SUCCESS"
        assert rollback["active_version"] == "V0001"

        # TEST 6: Verifikasi Clean dan SHA-256
        active_after = manager.get_active_version(
            ticker,
            market
        )

        active_clean = Path(
            engine.clean_dir
        ) / market / f"{ticker}.csv"

        metadata_path = (
            engine.version_dir
            / market
            / ticker
            / "V0001.json"
        )

        metadata = json.loads(
            metadata_path.read_text(encoding="utf-8")
        )

        active_hash = engine._hash_file(active_clean)

        print("\nTEST 6 - SHA256 INTEGRITY")
        print("Active version:", active_after["active_version"])
        print("Hash matches:", active_hash == metadata["clean_hash"])

        assert active_after["active_version"] == "V0001"
        assert active_hash == metadata["clean_hash"]

        # TEST 7: Audit Trail
        audit_events = [
            json.loads(line)
            for line in engine.audit_file.read_text(
                encoding="utf-8"
            ).splitlines()
            if line.strip()
        ]

        event_names = [
            event.get("event")
            for event in audit_events
        ]

        print("\nTEST 7 - AUDIT TRAIL")
        print("Events:", event_names)

        assert "DATASET_SAVED" in event_names
        assert "ROLLBACK" in event_names
        assert "ACTIVE_VERSION_CHANGED" in event_names

        print("\n================================")
        print("ALL TESTS PASSED")
        print("DATAHUB ORIGINAL: NOT MODIFIED")
        print("================================")


if __name__ == "__main__":
    run_test()
