# Bank Valuation & Fundamental Data Controls

## Valuation method

Banks are valued with the Residual Income Model (RIM), not generic FCFF DCF. The base model uses common book equity per share, forecast ROE, cost of equity and stable book-value growth. The model remains sensitive to parent-attributable equity, diluted shares, reporting period, credit quality, capital needs and regulation.

## ROE hierarchy

1. Analyst-entered **Official reported ROE (%)** from a named filing is preferred when supplied; the UI and reports label it as analyst-entered and not independently verified. Record the exact ROE definition (for example, net income after tax / average equity versus Tier 1 average equity) and use a matching reporting period.
2. Calculated ROE = latest net income attributable to parent / average reported stockholders' equity, when comparable periods are available.
3. Provider ROE is a fallback only and is explicitly labelled unverified.
4. Closing-equity ROE is a proxy when average equity cannot be calculated.
5. The separate manual valuation override remains labelled User assumption.

The current Yahoo Finance data path is an aggregator, not an official filing verification service. A populated provider field must not be described as verified.

## Bank operating and regulatory ratios

The application accepts manual inputs for the following indicators. Enter values from the same reporting period and identify the filing used.

| Indicator | Formula / definition |
|---|---|
| NPL gross | Non-performing loans / total loans |
| CAR / KPMM | Regulatory capital / risk-weighted assets |
| LDR | Loans to third-party non-bank borrowers / third-party funds |
| NIM | Net interest income / average earning assets |

OJK's *Laporan Surveillance Perbankan Indonesia Triwulan I 2026*, Appendix I, lists these indicator formulas (including CAR, NIM, NPL gross and LDR): https://ojk.go.id/id/kanal/perbankan/data-dan-statistik/laporan-profil-industri-perbankan/Documents/Laporan%20Surveillance%20Perbankan%20Indonesia%20-%20Triwulan%20I%202026.pdf

## Data quality statuses

- **INSUFFICIENT DATA**: a required core field (equity, net income, shares or price) is absent/invalid.
- **REVIEW REQUIRED**: core data exists, but official filing provenance, one or more bank ratios, average equity, or a consistency check is incomplete.
- **VERIFIED**: the analyst has supplied the source name, reporting period and HTTPS filing URL; all four bank ratios; average equity; and explicitly attested that the official filing and figures were checked. This is an analyst attestation, not an automated validation by the application.

Consistency checks include calculated ROE vs provider ROE, book value per share, price × shares vs provider market capitalization, and the calendar-day gap between the latest market-price date and the latest balance-sheet/income-statement period. A gap greater than 150 days is marked STALE and blocks VERIFIED status. Missing reporting dates are marked UNKNOWN; they are not assumed current.

A documented official ROE input is distinct from the valuation-assumption override. It changes the RIM forecast ROE but does not independently verify the figure. The official source period must still match the financial statement periods used by the model.

## Exports

Excel includes Bank Valuation, Bank RIM Forecast, Bank Sensitivity, Bank Scenarios, Bank Ratios, Bank Data Checks and Bank Review. PDF includes the RIM summary, scenarios, filing provenance, ratio inputs, consistency checks and review notes.

## Limitations

- The current automatic filing connector is limited to the registered BBRI Q3 2026 issuer PDF. It extracts NPL gross, KPMM/CAR, ROE footnote 4, NIM and LDR as review-only candidates with source URL, period, PDF page and SHA-256 provenance.
- The collector does not yet replace the app's core balance-sheet, income-statement or share-count feed. The market-price/fundamental freshness gate therefore remains active until those core statement fields are separately reconciled to the same period.
- Other bank issuers require their own verified official-domain mapping and document-layout tests before automated retrieval is enabled.
- PDF extraction is text-based; scanned pages requiring OCR are not silently interpreted. An extraction result never sets analyst confirmation or VERIFIED status.
- Verify parent-attributable equity, diluted shares, consolidated/per-share units, FX, period alignment and restatements against the official filing.
- VERIFIED means the named analyst attested to reviewing the filing; it is not an audit opinion, regulatory rating or investment recommendation.
