
from __future__ import annotations

import hashlib
import json
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd


class TSFAStorageEngine:
    """
    TSFA Core Storage Engine.

    Architecture:
    - Raw: original downloaded data
    - Clean: active validated dataset
    - Versions: immutable version archive
    - Metadata: JSON
    - Audit: JSONL
    """

    def __init__(self, base_dir="datahub"):
        self.base = Path(base_dir)

        self.raw_dir = self.base / "raw"
        self.clean_dir = self.base / "clean"
        self.version_dir = self.base / "versions"
        self.audit_dir = self.base / "audit"
        self.report_dir = self.base / "reports"
        self.active_dir = self.base / "active"

        for directory in (
            self.raw_dir,
            self.clean_dir,
            self.version_dir,
            self.audit_dir,
            self.report_dir,
            self.active_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)

        self.audit_file = self.audit_dir / "audit_log.jsonl"

    
    @staticmethod
    def _safe_ticker(ticker):
        ticker = str(ticker).strip().upper()

        if not ticker or not re.fullmatch(
            r"[A-Z0-9.^_-]+", ticker
        ):
            raise ValueError("Ticker tidak valid.")

        return ticker.replace("/", "_")

    @staticmethod
    def _market(market):
        value = str(market).strip().lower()

        aliases = {
            "indonesia": "indonesia",
            "indonesia (bei)": "indonesia",
            "bei": "indonesia",
            "us": "us",
            "usa": "us",
            "amerika": "us",
            "amerika serikat": "us",
            "amerika serikat (nyse/nasdaq)": "us",
            "united states": "us",
            "united states (nyse/nasdaq)": "us",
        }

        if value not in aliases:
            raise ValueError(
                f"Market tidak dikenal: {market}"
            )

        return aliases[value]

        value = str(market).strip().lower()

        aliases = {
            "indonesia": "indonesia",
            "indonesia (bei)": "indonesia",
            "bei": "indonesia",
            "us": "us",
            "usa": "us",
            "amerika": "us",
            "amerika serikat": "us",
            "amerika serikat (nyse/nasdaq)": "us",
            "united states": "us",
            "united states (nyse/nasdaq)": "us",
        }

        if value not in aliases:
            raise ValueError(
                f"Market tidak dikenal: {market}"
            )

    @staticmethod
    def _hash_file(path):
        digest = hashlib.sha256()

        with open(path, "rb") as file:
            for chunk in iter(
                lambda: file.read(1024 * 1024), b""
            ):
                digest.update(chunk)

        return digest.hexdigest()

    @staticmethod
    def _atomic_csv(data, destination):
        destination = Path(destination)
        destination.parent.mkdir(
            parents=True, exist_ok=True
        )

        temp_path = None

        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                suffix=".tmp",
                prefix="tsfa_",
                dir=destination.parent,
                delete=False,
                encoding="utf-8",
                newline="",
            ) as temp:
                temp_path = Path(temp.name)
                data.to_csv(
                    temp,
                    index=True,
                    index_label="Date",
                )

            temp_path.replace(destination)

        finally:
            if (
                temp_path is not None
                and temp_path.exists()
            ):
                temp_path.unlink()

    def _audit(self, record):
        event = {
            "timestamp_utc": datetime.now(
                timezone.utc
            ).isoformat(),
            **record,
        }

        self.audit_file.parent.mkdir(
            parents=True, exist_ok=True
        )

        with open(
            self.audit_file,
            "a",
            encoding="utf-8",
        ) as file:
            file.write(
                json.dumps(
                    event,
                    ensure_ascii=False,
                    default=str,
                )
                + "\n"
            )

    def validate_market_data(self, data):
        errors = []
        warnings = []
        outliers = []

        if not isinstance(data, pd.DataFrame):
            return {
                "status": "REJECT",
                "valid": False,
                "errors": ["Input harus berupa DataFrame."],
                "warnings": [],
                "outliers": [],
                "data": None,
            }

        df = data.copy()

        if df.empty:
            errors.append("Dataset kosong.")

        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        df.columns = [
            str(column).strip()
            for column in df.columns
        ]

        if "Date" in df.columns:
            df = df.set_index("Date")

        if df.index.name is None:
            df.index.name = "Date"

        try:
            dates = pd.to_datetime(
                df.index, errors="coerce", utc=True
            )

            if dates.isna().any():
                errors.append(
                    "Terdapat tanggal yang tidak valid."
                )
            else:
                df.index = dates.tz_convert(None)
                df.index.name = "Date"

        except Exception as exc:
            errors.append(
                f"Gagal memproses tanggal: {exc}"
            )

        required = ["Adj Close"]

        missing_columns = [
            column
            for column in required
            if column not in df.columns
        ]

        if missing_columns:
            errors.append(
                "Kolom wajib tidak ditemukan: "
                + ", ".join(missing_columns)
            )

        numeric_columns = [
            column
            for column in (
                "Open",
                "High",
                "Low",
                "Close",
                "Adj Close",
                "Volume",
            )
            if column in df.columns
        ]

        for column in numeric_columns:
            df[column] = pd.to_numeric(
                df[column], errors="coerce"
            )

        df = df.replace(
            [np.inf, -np.inf], np.nan
        )

        if df.index.has_duplicates:
            errors.append(
                "Terdapat tanggal duplikat."
            )

        df = df.sort_index()

        if "Adj Close" in df.columns:
            if df["Adj Close"].isna().any():
                errors.append(
                    "Adj Close memiliki nilai kosong."
                )

            if (df["Adj Close"].dropna() <= 0).any():
                errors.append(
                    "Adj Close memiliki harga nol atau negatif."
                )

        if "Volume" in df.columns:
            if df["Volume"].isna().any():
                warnings.append(
                    "Volume memiliki nilai kosong."
                )

        # Outlier detection: flag only, never delete.
        if (
            "Adj Close" in df.columns
            and len(df) >= 10
        ):
            returns = df["Adj Close"].pct_change()
            clean_returns = returns.dropna()

            if len(clean_returns) >= 9:
                median = clean_returns.median()
                mad = (
                    clean_returns - median
                ).abs().median()

                if mad > 0:
                    robust_score = (
                        0.6745
                        * (clean_returns - median).abs()
                        / mad
                    )

                    candidates = robust_score[
                        robust_score > 6
                    ]

                    outliers = [
                        {
                            "date": str(date),
                            "return": float(
                                clean_returns.loc[date]
                            ),
                            "robust_score": float(
                                robust_score.loc[date]
                            ),
                        }
                        for date in candidates.index
                    ]

                    if outliers:
                        warnings.append(
                            f"{len(outliers)} kandidat outlier "
                            "ditemukan; tidak dihapus otomatis."
                        )

        valid = len(errors) == 0

        return {
            "status": (
                "REJECTED"
                if not valid
                else "WARNING"
                if warnings
                else "VALID"
            ),
            "valid": valid,
            "errors": errors,
            "warnings": warnings,
            "outliers": outliers,
            "data": df if valid else None,
        }

    def save_dataset(
        self,
        ticker,
        market,
        data,
        provider="Yahoo Finance",
    ):
        ticker = self._safe_ticker(ticker)
        market = self._market(market)

        validation = self.validate_market_data(data)

        timestamp = datetime.now(
            timezone.utc
        ).strftime("%Y%m%dT%H%M%S%fZ")

        raw_path = (
            self.raw_dir
            / market
            / ticker
            / f"{timestamp}.csv"
        )

        raw_path.parent.mkdir(
            parents=True, exist_ok=True
        )

        # Preserve the original received dataset.
        raw_data = data.copy()

        if isinstance(raw_data.columns, pd.MultiIndex):
            raw_data.columns = (
                raw_data.columns.get_level_values(0)
            )

        raw_data.to_csv(
            raw_path,
            index=True,
            index_label="Date",
        )

        raw_hash = self._hash_file(raw_path)

        if not validation["valid"]:
            self._audit({
                "event": "DATASET_REJECTED",
                "ticker": ticker,
                "market": market,
                "provider": provider,
                "raw_path": str(raw_path),
                "raw_hash": raw_hash,
                "validation_status": "REJECTED",
                "errors": validation["errors"],
            })

            return {
                "status": "REJECT",
                "ticker": ticker,
                "market": market,
                "errors": validation["errors"],
                "raw_path": str(raw_path),
            }

        clean_data = validation["data"]

        clean_dir = (
            self.clean_dir / market
        )
        clean_dir.mkdir(
            parents=True, exist_ok=True
        )

        active_clean = clean_dir / f"{ticker}.csv"

        # Check duplicate against normalized content.
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".csv",
            delete=False,
            encoding="utf-8",
            newline="",
        ) as temp:
            candidate_path = Path(temp.name)
            clean_data.to_csv(
                temp,
                index=True,
                index_label="Date",
            )

        try:
            candidate_hash = self._hash_file(
                candidate_path
            )

            if active_clean.exists():
                current_hash = self._hash_file(
                    active_clean
                )

                if current_hash == candidate_hash:
                    self._audit({
                        "event": "DUPLICATE_DATASET",
                        "ticker": ticker,
                        "market": market,
                        "raw_hash": raw_hash,
                        "clean_hash": current_hash,
                        "validation_status": validation["status"],
                    })

                    return {
                        "status": "UNCHANGED",
                        "ticker": ticker,
                        "market": market,
                        "clean_path": str(active_clean),
                        "clean_hash": current_hash,
                    }
        finally:
            if candidate_path.exists():
                candidate_path.unlink()

        ticker_version_dir = (
            self.version_dir / market / ticker
        )

        ticker_version_dir.mkdir(
            parents=True, exist_ok=True
        )

        existing_versions = []

        for path in ticker_version_dir.glob("V*.json"):
            match = re.fullmatch(
                r"V(\d+)", path.stem
            )
            if match:
                existing_versions.append(
                    int(match.group(1))
                )

        next_number = (
            max(existing_versions, default=0) + 1
        )

        version_id = f"V{next_number:04d}"

        version_dir = (
            ticker_version_dir / version_id
        )
        version_dir.mkdir(
            parents=True, exist_ok=False
        )

        version_clean = (
            version_dir / f"{ticker}.csv"
        )

        self._atomic_csv(
            clean_data, version_clean
        )

        clean_hash = self._hash_file(
            version_clean
        )

        metadata = {
            "version_id": version_id,
            "ticker": ticker,
            "market": market,
            "provider": provider,
            "created_at_utc": datetime.now(
                timezone.utc
            ).isoformat(),
            "validated": True,
            "validation_status": validation["status"],
            "validation_errors": validation["errors"],
            "validation_warnings": validation["warnings"],
            "outliers": validation["outliers"],
            "row_count": len(clean_data),
            "date_start": str(clean_data.index.min()),
            "date_end": str(clean_data.index.max()),
            "raw_path": str(raw_path),
            "raw_hash": raw_hash,
            "clean_path": str(version_clean),
            "clean_hash": clean_hash,
        }

        metadata_path = (
            ticker_version_dir
            / f"{version_id}.json"
        )

        metadata_path.write_text(
            json.dumps(
                metadata,
                indent=4,
                ensure_ascii=False,
                default=str,
            ),
            encoding="utf-8",
        )

        # Activate Clean only after validation and archive succeed.
        self._atomic_csv(
            clean_data, active_clean
        )

        active_dir = (
            self.active_dir / market
        )
        active_dir.mkdir(
            parents=True, exist_ok=True
        )

        active_record = {
            "ticker": ticker,
            "market": market,
            "active_version": version_id,
            "clean_path": str(active_clean),
            "clean_hash": self._hash_file(active_clean),
        }

        active_file = active_dir / f"{ticker}.json"
        temp_active = active_file.with_suffix(".tmp")

        temp_active.write_text(
            json.dumps(
                active_record,
                indent=4,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        temp_active.replace(active_file)

        self._audit({
            "event": "DATASET_SAVED",
            "ticker": ticker,
            "market": market,
            "provider": provider,
            "version_id": version_id,
            "raw_hash": raw_hash,
            "clean_hash": clean_hash,
            "row_count": len(clean_data),
            "date_start": metadata["date_start"],
            "date_end": metadata["date_end"],
            "validation_status": validation["status"],
            "warnings": validation["warnings"],
        })

        return {
    	    "status": "PASS",
            "ticker": ticker,
    	    "market": market,
    	    "version_id": version_id,
    	    "raw_path": str(raw_path),
    	    "clean_path": str(active_clean),
    	    "version_path": str(metadata_path),
    	    "clean_hash": self._hash_file(active_clean),
    	    "validation": validation["status"],
	}

    def rollback_version(
        self,
        ticker,
        market,
        version_id,
    ):
        ticker = self._safe_ticker(ticker)
        market = self._market(market)

        if not re.fullmatch(r"V\d+", version_id):
            raise ValueError("Format version tidak valid.")

        metadata_path = (
            self.version_dir
            / market
            / ticker
            / f"{version_id}.json"
        )

        if not metadata_path.exists():
            raise FileNotFoundError(
                "Metadata versi tidak ditemukan."
            )

        metadata = json.loads(
            metadata_path.read_text(encoding="utf-8")
        )

        if not metadata.get("validated"):
            raise ValueError(
                "Versi tidak tervalidasi."
            )

        archived_clean = Path(
            metadata["clean_path"]
        )

        if not archived_clean.exists():
            raise FileNotFoundError(
                "Arsip Clean tidak ditemukan."
            )

        actual_hash = self._hash_file(
            archived_clean
        )

        if actual_hash != metadata["clean_hash"]:
            raise ValueError(
                "Hash arsip tidak cocok."
            )

        restored_data = pd.read_csv(
            archived_clean,
            index_col="Date",
            parse_dates=True,
        )

        validation = self.validate_market_data(
            restored_data
        )

        if not validation["valid"]:
            raise ValueError(
                "Dataset arsip gagal validasi ulang."
            )

        active_clean = (
            self.clean_dir
            / market
            / f"{ticker}.csv"
        )

        self._atomic_csv(
            validation["data"],
            active_clean,
        )

        self._audit({
            "event": "ROLLBACK",
            "ticker": ticker,
            "market": market,
            "version_id": version_id,
            "clean_hash": actual_hash,
        })

        return {
            "status": "ROLLBACK_SUCCESS",
            "version_id": version_id,
            "active_clean": str(active_clean),
        }
