# AI Interaction Log

The course requires at least three documented GenAI interactions. Each entry
has the prompt verbatim, a short summary of what the AI produced, and a
critical evaluation that **the team** writes. If a bug or wrong assumption in
AI-generated code turns up later (especially look-ahead bias), add a note to
the relevant entry describing what was wrong and how it was fixed.

---

## Entry 1: Repository setup and Phase 1 data-pull code

- **Date:** 2026-10-02
- **Phase:** 1 (data pulls)
- **Tool:** Claude Code

**Prompt (verbatim):**

> [The project plan `CLAUDE.md` attached as a file, with no other text.]
>
> https://github.com/charishma005/Equities_Course_Project I want to set up this repo for the project

**Summary of what was produced:**

Claude Code set up the repository layout from CLAUDE.md section 2, plus a
`.gitignore` that excludes `data/raw/`, `data/interim/`, and `.env`, and a
`config.py` with every parameter from the plan. It wrote `src/pull_wrds.py`
(SQL pulls for I/B/E/S statsum, the I/B/E/S-CRSP link table, and CRSP
msf/msenames/msedelist, with credentials read through `~/.pgpass` or a
prompt) and `src/pull_public.py` (parsers for Ken French CSV/SIC files and
FRED). Ken French percent returns are converted to decimals and missing codes
to NaN. Offline unit tests cover the parsers, the month-end date convention,
and the gitignore rules. The pulls could not be run because the cloud sandbox
has no network access to WRDS, Ken French, or FRED.

**Bug found later (2026-10-03):** the AI wrote type hints such as
`pd.Series | pd.DatetimeIndex`, which need Python 3.10+. The plan says
Python 3.11+, but a teammate's Mac runs Python 3.9, so every script
crashed on import with `TypeError: unsupported operand type(s) for |`.
The AI had only tested on Python 3.11 in its own sandbox. Fixed by adding
`from __future__ import annotations` to every module and re-running the
tests under Python 3.9 with the teammate's pandas version (2.2.3). The
same session also changed the importer to skip files it does not
recognize instead of crashing, and to apply the MEASURE/FPI filters when
those columns are present in a web-query download.

**Critical evaluation (to be written by the team):**

**Later note (2026-10-04):** the web-download importer
(`src/import_wrds_files.py`) was removed after the team switched to CRSP CIZ
tables pulled by `pull_wrds.py`; it still expected legacy CRSP columns and
would have silently dropped delisting returns.

---

## Entry 2: Review of Phases 2–3 and the 2026 coverage gap

- **Date:** 2026-10-04
- **Phase:** 2–3 (cleaning, signals)
- **Tool:** Claude Code

**Prompts (verbatim):**

> https://github.com/charishma005/Equities_Course_Project
>
> how is this looking so far; any improvements needed?

> what are the next steps now?  currently ignoring 2026

> [mid-task, pasting advice from another AI tool] For the primary results,
> don't include 2026 REV or REV_ALT. [...] Keep the planned March 2025–August
> 2026 review window and report how many months each signal actually covers;
> don't shift the window to make coverage look complete. [...] so should i
> include 2026 now or not in reviewing my results?

**Summary of what was produced:**

Claude Code reviewed the team's Phase 2–3 commit against CLAUDE.md. It
found that momentum compounded months t-12 to t-2 instead of the planned
t-11 to t-1, and that CRSP characteristics were carried forward across
mid-sample gaps rather than only after CRSP ends; both were fixed with
tests. It traced the missing 2026 REV to the annually updated I/B/E/S-CRSP
link table and laid out alternatives (extending active links, CUSIP
matching, I/B/E/S `actpsum` prices). It added the Phase 2 thin-industry
flag, Phase 3 coverage tables, a horizon-coverage table, the MOM-REV
correlation figure, and `tests/test_timing.py` (end-to-end t to t+1
alignment and a check that future data cannot change past signals).

**Wrong assumption caught during the interaction:** when told to ignore
2026, the AI first added a December 2025 sample cutoff, which would have
moved the "most recent 18 months" window to July 2024–December 2025. That
shifts the window to make coverage look complete, which the plan forbids.
After the team's correction it removed the cutoff: 2026 rows stay in the
panel with REV and REV_ALT missing, the window stays March 2025–August
2026, and coverage per signal is reported instead. The decision was
written into CLAUDE.md 4.4 and 10.1.

**Parallel work:** a teammate pushed the same momentum and carry-forward
fixes, a 49-industry coverage grid, and the separate 2026 CUSIP/ACTPSUM
sensitivity while this session was running. The merge kept the teammate's
versions where the two overlapped (their committed result tables were made
with them) and kept this session's horizon-coverage table, future-data
invariance test, and plan-compliant figure styling.

**Critical evaluation (to be written by the team):**


---

## Entry 3: Phase 4 checkpoint and Phase 5 risk model / portfolio construction

- **Date:** 2026-10-04
- **Phase:** 4–5 (IC checkpoint, risk model, holdings)
- **Tool:** Claude Code

**Prompts (verbatim):**

> what's next steps after u review the git hub

> yes do steps 1-2 then start phase 5  and Still open: the repo is public and
> contains derived WRDS outputs and real AAPL values. Make it private unless
> your course says otherwise. - ignore for now we will see in the end

**Summary of what was produced:**

Claude Code reviewed the team's Phase 4 code (no look-ahead found) and
flagged the CLAUDE.md 12.4 checkpoint: REV orthogonal to momentum has an IC
of about zero (Newey-West t -0.05 over 1985–2025, -0.50 post-2010). It added
a REV-sample comparison window, Newey-West t-stats, and figure titles with
sample periods. For Phase 5 it wrote `src/risk.py` (EWMA covariance, 30-month
half-life, residual volatility) and `src/portfolio.py` (Grinold-Kahn alphas,
dollar-neutral mean-variance holdings with a 10%-of-gross cap solved as a
fixed point, the diagonal comparison, and monthly λ calibration to 5%
ex-ante risk), with tests for timing and constraints. It found that realized
active volatility of the mean-variance books is about twice the 5% target
and ran a side test showing covariance shrinkage closes most of the gap; it
left the choice to the team rather than changing the plan's risk model.

**Not logged by Claude Code:** the team also used another AI tool for the
2026 coverage advice pasted into the Entry 2 conversation. That interaction
should get its own entry, with the prompt the team sent it.

**Critical evaluation (to be written by the team):**


---

## Entry 4: Covariance shrinkage and Phase 6 backtest

- **Date:** 2026-10-04
- **Phase:** 5–6 (risk model change, backtest, costs)
- **Tool:** Claude Code

**Prompt (verbatim):**

> how are the risks looking so far; ok go with covariance shrinkage and go
> with phase 6;

**Summary of what was produced:**

Claude Code added 50% shrinkage of the EWMA covariance toward its diagonal
(the team's decision, recorded in CLAUDE.md 7.1), which brought realized
active volatility of the mean-variance books from about 10% to 4.3–6.6%
against the 5% target and cut gross exposure from about 4x to 1.2–1.5x. It
wrote `src/backtest.py` (t+1 returns, drift-adjusted turnover, costs charged
on the following month, performance by window, cumulative-return and
drawdown figures) with tests that hand-check turnover and timing. Over
1995–2025, MOM nets a 0.40 Sharpe at 20 bp and the blend 0.27, while REV and
REV orthogonal have no gross edge and lose heavily after costs because their
industry rankings turn over about 175% a month.

**Critical evaluation (to be written by the team):**


---

## Entry 5: Phase 7 factor attribution code

- **Date:** 2026-10-04
- **Phase:** 7 (factor attribution)
- **Tool:** Claude Code

**Prompt (verbatim):**

> ok

(in reply to: "Should I go ahead [with Phase 7]?")

**Summary of what was produced:**

Claude Code wrote `src/attribution.py`, which regresses each strategy's
20 bp net returns on FF5 + UMD, FF5 alone, and FF5 + UMD + short-term
reversal with Newey-West t-stats, across the four windows, and builds the
with/without-UMD comparison table with a rejection-criterion flag. Returns
are matched to factors by calendar month, and the run stops if any month is
missing, to guard against off-by-one errors. The Ken French factor files are
not in the repository, so the code was tested on synthetic factors and must
be run by the team to produce real results.

**Problem found after the team ran it (2026-10-04):** the AI's
`passes_criterion` flag marked the blend's recent-18-month window as "yes"
(alpha t = 3.4). That window has only 10 monthly observations for 7
regression parameters with 6 Newey-West lags, so the t-stat is meaningless.
The AI had not guarded against tiny samples. Fixed by labeling windows with
fewer than 36 months "low power" (`CRITERION_MIN_MONTHS`) while still
reporting the regression, as CLAUDE.md 9 asks.

**Critical evaluation (to be written by the team):**


---

## Entry 6: Phase 8 robustness grid and subperiod stability

- **Date:** 2026-10-04
- **Phase:** 8 (robustness)
- **Tool:** Claude Code

**Prompt (verbatim):**

> ok

(in reply to: "Should I start [Phase 8]?")

**Summary of what was produced:**

Claude Code wrote `src/robustness.py`, a one-at-a-time grid around the base
case plus a full 3x3 momentum-lookback x half-life heatmap, where each row
reruns signals, the IC blend, holdings, and the backtest for the blended
strategy and is scored on a fixed 1995–2025 window. It added a beta-neutral
option to the optimizer, a 30-industry hook, annual returns, a 2009/2020
stress table, and a rolling-alpha step that runs where the factor files
exist. The base row reproduces Phase 6 to within 1e-10. No setting gives a
net Sharpe above 0.38; the momentum lookback drives the results, and the
consensus-change REV makes the blend worse. The minimum-analysts and
30-industry rows and all factor alphas need the team's raw data.

**Bug found when the team ran it (2026-10-04):** `attribution.align`, written
by the AI in Phase 7, compared two columns using a row mask built before a
merge that renumbers rows. When the input was a filtered subset (the
rolling-alpha step and `--alphas-only`), the labels no longer lined up and
pandas 2.2 (the teammate's version) crashed with an `AssertionError`, so the
rolling 36-month alpha was never written. The AI's tests only used freshly
numbered rows, and its own environment ran pandas 3. Fixed by renumbering
rows and comparing plain arrays; a regression test now passes a filtered
subset, and the fix was checked under pandas 2.2.3 / Python 3.9. The bug
could only crash, never misalign silently, so the committed grid alphas
are unaffected.

**Critical evaluation (to be written by the team):**


---

## Entry 7: Phase 9 report assets

- **Date:** 2026-10-04
- **Phase:** 9 (report assets)
- **Tool:** Claude Code

**Prompt (verbatim):**

> ok

(in reply to: "Want me to build [Phase 9]?")

**Summary of what was produced:**

Claude Code wrote `src/report.py`, which builds `results/summary.md` from the
committed result tables: the IC, risk/λ, performance, factor-regression,
horizon, and robustness tables, a captioned list of every figure, a
checklist mapping each report section to its evidence, and a draft
executive summary whose numbers are read from the tables. Its first draft
of the summary said no strategy or window reached t ≥ 2, which was false:
the blend's 10-month recent window has t = 3.40. The AI caught this on
review and rewrote the sentence to state the low-power exception
explicitly.

**Critical evaluation (to be written by the team):**

