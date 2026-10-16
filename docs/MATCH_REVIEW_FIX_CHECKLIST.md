# Match review and follow-up checklist — 30 September 2026

Scope: follow-up to the production audit, not a claim that every item has been re-audited today. Preserve the current shadow model and immutable forecasts.

## P0 — trust in the evidence

- [ ] **Reconcile xT definitions.** Saved Brighton–Arsenal team observations report 2.997–3.431 xT; event-map positive pass gains were 3.073–4.405, with carries separate. Trace filters, grid version, positive/net convention and aggregation. Acceptance: each view declares its definition and identical definitions reconcile to event IDs.
- [ ] **Prove complete frozen fixture coverage.** The September 17 report records four omitted matches. Test the current freeze gate against a missing league, postponed fixture and late schedule update. Acceptance: no incomplete slate can be labelled complete; no backfilled prediction counted as genuinely frozen.
- [ ] **Audit source fixture/player identity.** The event roster for this example includes names whose team membership merits source verification. Reconcile provider ID, date, teams and lineups to the raw archive before presenting the review as independently verified real-world reporting. Do not silently rewrite records.
- [ ] **Resolve public-data versus private-site expectations.** Existing gate.js explicitly says its password is a browser-side doormat, not data access control. Inventory exposed artifacts/API policies; present options before changing authentication. Acceptance: privacy wording matches actual protection. No new auth flow without user agreement.

## P1 — model interpretation

- [ ] **Expose the exact 3/5/10-window attribution inputs.** Last-three prose is context, not the full explanation of signed contributions. Acceptance: each contribution links to transformed inputs and model version; counterintuitive signs are explained without causal claims.
- [ ] **Replace the unweighted process winner.** The current saved report counts metric leads, including correlated territorial measures. Acceptance: show separate dimensions, not an invented composite match-quality verdict.
- [ ] **Separate frozen from reconstructed challengers.** Existing comparison uses a different as-of date and nonmatching source manifests. Acceptance: same-fixture research explicitly labelled exploratory; promotion comparisons require matched cutoffs and fixture manifests.
- [ ] **Audit shot-quality model calibration.** Saved xG has repeated binned values. Check shot type, penalties, headers, coordinates and calibration by league/season; compare held-out xG-per-shot signals. Acceptance: documented model/version and out-of-time calibration, not a claim that these are provider xG.
- [ ] **Add score-state and time-window review.** Compare level-score, trailing and leading periods; annotate goal timing. Acceptance: filters recompute denominators and never imply post-match information was a pre-match input.

## P2 — product quality and efficiency

- [ ] **Unify export contracts.** PNG and print/PDF should carry fixture, dates, units, source and caveats. Test mobile, light/dark, long labels, empty evidence and file output.
- [ ] **Resolve player population mismatch.** Trace the previously observed 2,916 touched versus 2,915 squad discrepancy. Acceptance: explain or eliminate the one-player difference using IDs, not names.
- [ ] **Optimize sequence similarity.** Timeout/retry is mitigation, not removal of the full-scan cost. Acceptance: benchmark representative queries with plans and returned-neighbour equivalence before changing the function.
- [ ] **Finish navigation and scope consistency.** Verify Go to, league labels, role/position distinctions, export controls and empty-state explanations across every subsection.

## This review's release checks

- [x] Frozen probabilities, log loss and multiclass Brier independently recomputed.
- [x] Event shot totals (17/11), goals (3/0), and 28/28 fitted xG availability verified; timing preserved including added time. Archived xG differs slightly and remains an explicit open reconciliation item.
- [x] Rendered light/dark and 390px/desktop layouts inspected. Narrow charts intentionally scroll rather than shrink labels. Both PNG controls exercised; shot-map PNG visually inspected. Browser print/PDF is provided but final PDF output has not been inspected.
- [x] Unknown fixture fails explicitly; no synthetic replacement evidence.
- [x] No model lifecycle, scraper or operational schedule changed.

Design reference: John Muller's Athletic match dashboards: https://johnspacemuller.substack.com/p/premier-league-match-dashboards . Reuse editorial principles, not branding or proprietary graphics.
