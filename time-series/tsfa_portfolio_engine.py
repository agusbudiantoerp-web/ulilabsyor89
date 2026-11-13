"""
TSFA Portfolio Engine - V1.3
Standalone personal portfolio ledger and Excel validation engine.

Initial scope:
- Indonesia / IDR only (prevents accidental mixed-currency aggregation).
- Opening holdings are entered as shares and average cost per share.
- Historical transactions before the opening date are not required.
- Subsequent BUY/SELL transactions use moving weighted-average cost.
- Workbook data is processed in memory; this module does not write to DataHub.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import date, datetime
from io import BytesIO
from typing import Any

import pandas as pd
from openpyxl import load_workbook


REQUIRED_SHEETS = {
    "PORTFOLIO",
    "TRANSACTIONS",
    "CASH_FLOW",
    "PRICE_HISTORY",
    "ANALYSIS_RESULTS",
}
PORTFOLIO_COLUMNS = [
    "Record_Type", "Market", "Ticker", "Opening_Quantity_Shares",
    "Opening_Average_Cost", "Opening_Market_Price", "Opening_Cash",
    "Currency", "As_Of_Date",
]
TRANSACTION_COLUMNS = [
    "Transaction_ID", "Date", "Market", "Ticker", "Side",
    "Quantity_Shares", "Price_Per_Share", "Fees", "Tax", "Currency",
]
CASH_FLOW_COLUMNS = [
    "Flow_ID", "Date", "Flow_Type", "Amount", "Currency",
    "Ticker", "Tax",
]
PRICE_COLUMNS = [
    "Date", "Market", "Ticker", "Close", "Currency",
]


class PortfolioValidationError(ValueError):
    """Raised when the uploaded portfolio workbook is invalid."""


@dataclass
class PortfolioResult:
    positions: pd.DataFrame
    cash_balance: float
    as_of_date: date
    total_market_value: float
    total_cost_basis: float
    total_unrealized_pnl: float
    priced_positions: int
    warnings: list[str]


def _is_blank(value: Any) -> bool:
    return value is None or (isinstance(value, float) and pd.isna(value)) or (
        isinstance(value, str) and not value.strip()
    )


def _number(value: Any, field: str, row: int, *, required: bool = False,
            default: float | None = None) -> float | None:
    if _is_blank(value):
        if required:
            raise PortfolioValidationError(
                f"PORTFOLIO baris {row}: {field} wajib diisi."
            )
        return default
    try:
        result = float(value)
    except (TypeError, ValueError):
        raise PortfolioValidationError(
            f"Baris {row}: {field} harus berupa angka."
        )
    if not pd.notna(result):
        raise PortfolioValidationError(f"Baris {row}: {field} bukan angka valid.")
    return result


def _read_workbook(source: Any) -> tuple[dict[str, pd.DataFrame], dict[str, Any]]:
    """
    Read cached formula results (data_only=True) so Excel formulas such as
    BBRI quantity =160100+128500+10300 are imported as their calculated values.
    `source` may be a path, bytes, or a file-like object.
    """
    try:
        if isinstance(source, bytes):
            source = BytesIO(source)
        wb = load_workbook(source, data_only=True, read_only=True)
    except Exception as exc:
        raise PortfolioValidationError(f"File Excel tidak dapat dibuka: {exc}") from exc

    missing = REQUIRED_SHEETS.difference(wb.sheetnames)
    if missing:
        raise PortfolioValidationError(
            "Sheet wajib tidak ditemukan: " + ", ".join(sorted(missing))
        )

    frames: dict[str, pd.DataFrame] = {}
    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        rows = ws.iter_rows(values_only=True)
        try:
            headers = next(rows)
        except StopIteration:
            frames[sheet_name] = pd.DataFrame()
            continue
        headers = [str(x).strip() if x is not None else "" for x in headers]
        records = []
        for row in rows:
            if not any(not _is_blank(v) for v in row):
                continue
            records.append(dict(zip(headers, row)))
        frames[sheet_name] = pd.DataFrame(records)
    wb.close()
    return frames, {}


def _require_columns(df: pd.DataFrame, required: list[str], sheet: str) -> None:
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise PortfolioValidationError(
            f"Sheet {sheet}: kolom wajib tidak ditemukan: {', '.join(missing)}"
        )


def validate_portfolio_workbook(source: Any) -> dict[str, Any]:
    """Validate workbook and return a compact summary without persisting data."""
    frames, _ = _read_workbook(source)
    portfolio = frames["PORTFOLIO"]
    _require_columns(portfolio, PORTFOLIO_COLUMNS, "PORTFOLIO")

    holdings = []
    cash_rows = []
    for excel_row, (_, row) in enumerate(portfolio.iterrows(), start=2):
        record_type = str(row.get("Record_Type") or "").strip().upper()
        if not record_type:
            continue
        market = str(row.get("Market") or "").strip()
        currency = str(row.get("Currency") or "").strip().upper()
        ticker = str(row.get("Ticker") or "").strip().upper()

        if market != "Indonesia" or currency != "IDR":
            raise PortfolioValidationError(
                f"PORTFOLIO baris {excel_row}: V1.3 tahap awal hanya mendukung "
                "Market=Indonesia dan Currency=IDR."
            )
        if record_type == "CASH":
            if ticker != "CASH":
                raise PortfolioValidationError(
                    f"PORTFOLIO baris {excel_row}: Record_Type CASH harus memakai Ticker CASH."
                )

            cash_amount = _number(
                row.get("Opening_Cash"), "Opening_Cash", excel_row,
                required=True
            )

            if cash_amount is None or cash_amount < 0:
                raise PortfolioValidationError(
                    f"PORTFOLIO baris {excel_row}: Opening_Cash tidak boleh negatif "
                    "untuk portofolio cash-only."
                )

            cash_rows.append(cash_amount)

        elif record_type == "HOLDING":
            if not ticker or ticker == "CASH":
                raise PortfolioValidationError(
                    f"PORTFOLIO baris {excel_row}: ticker saham tidak valid."
                )
            qty = _number(row.get("Opening_Quantity_Shares"),
                          "Opening_Quantity_Shares", excel_row, required=True)
            avg = _number(row.get("Opening_Average_Cost"),
                          "Opening_Average_Cost", excel_row, required=True)
            market_price = _number(row.get("Opening_Market_Price"),
                                   "Opening_Market_Price", excel_row, default=None)
            if qty is None or qty <= 0 or not float(qty).is_integer():
                raise PortfolioValidationError(
                    f"PORTFOLIO baris {excel_row}: jumlah saham harus bilangan bulat positif."
                )
            if avg is None or avg <= 0:
                raise PortfolioValidationError(
                    f"PORTFOLIO baris {excel_row}: average cost harus lebih besar dari nol."
                )
            if market_price is not None and market_price < 0:
                raise PortfolioValidationError(
                    f"PORTFOLIO baris {excel_row}: harga pasar tidak boleh negatif."
                )
            holdings.append({
                "Ticker": ticker,
                "Quantity_Shares": int(qty),
                "Average_Cost": float(avg),
                "Opening_Market_Price": market_price,
                "Market": market,
                "Currency": currency,
            })
        else:
            raise PortfolioValidationError(
                f"PORTFOLIO baris {excel_row}: Record_Type harus CASH atau HOLDING."
            )

    if not holdings:
        raise PortfolioValidationError("Tidak ada posisi HOLDING pada sheet PORTFOLIO.")
    if len(cash_rows) > 1:
        raise PortfolioValidationError("Sheet PORTFOLIO hanya boleh memiliki satu baris CASH.")
    if len({x["Ticker"] for x in holdings}) != len(holdings):
        raise PortfolioValidationError("Ticker HOLDING duplikat. Gabungkan menjadi satu baris.")

    dates = pd.to_datetime(
        [x for x in portfolio.get("As_Of_Date", []) if not _is_blank(x)],
        errors="coerce"
    ).dropna()
    if dates.empty:
        raise PortfolioValidationError("As_Of_Date wajib diisi pada PORTFOLIO.")
    if dates.nunique() != 1:
        raise PortfolioValidationError("Semua baris PORTFOLIO harus memakai As_Of_Date yang sama.")

    total_qty = sum(x["Quantity_Shares"] for x in holdings)
    total_cost = sum(x["Quantity_Shares"] * x["Average_Cost"] for x in holdings)
    return {
        "status": "VALID",
        "holding_count": len(holdings),
        "total_quantity_shares": total_qty,
        "total_lots": total_qty / 100,
        "total_cost_basis": total_cost,
        "opening_cash": float(cash_rows[0]) if cash_rows else 0.0,
        "as_of_date": dates[0].date(),
        "tickers": [x["Ticker"] for x in holdings],
        "warnings": [
            "V1.3 tahap awal hanya mendukung saham Indonesia dalam IDR.",
        ],
    }


def calculate_portfolio(
    source: Any,
    market_prices: dict[str, dict[str, Any]] | None = None,
) -> PortfolioResult:
    """
    Calculate opening positions plus transactions/cash flows after As_Of_Date.
    BUY fees/tax increase cost basis. SELL fees/tax reduce net sale proceeds.
    """
    frames, _ = _read_workbook(source)
    summary = validate_portfolio_workbook(source)
    portfolio = frames["PORTFOLIO"]

    positions: dict[str, dict[str, Any]] = {}
    opening_cash = 0.0
    for _, row in portfolio.iterrows():
        rt = str(row.get("Record_Type") or "").strip().upper()
        if rt == "CASH":
            opening_cash = float(row.get("Opening_Cash") or 0)
        elif rt == "HOLDING":
            ticker = str(row["Ticker"]).strip().upper()
            qty = int(float(row["Opening_Quantity_Shares"]))
            avg = float(row["Opening_Average_Cost"])
            positions[ticker] = {
                "Ticker": ticker, "Quantity_Shares": qty,
                "Average_Cost": avg, "Realized_PnL": 0.0,
                "Opening_Market_Price": (
                    None if _is_blank(row.get("Opening_Market_Price"))
                    else float(row["Opening_Market_Price"])
                ),
                "Market": "Indonesia", "Currency": "IDR",
            }

    as_of = summary["as_of_date"]
    cash_balance = opening_cash
    warnings: list[str] = list(summary["warnings"])

    tx = frames.get("TRANSACTIONS", pd.DataFrame())
    if not tx.empty:
        _require_columns(tx, TRANSACTION_COLUMNS, "TRANSACTIONS")
        tx_rows = []
        for excel_row, (_, r) in enumerate(tx.iterrows(), start=2):
            if _is_blank(r.get("Ticker")) and _is_blank(r.get("Date")):
                continue
            dt = pd.to_datetime(r.get("Date"), errors="coerce")
            if pd.isna(dt):
                raise PortfolioValidationError(
                    f"TRANSACTIONS baris {excel_row}: Date wajib dan harus valid."
                )
            if dt.date() <= as_of:
                raise PortfolioValidationError(
                    f"TRANSACTIONS baris {excel_row}: transaksi harus setelah As_Of_Date "
                    f"({as_of}). Riwayat sebelum tanggal saldo awal tidak perlu dimasukkan."
                )
            if str(r.get("Market") or "").strip() != "Indonesia" or str(r.get("Currency") or "").strip().upper() != "IDR":
                raise PortfolioValidationError(
                    f"TRANSACTIONS baris {excel_row}: hanya Indonesia/IDR yang didukung."
                )
            ticker = str(r.get("Ticker") or "").strip().upper()
            side = str(r.get("Side") or "").strip().upper()
            qty = _number(r.get("Quantity_Shares"), "Quantity_Shares", excel_row, required=True)
            price = _number(r.get("Price_Per_Share"), "Price_Per_Share", excel_row, required=True)
            fees = _number(r.get("Fees"), "Fees", excel_row, default=0.0) or 0.0
            tax = _number(r.get("Tax"), "Tax", excel_row, default=0.0) or 0.0
            if not ticker or side not in {"BUY", "SELL"}:
                raise PortfolioValidationError(
                    f"TRANSACTIONS baris {excel_row}: ticker atau Side tidak valid."
                )
            if qty is None or qty <= 0 or not float(qty).is_integer() or price is None or price <= 0:
                raise PortfolioValidationError(
                    f"TRANSACTIONS baris {excel_row}: quantity harus bilangan bulat positif "
                    "dan harga harus lebih besar dari nol."
                )
            if fees < 0 or tax < 0:
                raise PortfolioValidationError(
                    f"TRANSACTIONS baris {excel_row}: Fees dan Tax tidak boleh negatif."
                )
            tx_rows.append((dt, ticker, side, int(qty), float(price), fees, tax))
        tx_rows.sort(key=lambda x: x[0])

        for dt, ticker, side, qty, price, fees, tax in tx_rows:
            if ticker not in positions:
                positions[ticker] = {
                    "Ticker": ticker,
                    "Quantity_Shares": 0,
                    "Average_Cost": 0.0,
                    "Realized_PnL": 0.0,
                    "Opening_Market_Price": None,
                    "Market": "Indonesia",
                    "Currency": "IDR",
                }

            p = positions[ticker]
            gross = qty * price

            if side == "BUY":
                total_buy_cost = gross + fees + tax

                if total_buy_cost > cash_balance + 1e-8:
                    raise PortfolioValidationError(
                        f"TRANSACTIONS: saldo kas tidak cukup untuk BUY {ticker} "
                        f"tanggal {dt.date()}. "
                        f"Saldo tersedia: Rp{cash_balance:,.2f}; "
                        f"kebutuhan: Rp{total_buy_cost:,.2f}."
                    )

                new_qty = p["Quantity_Shares"] + qty
                p["Average_Cost"] = (
                    (
                        p["Quantity_Shares"] * p["Average_Cost"]
                        + total_buy_cost
                    ) / new_qty
                )
                p["Quantity_Shares"] = new_qty
                cash_balance -= total_buy_cost

            else:
                if qty > p["Quantity_Shares"]:
                    raise PortfolioValidationError(
                        f"Transaksi SELL {ticker} tanggal {dt.date()} "
                        "melebihi jumlah saham tersedia."
                    )

                net_proceeds = gross - fees - tax
                p["Realized_PnL"] += (
                    net_proceeds - qty * p["Average_Cost"]
                )
                p["Quantity_Shares"] -= qty
                cash_balance += net_proceeds

                if p["Quantity_Shares"] == 0:
                    p["Average_Cost"] = 0.0

    flows = frames.get("CASH_FLOW", pd.DataFrame())
    if not flows.empty:
        _require_columns(flows, CASH_FLOW_COLUMNS, "CASH_FLOW")
        for excel_row, r in enumerate(flows.iterrows(), start=2):
            _, row = r
            if _is_blank(row.get("Date")) and _is_blank(row.get("Amount")):
                continue
            dt = pd.to_datetime(row.get("Date"), errors="coerce")
            if pd.isna(dt):
                raise PortfolioValidationError(f"CASH_FLOW baris {excel_row}: Date tidak valid.")
            if dt.date() <= as_of:
                raise PortfolioValidationError(
                    f"CASH_FLOW baris {excel_row}: arus kas harus setelah As_Of_Date."
                )
            if str(row.get("Currency") or "").strip().upper() != "IDR":
                raise PortfolioValidationError(f"CASH_FLOW baris {excel_row}: hanya IDR didukung.")
            flow_type = str(row.get("Flow_Type") or "").strip().upper()
            amount = _number(row.get("Amount"), "Amount", excel_row, required=True)
            tax = _number(row.get("Tax"), "Tax", excel_row, default=0.0) or 0.0
            if amount is None or amount < 0 or tax < 0:
                raise PortfolioValidationError(f"CASH_FLOW baris {excel_row}: Amount/Tax tidak valid.")
            if flow_type == "DEPOSIT":
                cash_balance += amount
            elif flow_type == "WITHDRAWAL":
                if amount > cash_balance:
                    raise PortfolioValidationError(
                        f"CASH_FLOW baris {excel_row}: saldo kas tidak cukup untuk WITHDRAWAL {amount:,.2f}; saldo tersedia {cash_balance:,.2f}."
                    )
                cash_balance -= amount
            elif flow_type in {"DIVIDEND", "INTEREST"}:
                if tax > amount:
                    raise PortfolioValidationError(
                        f"CASH_FLOW baris {excel_row}: Tax tidak boleh melebihi Amount untuk {flow_type}."
                    )
                cash_balance += amount - tax
            elif flow_type == "OTHER":
                warnings.append(
                    f"CASH_FLOW baris {excel_row}: OTHER tidak mengubah saldo kas otomatis."
                )
            else:
                raise PortfolioValidationError(
                    f"CASH_FLOW baris {excel_row}: Flow_Type tidak dikenal."
                )

    # Baseline: latest valid price from workbook PRICE_HISTORY.
    # Tuple format: (price_date, close_price).
    prices: dict[str, tuple[Any, float]] = {}
    ph = frames.get("PRICE_HISTORY", pd.DataFrame())
    if not ph.empty:
        _require_columns(ph, PRICE_COLUMNS, "PRICE_HISTORY")
        for _, r in ph.iterrows():
            if _is_blank(r.get("Ticker")) or _is_blank(r.get("Date")):
                continue
            dt = pd.to_datetime(r.get("Date"), errors="coerce")
            if pd.isna(dt) or dt.date() > date.today():
                continue
            if str(r.get("Market") or "").strip() != "Indonesia" or str(r.get("Currency") or "").strip().upper() != "IDR":
                continue
            close = _number(r.get("Close"), "Close", 0, default=None)
            if close is not None and close > 0:
                ticker = str(r["Ticker"]).strip().upper()
                if ticker not in prices or dt > prices[ticker][0]:
                    prices[ticker] = (dt, close)

    # Override workbook prices only when a valid external price is supplied.
    # Expected format: {"BBRI": {"price": 3500, "date": "2026-11-12"}}
    if market_prices:
        for raw_ticker, quote in market_prices.items():
            ticker = str(raw_ticker).strip().upper()
            if ticker not in positions or not isinstance(quote, dict):
                continue

            close = _number(quote.get("price"), "Market_Price", 0, default=None)
            dt = pd.to_datetime(quote.get("date"), errors="coerce")

            if close is None or close <= 0 or pd.isna(dt):
                continue
            if dt.date() > date.today():
                continue

            prices[ticker] = (dt, close)

    rows = []
    for ticker, p in positions.items():
        qty = p["Quantity_Shares"]
        price_record = prices.get(ticker)
        last_price = (
            price_record[1]
            if price_record is not None
            else p["Opening_Market_Price"]
        )
        price_date = (
            price_record[0].date()
            if price_record is not None
            else None
        )
        market_value = qty * last_price if last_price is not None and qty > 0 else None
        cost_basis = qty * p["Average_Cost"]
        unrealized = market_value - cost_basis if market_value is not None else None
        rows.append({
            "As_Of_Date": as_of,
            "Market": "Indonesia",
            "Ticker": ticker,
            "Quantity_Shares": qty,
            "Average_Cost": p["Average_Cost"],
            "Last_Price": last_price,
            "Price_Date": price_date,
            "Market_Value": market_value,
            "Cost_Basis": cost_basis,
            "Unrealized_PnL": unrealized,
            "Unrealized_PnL_Pct": (
                unrealized / cost_basis * 100
                if unrealized is not None and cost_basis > 0
                else None
            ),
            "Realized_PnL": p["Realized_PnL"],
            "Weight_Pct": None,
            "Currency": "IDR",
        })

    result_df = pd.DataFrame(rows)
    total_market_value = result_df["Market_Value"].sum(min_count=1)
    if pd.notna(total_market_value) and total_market_value > 0:
        result_df["Weight_Pct"] = (
            result_df["Market_Value"] / total_market_value * 100
        )
    priced = int(result_df["Market_Value"].notna().sum())
    if priced < len(result_df):
        warnings.append(
            f"{len(result_df) - priced} posisi belum memiliki harga pasar; "
            "Market Value dan Unrealized P&L belum lengkap."
        )

    total_cost_basis = float(result_df["Cost_Basis"].sum())
    total_unrealized = (
        float(result_df["Unrealized_PnL"].sum(min_count=1))
        if result_df["Unrealized_PnL"].notna().any() else float("nan")
    )
    return PortfolioResult(
        positions=result_df.sort_values("Ticker").reset_index(drop=True),
        cash_balance=float(cash_balance),
        as_of_date=as_of,
        total_market_value=float(total_market_value) if pd.notna(total_market_value) else float("nan"),
        total_cost_basis=total_cost_basis,
        total_unrealized_pnl=total_unrealized,
        priced_positions=priced,
        warnings=warnings,
    )




def export_analysis_to_excel(
    result: PortfolioResult,
    risk_result: dict[str, Any] | None = None,
    target_allocation: pd.DataFrame | None = None,
    rebalancing: pd.DataFrame | None = None,
    sector_result: dict[str, Any] | None = None,
    market_stress_result: dict[str, Any] | None = None,
    sector_stress_result: dict[str, Any] | None = None,
) -> bytes:

    """Export portfolio, risk, allocation and rebalancing analysis."""

    output = BytesIO()

    with pd.ExcelWriter(output, engine="openpyxl") as writer:

        # 1. HOLDINGS
        result.positions.to_excel(
            writer,
            sheet_name="HOLDINGS",
            index=False,
        )

        # 2. ANALYSIS RESULTS (existing sheet)
        result.positions.to_excel(
            writer,
            sheet_name="ANALYSIS_RESULTS",
            index=False,
        )

        # 3. PORTFOLIO SUMMARY
        pd.DataFrame([{
            "As_Of_Date": result.as_of_date,
            "Opening_and_Updated_Cash": result.cash_balance,
            "Total_Market_Value": result.total_market_value,
            "Total_Cost_Basis": result.total_cost_basis,
            "Total_Unrealized_PnL": result.total_unrealized_pnl,
            "Priced_Positions": result.priced_positions,
        }]).to_excel(
            writer,
            sheet_name="PORTFOLIO_SUMMARY",
            index=False,
        )

        # 4. VALIDATION NOTES (existing sheet)
        pd.DataFrame({
            "Warnings": result.warnings
        }).to_excel(
            writer,
            sheet_name="VALIDATION_NOTES",
            index=False,
        )

        # 5. RISK ANALYSIS
        if (
            isinstance(risk_result, dict)
            and risk_result.get("status") == "success"
        ):
            risk_summary = pd.DataFrame([{
                "First_Date": risk_result.get("first_date"),
                "Last_Date": risk_result.get("last_date"),
                "Observations": risk_result.get("observations"),
                "Annualized_Return_Pct": (
                    risk_result.get("annualized_return_pct")
                ),
                "Annualized_Volatility_Pct": (
                    risk_result.get("annualized_volatility_pct")
                ),
                "Maximum_Drawdown_Pct": (
                    risk_result.get("max_drawdown_pct")
                ),
            }])

            risk_summary.to_excel(
                writer,
                sheet_name="RISK_ANALYSIS",
                index=False,
            )

            risk_contribution = risk_result.get(
                "risk_contribution"
            )

            if isinstance(risk_contribution, pd.DataFrame):
                risk_contribution.to_excel(
                    writer,
                    sheet_name="RISK_CONTRIBUTION",
                    index=False,
                )

            correlation = risk_result.get(
                "correlation_matrix"
            )

            if isinstance(correlation, pd.DataFrame):
                correlation.to_excel(
                    writer,
                    sheet_name="CORRELATION_MATRIX",
                )

        # 6. TARGET ALLOCATION
        if isinstance(target_allocation, pd.DataFrame):
            target_allocation.to_excel(
                writer,
                sheet_name="TARGET_ALLOCATION",
                index=False,
            )

        # 7. REBALANCING ANALYSIS
        if isinstance(rebalancing, pd.DataFrame):
            rebalancing.to_excel(
                writer,
                sheet_name="REBALANCING_ANALYSIS",
                index=False,
            )

	# 8. SECTOR EXPOSURE
        if isinstance(sector_result, dict):

            sector_exposure = sector_result.get(
                "sector_exposure"
            )

            if isinstance(sector_exposure, pd.DataFrame):
                sector_exposure.to_excel(
                    writer,
                    sheet_name="SECTOR_EXPOSURE",
                    index=False,
                )

            # 9. SECTOR HOLDINGS
            sector_positions = sector_result.get(
                "positions"
            )

            
            if isinstance(sector_positions, pd.DataFrame):
                sector_positions.to_excel(
                    writer,
                    sheet_name="SECTOR_HOLDINGS",
                    index=False,
                )

        # 10. MARKET STRESS
        if isinstance(market_stress_result, dict):
            market_stress_table = market_stress_result.get(
                "scenario_results"
            )

            if isinstance(market_stress_table, pd.DataFrame):
                market_stress_table.to_excel(
                    writer,
                    sheet_name="MARKET_STRESS",
                    index=False,
                )

        # 11. SECTOR STRESS
        if isinstance(sector_stress_result, dict):
            sector_stress_table = sector_stress_result.get(
                "sector_stress"
            )

            if isinstance(sector_stress_table, pd.DataFrame):
                sector_stress_table.to_excel(
                    writer,
                    sheet_name="SECTOR_STRESS",
                    index=False,
                )

        # 12. FORMAT ALL EXPORTED WORKSHEETS
        from openpyxl.styles import Font, PatternFill, Alignment

        date_columns = {'As_Of_Date', 'Price_Date', 'First_Date', 'Last_Date'}
        percent_columns = {
            'Unrealized_PnL_Pct', 'Weight_Pct', 'Annualized_Return_Pct',
            'Annualized_Volatility_Pct', 'Maximum_Drawdown_Pct',
            'Risk_Contribution_Pct', 'Actual_Weight_Pct',
            'Target_Weight_Pct', 'Weight_Difference_Pct',
            'Portfolio_Impact_Pct', 'Shock_Pct'
        }
        integer_columns = {
            'Quantity_Shares', 'Priced_Positions', 'Stock_Count', 'Observations'
        }
        money_columns = {
            'Average_Cost', 'Last_Price', 'Market_Value', 'Cost_Basis',
            'Realized_PnL', 'Unrealized_PnL', 'Opening_and_Updated_Cash',
            'Total_Market_Value', 'Total_Cost_Basis', 'Total_Unrealized_PnL',
            'Target_Value', 'Value_Difference', 'Equity_Market_Value_Before',
            'Cash_Balance', 'Total_Portfolio_Value_Before', 'Estimated_PnL',
            'Equity_Market_Value_After', 'Stressed_Portfolio_Value',
            'Stressed_Market_Value'
        }

        for ws in writer.book.worksheets:
            ws.freeze_panes = 'A2'
            if ws.max_row >= 1 and ws.max_column >= 1:
                ws.auto_filter.ref = ws.dimensions

            for cell in ws[1]:
                cell.font = Font(bold=True, color='FFFFFF')
                cell.fill = PatternFill(fill_type='solid', fgColor='1F4E78')
                cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)

            for col_idx, header_cell in enumerate(ws[1], start=1):
                header = str(header_cell.value or '')
                for row_idx in range(2, ws.max_row + 1):
                    cell = ws.cell(row=row_idx, column=col_idx)

                    if header in percent_columns and cell.value is not None:
                        cell.value = cell.value / 100.0

                    if header in date_columns and cell.value is not None:
                        cell.number_format = 'yyyy-mm-dd'
                    elif header in percent_columns and cell.value is not None:
                        cell.number_format = '0.00%;[Red](0.00%);-'
                    elif header in integer_columns and cell.value is not None:
                        cell.number_format = '#,##0;[Red](#,##0);-'
                    elif header in money_columns and cell.value is not None:
                        cell.number_format = '#,##0;[Red](#,##0);-'

                values = [str(header_cell.value or '')]
                values.extend(str(ws.cell(row=r, column=col_idx).value or '') for r in range(2, ws.max_row + 1))
                ws.column_dimensions[header_cell.column_letter].width = min(max(max(map(len, values)) + 2, 12), 40)

            ws.row_dimensions[1].height = 30

    output.seek(0)


    return output.getvalue()

