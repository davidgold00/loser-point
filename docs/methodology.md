# Methodology

**Status: outline only (Phase 0).** Full ~2,500-word writeup to be completed
alongside Phase 3 (main models) and Phase 4 (regime DiD), once results exist
to report. Structure, fixed in advance:

1. Institutional background — point-system history (loser point 1999-10-01,
   shootout 2005-10-01, ROW tiebreaker 2010-10-01; dates to be verified
   against primary sources and cited here).
2. Data — MoneyPuck shot-level panel, NHL API standings/schedule, Hockey-Reference
   historical goal timestamps.
3. Panel construction — minute-boundary convention (see
   `docs/decisions/0001-minute-boundary-convention.md`), empty-net policy,
   situation filtering.
4. Identification — event-study/DiD, explicitly not RDD; why tied-late state
   is not randomly assigned; how team/opponent/Elo controls address it.
5. Specifications — equations for the main FE-Poisson model, the regime DiD,
   and the ROW natural experiment.
6. Pre-registered heterogeneity predictions (written **before** estimation).
7. Results.
8. Robustness battery.
9. Threats to validity.
10. Counterfactual and the Lucas-critique caveat.
