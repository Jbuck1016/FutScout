# Site polish — 2026-10-01

Primary direction: private access, production-quality execution. No new model, data ingestion or lifecycle work in this pass.

## Implemented
- Model Lab: white/slate editorial palette, Georgia headings and readable sans-serif body; consistent 42px navigation controls, improved table/numeric typography, reduced box decoration, deliberate mobile two-column navigation.
- Trust tests lead with the conclusion, not the feature table. "Shots and territory are tied" corrected to "No clear winner": non-significance is not equivalence.
- Cross-season wording limits the claim to observed baseline improvements rather than asserting a proven cause of model instability.
- Section introductions explain the question and evidence limits.
- Current46 and historical44 scored calls preserved. Existing lineage labels retained; older count moved to explicit expandable research history. No count fabricated or replaced.
- Player landing replaced empty panel with four working routes: search, scouting shortlist, scatter and plot studio. Existing profile and numerical chart logic preserved.

## Verified
- node pipeline/tools/check_site_polish.js PASS (syntax, labels, theme scope, four actions).
- node pipeline/tools/check_player_metric_units.js PASS.
- python pipeline/tools/check_model_lab_dashboard.py PASS.
- Actual local desktop light/dark Model Lab render and 390px dark trust-test page inspected. Document width375 within390 viewport, no page-level horizontal overflow.
- Player landing desktop and390px light inspected. Search action focuses search field; Scout and Scatter open their actual controls. Plot studio initiation checked; complete data-loading verification recorded separately if performed.
- Actual dark feature-gate PNG downloaded and visually inspected: all columns, title, caveat and provenance footer readable and unclipped.
- Model Lab browser console error sample: none captured. Not an infrastructure log audit.
- No PDF regression performed in this pass. No claim of whole-site visual coverage.

## Remaining site-wide work
- Extend coherent surfaces/type/navigation across teams, sequences, rankings and match explorer with bespoke chart checks.
- Consolidate duplicate guidance and move detailed methodology behind usable disclosures without hiding essential caveats.
- Build a checked export matrix across chart types, dark/light and long/empty data.
- Generalize the worked match review only after fixture-specific source validation; one reviewed match is not universal coverage.
- Add automated screenshot/interaction regression coverage beyond the lightweight assertions here.
- Revisit player mobile sidebar allocation: current list takes substantial vertical space before investigation content.

## Integration boundary
Original local model-lab.html and players.html matched production byte-for-byte after newline normalization before edits. Publish only scoped files; preserve extensive unrelated dirty checkout. Forecast payloads, model registry, Supabase schema, scraper and operational schedules unchanged.
Frontend-design skill guided editorial hierarchy; sports-analytics guidance corrected evidence claims and distinguished snapshots. Deployment skill guides selective Git integration and production verification.

## Delivery
Commit 23c86a5556d542f12c336866791b733fb52ab218. Vercel production READY: dpl_8oNsxgDhgPfLfbrK9aL5haQeCmCY, https://arsenal-analytics-6c9s3r469-jbuck1016s-projects.vercel.app . Production Model Lab confirmed new palette and verdict-first order. Local Plot studio completed loading Sean Zawadzki and four selected metrics; no captured console errors. Production infrastructure logs/drains not audited. Remaining checklist above is not claimed complete.
