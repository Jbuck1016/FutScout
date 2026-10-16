# Six evidence and product fixes — 30 September 2026

## Implemented

1. **Metric reconciliation.** Brighton–Arsenal sequence/net all-phase successful-pass xT is 2.997–3.431; positive open-play successful-pass xT is 3.073–4.405. Database function inspection and event aggregation reconcile both definitions. The live xG bins refit from all available shots: archived report 1.7225–1.0978 and captured event feed 1.7156–1.0923 are distinct snapshots, not values to overwrite. Added a user-facing Evidence definitions page.
2. **Source identity.** All 1,495 raw event IDs, team IDs, player IDs and player names match the retained WhoScored archive for source match 1983575 / canonical fd-560586. Date, teams and 3–0 score match. Gzip level-9/mtime-0 SHA-256 matches the private storage manifest: 8cf3f17c757edcdbf7ef3261b10db300ecc895aafa4d4edd1711d60be4755128. This verifies source consistency, not an independent provider's real-world match account.
3. **Fixture completeness.** Strict freeze manifests now account for every provider fixture using actual unique rows, including explicit exclusions. Missing league/fixture, duplicate prediction, changed identity/kickoff, missing kickoff and late capture fail. Postponed/suspended/cancelled rows are excluded from the expected active week, not silently lost. Existing legacy manifests must be freshly captured for future freezes; old predictions remain untouched. The September 17 omissions are not retroactively fixed.
4. **Exact explanation ledger.** New explanations retain raw and normalized numeric inputs, home/away transformed values, coefficients and log-rate contributions. Shared UI renders these and clearly marks legacy snapshots without a ledger. Corrected log-rate units: the prior “goal balance” label could be mistaken for goals. No historical reconstruction is passed off as a frozen input.
5. **Comparison eligibility.** Matching fixture names is insufficient. Comparison output is exploratory unless real cutoff timing and matching fixture, source-row and feature-input hashes pass. Even then, eligibility requires the tournament audit/scorer; the comparison tool never grants promotion.
6. **Shared product contract.** Navigation includes review/definition pages and matches neighbouring button dimensions. Shared exports cover supported sections/panels, preserve cloned canvases, capture selected context, normalize modern CSS colours, and paginate long PDFs. Existing bespoke chart exporters are not duplicated. Definitions explain xT, fitted xG, effect units, windows and evidence eligibility.

## Verification

- `check_model_artifact.py`: point-in-time invariance and exact contribution arithmetic passed (synthetic only).
- `check_frozen_tournament_contract.py`: complete five-model synthetic freeze/audit/scoring plus missing/duplicate/identity/kickoff/late-capture cases passed.
- `check_evidence_classification.py`: stale, rolling, missing or mismatched provenance stays exploratory; matching data still requires audit.
- `check_forecast_evidence.js`: escaping, units, windows, legacy fallback passed.
- Model Lab and forecast dashboard safety tests passed; JavaScript syntax and Python compilation passed.
- Browser: legacy disclosure and corrected units rendered; Go to includes full destinations with matching button height.
- Actual tournament PDF downloaded and rendered for inspection. Synthetic 100-row/canvas PDF produced three pages; canvas content survives. Local synthetic QA page is not deployed.

## Boundaries

No model training, promotion, lifecycle writes, scraper changes, task schedule changes or historical forecast rewrites. Full ledgers become available in newly generated forecasts; missing legacy evidence remains missing. Source verification covered this worked match, not every historical fixture. Shared export fixes do not claim a new exhaustive audit of every bespoke export implementation.
