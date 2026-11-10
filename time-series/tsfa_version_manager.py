
import json
from pathlib import Path

import pandas as pd


class TSFAVersionManager:

    def __init__(self, engine):
        self.engine = engine

    def _metadata_path(self, ticker, market, version_id):
        ticker = self.engine._safe_ticker(ticker)
        market = self.engine._market(market)

        if not version_id.startswith("V") or not version_id[1:].isdigit():
            raise ValueError("Format version tidak valid.")

        return (
            self.engine.version_dir
            / market
            / ticker
            / f"{version_id}.json"
        )

    def _read_metadata(self, ticker, market, version_id):
        path = self._metadata_path(ticker, market, version_id)

        if not path.exists():
            raise FileNotFoundError(
                f"Metadata {version_id} tidak ditemukan."
            )

        metadata = json.loads(
            path.read_text(encoding="utf-8")
        )

        if not metadata.get("validated"):
            raise ValueError("Versi belum lolos validasi.")

        return metadata

    def _read_clean(self, metadata):
        path = Path(metadata["clean_path"])

        if not path.exists():
            raise FileNotFoundError(
                "Arsip Clean tidak ditemukan."
            )

        actual_hash = self.engine._hash_file(path)

        if actual_hash != metadata["clean_hash"]:
            raise ValueError("SHA-256 arsip tidak cocok.")

        return pd.read_csv(
            path,
            index_col="Date",
            parse_dates=True,
        )

    def _active_clean_path(self, ticker, market):
        ticker = self.engine._safe_ticker(ticker)
        market = self.engine._market(market)

        return (
            self.engine.clean_dir
            / market
            / f"{ticker}.csv"
        )

    def compare_versions(
        self,
        ticker,
        market,
        version_a,
        version_b,
    ):
        meta_a = self._read_metadata(
            ticker, market, version_a
        )

        meta_b = self._read_metadata(
            ticker, market, version_b
        )

        data_a = self._read_clean(meta_a)
        data_b = self._read_clean(meta_b)

        dates_a = set(data_a.index)
        dates_b = set(data_b.index)

        added_dates = sorted(dates_b - dates_a)
        removed_dates = sorted(dates_a - dates_b)
        common_dates = sorted(dates_a & dates_b)

        changed_values = {}

        columns = sorted(
            set(data_a.columns) & set(data_b.columns)
        )

        for column in columns:
            a = data_a.loc[common_dates, column]
            b = data_b.loc[common_dates, column]

            equal = a.eq(b) | (a.isna() & b.isna())
            changed = []

            for date in a.index[~equal]:
                old = a.loc[date]
                new = b.loc[date]

                changed.append({
                    "date": str(date),
                    "old_value": None if pd.isna(old) else old,
                    "new_value": None if pd.isna(new) else new,
                })

            if changed:
                changed_values[column] = changed

        return {
            "ticker": ticker,
            "market": market,
            "version_a": version_a,
            "version_b": version_b,
            "rows_a": len(data_a),
            "rows_b": len(data_b),
            "added_dates": [str(x) for x in added_dates],
            "removed_dates": [str(x) for x in removed_dates],
            "changed_values": changed_values,
            "hash_a": meta_a["clean_hash"],
            "hash_b": meta_b["clean_hash"],
        }

    def set_active_version(
        self,
        ticker,
        market,
        version_id,
    ):
        metadata = self._read_metadata(
            ticker, market, version_id
        )

        # Pastikan arsip versi tervalidasi dan hash cocok.
        self._read_clean(metadata)

        ticker = self.engine._safe_ticker(ticker)
        market = self.engine._market(market)

        # Pointer harus menunjuk ke Clean aktif,
        # bukan ke file arsip historis.
        active_clean = self._active_clean_path(
            ticker, market
        )

        if not active_clean.exists():
            raise FileNotFoundError(
                "File Clean aktif tidak ditemukan."
            )

        active_hash = self.engine._hash_file(
            active_clean
        )

        if active_hash != metadata["clean_hash"]:
            raise ValueError(
                "Hash Clean aktif tidak sesuai dengan versi yang dipilih. "
                "Lakukan rollback sebelum mengubah active pointer."
            )

        active_dir = self.engine.active_dir / market
        active_dir.mkdir(parents=True, exist_ok=True)

        active_file = active_dir / f"{ticker}.json"

        record = {
            "ticker": ticker,
            "market": market,
            "active_version": version_id,
            "clean_path": str(active_clean),
            "clean_hash": metadata["clean_hash"],
        }

        temp_file = active_file.with_suffix(".tmp")

        temp_file.write_text(
            json.dumps(
                record,
                indent=4,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        temp_file.replace(active_file)

        self.engine._audit({
            "ticker": ticker,
            "market": market,
            "event": "ACTIVE_VERSION_CHANGED",
            "version_id": version_id,
            "clean_hash": metadata["clean_hash"],
        })

        return record

    def get_active_version(self, ticker, market):
        ticker = self.engine._safe_ticker(ticker)
        market = self.engine._market(market)

        active_file = (
            self.engine.active_dir
            / market
            / f"{ticker}.json"
        )

        if not active_file.exists():
            return None

        record = json.loads(
            active_file.read_text(encoding="utf-8")
        )

        metadata = self._read_metadata(
            ticker,
            market,
            record["active_version"],
        )

        # Periksa integritas arsip.
        self._read_clean(metadata)

        expected_clean = self._active_clean_path(
            ticker, market
        )

        recorded_clean = Path(record["clean_path"])

        if recorded_clean.resolve() != expected_clean.resolve():
            raise ValueError(
                "Lokasi Clean pada active pointer tidak sesuai."
            )

        if not expected_clean.exists():
            raise FileNotFoundError(
                "File Clean aktif tidak ditemukan."
            )

        active_hash = self.engine._hash_file(
            expected_clean
        )

        if active_hash != metadata["clean_hash"]:
            raise ValueError(
                "Hash Clean aktif tidak cocok dengan versi aktif."
            )

        if active_hash != record["clean_hash"]:
            raise ValueError(
                "Hash Clean aktif tidak cocok dengan active pointer."
            )

        return record

    def rollback(
        self,
        ticker,
        market,
        version_id,
    ):
        result = self.engine.rollback_version(
            ticker,
            market,
            version_id,
        )

        active = self.set_active_version(
            ticker,
            market,
            version_id,
        )

        return {
            "status": "ROLLBACK_SUCCESS",
            "version_id": version_id,
            "active_version": active["active_version"],
            "active_clean": result["active_clean"],
        }
