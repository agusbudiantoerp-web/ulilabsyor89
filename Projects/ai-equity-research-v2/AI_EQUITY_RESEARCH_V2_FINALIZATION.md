# AI Equity Research V2 — Finalization Notes

## What is included

- Existing Research Engine, DCF, Multi-Stage DCF, scenario analysis, Excel/PDF exports, Daily Signal, SQLite storage, Telegram adapter and Windows scheduler are retained from the supplied V2 project package.
- Daily Telegram report now has a dedicated TPIA section even when TPIA is classified as `NO_TRADE`.
- Gemma/Ollama commentary has a structured Indonesian prompt targeting approximately 300–350 tokens, a larger generation ceiling, and one retry when Ollama explicitly reports token-limit completion.
- `--dry-run` bypasses the same-day delivery guard and never sends Telegram or marks a report as delivered.
- Backtest CLI now prints a readable summary by default; `--json` retains the full machine-readable output and trade detail.
- Telegram delivery continues to use the configured allowlist and safe message chunking.

## Backtest command

```powershell
python daily_signal_cli.py backtest BBCA IDX
```

Full JSON output:

```powershell
python daily_signal_cli.py backtest BBCA IDX --json
```

The default model assumptions remain 10 bps fee and 10 bps slippage per side, 1% risk budget per trade, maximum 100% allocation, and a maximum five-session holding period. Change these only when the research protocol requires it.

## Daily report commands

```powershell
python daily_signal_scheduler.py --dry-run
python daily_signal_scheduler.py --test-ollama-telegram
python daily_signal_scheduler.py --test-telegram
```

A normal scheduled execution remains `python daily_signal_scheduler.py`; the existing Windows Task Scheduler task and `.env` secrets are not replaced by this package.

## Ollama settings

Defaults:

- URL: `http://127.0.0.1:11434/api/generate`
- Model: `gemma4:latest`
- Timeout: 300 seconds
- Output ceiling: 650 tokens (`OLLAMA_NUM_PREDICT` can override)
- Context: 4096 tokens

The model is instructed to use only the deterministic report data, preserve source prices and dates, avoid invented targets, and explicitly explain TPIA's status.

## Safety and research limitations

- The scanner covers only the configured starter watchlist, not all IDX/US listings.
- Yahoo Finance is a third-party source and daily bars are not live prices.
- Signals, entry bands, stops and targets are research hypotheses, not executable quotes or personalized investment advice.
- Backtests are simplified historical simulations. They do not fully model taxes, actual spread, market impact, suspensions, corporate actions, survivorship bias or intrabar execution ambiguity.
- Validate with walk-forward analysis and paper trading before considering real-world use.
- Never upload `.env`, Telegram tokens, chat IDs, or local SQLite data containing private operational details to public GitHub.


## Advanced Equity Intelligence extension

The follow-on extension is documented in [ADVANCED_EQUITY_INTELLIGENCE.md](ADVANCED_EQUITY_INTELLIGENCE.md). It adds the editable 40+40 IDX/US advanced screener, explainable 0–100 factor scoring, portfolio concentration/correlation/scenario analysis, currency-separated candidate allocation with IDX board-lot rounding, chronological walk-forward evaluation, and 1/3/5/10/20-session forward outcome tracking.

The scoring engine is deterministic and explainable; it is not a trained ML predictor. Walk-forward evaluation uses fixed rules and does not tune on test folds. Verify provider data, currency, sample size and execution assumptions before relying on results.


## Additional development — not yet validated

- Added an administrator-only Security & Audit console with OIDC role-map visibility, recent audit events, CSV export, hash-chain verification and configured storage-backend visibility.
- Logout audit events now follow the configured cloud PostgreSQL backend unless an explicit local audit database path is set.
- Added owner-scoped persistence for single-ticker, walk-forward and multi-asset research runs. Users can list, reload and delete only their own saved runs.
- Added confirmed owner-scoped deletion for saved portfolio books and audit events for portfolio and research-run operations.
- Expanded the Excel research pack to include available daily scan results, screener output, portfolio exposure/risk/optimization/stress scenarios, market intelligence diagnostics, backtest equity curves, trade details, walk-forward folds and saved-run metadata.
- Added audit events for Excel/PDF report downloads and administrator audit-log CSV exports.
- Added an administrator-only, read-only PostgreSQL health diagnostic for connectivity, required tables and basic table privileges; its results are also audit-logged.
- Added a confirmed administrator action to initialize the idempotent PostgreSQL schemas before running the read-only health check.
- Added a final Preview multi-user release test plan covering OIDC callbacks, role matrix, tenant isolation, audit, backtesting, exports and backup/restore.
- Hardened Excel report generation against formula injection from untrusted provider or ticker text.
- Fixed research-run storage initialization so the schema is created before the first SQLite/PostgreSQL save.
- Added `database_backup.py` for integrity-checked SQLite backups and PostgreSQL logical dumps with SHA-256 manifests, plus staging-first restore guidance.
- Added regression tests for owner-scoped research-run storage, PostgreSQL health diagnostics, detailed Excel workbook sheets and formula-injection protection. GitHub Actions is configured to run automatically on branch/PR updates. An earlier automatic run reported 173 passed and 3 failed because the first research-run save did not initialize its table; the initialization fix has been committed. The latest post-fix code still requires a fresh CI result and the planned end-to-end Preview validation before release.
