# Bank Valuation & Fundamental Data Controls

## Valuation method

Banks are valued with the Residual Income Model (RIM), not generic FCFF DCF. The base model uses common book equity per share, forecast ROE, cost of equity and stable book-value growth. The model remains sensitive to parent-attributable equity, diluted shares, reporting period, credit quality, capital needs and regulation.

## ROE hierarchy

1. Calculated ROE = latest net income attributable to parent / average reported stockholders' equity, when two comparable balance-sheet periods are available.
2. Provider ROE is a fallback only and is explicitly labelled unverified.
3. Closing-equity ROE is a proxy when average equity cannot be calculated.
4. A manual ROE override is always labelled User assumption.

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

Consistency checks include calculated ROE vs provider ROE, book value per share, and price × shares vs provider market capitalization. Material discrepancies block VERIFIED status.

## Exports

Excel includes Bank Valuation, Bank RIM Forecast, Bank Sensitivity, Bank Scenarios, Bank Ratios, Bank Data Checks and Bank Review. PDF includes the RIM summary, scenarios, filing provenance, ratio inputs, consistency checks and review notes.

## Limitations

- NPL, CAR, LDR and NIM are not automatically retrieved from OJK or issuer filings.
- The filing URL is recorded, not fetched or parsed by the application.
- Verify parent-attributable equity, diluted shares, consolidated/per-share units, FX, period alignment and restatements against the official filing.
- VERIFIED means the named analyst attested to reviewing the filing; it is not an audit opinion, regulatory rating or investment recommendation.
