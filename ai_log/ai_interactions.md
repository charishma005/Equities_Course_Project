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

**Critical evaluation (to be written by the team):**

