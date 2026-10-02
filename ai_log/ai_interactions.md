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

**Critical evaluation (to be written by the team):**

