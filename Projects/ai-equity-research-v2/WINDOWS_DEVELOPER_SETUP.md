# Windows Developer Setup — AI Equity Research V2

This guide prepares a local Windows workstation without replacing an existing Python installation.

## 1. Install Python 3.11 side by side

The current release candidate requires Python 3.11 because the patched Pillow release requires Python 3.11 or newer. Keep Python 3.10 installed if other projects still depend on it.

Open PowerShell and check installed interpreters:

```powershell
py -0p
```

Install Python 3.11 from the official Python for Windows installer if it is not listed. Enable the Python Launcher during installation. Open a new PowerShell window and verify:

```powershell
py -3.11 --version
```

## 2. Open the project directory

From the repository root:

```powershell
Set-Location .\Projects\ai-equity-research-v2
```

## 3. Create an isolated environment

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python --version
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

If PowerShell blocks activation, allow it for this terminal only and activate again:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

Do not remove or modify the system-wide execution policy.

## 4. Run local checks

```powershell
python -m compileall -q . -x "\\.venv|equity-research-lab-main"
python -m pytest tests -q
```

The complete CI suite also provisions PostgreSQL 16 and runs restricted-role/RLS integration checks. A local run without a dedicated disposable PostgreSQL test database does not replace that CI coverage.

## 5. Optional OCR support for scanned bank filings

The Python OCR wrappers are installed by `requirements.txt`. Local Windows also needs the Tesseract OCR executable and Poppler command-line tools; `packages.txt` installs these only in Streamlit Cloud, not on Windows.

- Install Tesseract OCR 5.x and ensure `tesseract.exe` is available on PATH.
- Install Poppler for Windows and ensure its `Library\\bin` directory (containing `pdftoppm.exe`) is available on PATH.
- Open a new PowerShell window and verify:

```powershell
tesseract --version
pdftoppm -v
```

OCR is limited to 12 pages per document at 180 DPI. The registered BMRI Q3 2026 connector targets page 23 of its presentation. If either executable is unavailable, the app safely reports OCR REQUIRED and does not fill any extracted values. OCR output always requires analyst review.

## 6. Start the Streamlit application

```powershell
streamlit run app.py
```

For local-only exploration, the app may use its configured SQLite fallback. Do not connect a local development session to production PostgreSQL. Use a disposable Preview database for multi-user/OIDC acceptance.

## 7. Exit the environment

```powershell
deactivate
```

Keep OAuth secrets, cookie secrets, API keys and database connection strings in private local environment variables or Streamlit Secrets. Never commit them or paste them into chat.

## 8. Troubleshooting

- If `py -3.11` is not found, install Python 3.11 and reopen PowerShell.
- If package installation fails, confirm `python --version` reports 3.11 and retry inside the activated `.venv`.
- If the app imports packages from Python 3.10, deactivate the old environment, remove only this project's `.venv`, recreate it with `py -3.11 -m venv .venv`, and reinstall requirements.
- Do not delete database files or change Streamlit production secrets as part of local setup.
