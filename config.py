"""Project-wide parameters. Every tunable number lives here (CLAUDE.md 1.3).

Timing convention: all monthly data are indexed by month-end timestamps
(datetime64, last calendar day of the month). A signal dated month-end t
uses information available on or before t and predicts the return of t+1.
"""

from __future__ import annotations

from pathlib import Path

# --------------------------------------------------------------------------
# Paths
# --------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent
DATA_RAW = ROOT / "data" / "raw"
DATA_INTERIM = ROOT / "data" / "interim"
DATA_PROCESSED = ROOT / "data" / "processed"
RESULTS = ROOT / "results"
FIGURES = RESULTS / "figures"
TABLES = RESULTS / "tables"

# --------------------------------------------------------------------------
# Phase 1: data pulls
# --------------------------------------------------------------------------
IBES_START = "1985-01-01"          # first statpers pulled
CRSP_START = "1984-01-01"          # one year before signals, for lookbacks
LINK_MAX_SCORE = 2                 # keep I/B/E/S-CRSP links with score <= 2

KF_BASE_URL = "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/"
KF_FILES = {
    "ind49": "49_Industry_Portfolios_CSV.zip",
    "ind30": "30_Industry_Portfolios_CSV.zip",     # Phase 8 robustness
    "sic49": "Siccodes49.zip",
    "sic30": "Siccodes30.zip",
    "ff5": "F-F_Research_Data_5_Factors_2x3_CSV.zip",
    "umd": "F-F_Momentum_Factor_CSV.zip",
    "strev": "F-F_ST_Reversal_Factor_CSV.zip",
}
KF_MISSING = (-99.99, -999.0)      # Ken French missing-value codes

FRED_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}"
FRED_SERIES = ["BAA10Y", "T10Y2Y"]
MACRO_LAG_MONTHS = 1               # applied when used (Phase 8), not at pull

# --------------------------------------------------------------------------
# Phase 2: cleaning
# --------------------------------------------------------------------------
SHRCD_KEEP = (10, 11)
EXCHCD_KEEP = (1, 2, 3)
CRSP_GAP_MAX_CARRY_MONTHS = 12     # max forward-fill of cap/SIC past CRSP end
OTHER_INDUSTRY_49 = 49
MIN_FIRMS_PER_INDUSTRY = 5

# --------------------------------------------------------------------------
# Phase 3: signals
# --------------------------------------------------------------------------
MOM_LOOKBACK = 12
MOM_SKIP = 1
MIN_ANALYSTS = 3
REV_ALT_LAG_MONTHS = 3
REV_ALT_WINSOR = (0.01, 0.99)
Z_WINSOR = 3.0

# --------------------------------------------------------------------------
# Phase 4: IC and blending
# --------------------------------------------------------------------------
BLEND_MIN_MONTHS = 60
ROLLING_IC_MONTHS = 12

# --------------------------------------------------------------------------
# Phase 5: risk and portfolio
# --------------------------------------------------------------------------
COV_HALFLIFE_MONTHS = 30
COV_MIN_MONTHS = 60
ANNUALIZE = 12
TARGET_ACTIVE_RISK = 0.05          # annualized
POSITION_CAP_FRAC_GROSS = 0.10

# --------------------------------------------------------------------------
# Phase 6-8: backtest, attribution, robustness
# --------------------------------------------------------------------------
COSTS_BPS = (10, 20, 30)
BASE_COST_BPS = 20
NW_LAGS = 6
POST_SPLIT = "2010-01-31"
RECENT_MONTHS = 18
ROLLING_ALPHA_MONTHS = 36

GRID = {
    "mom_lookback": (6, 9, 12),
    "rev_measure": ("net_ratio", "consensus_change"),
    "min_analysts": (1, 3, 5),
    "cov_halflife": (18, 30, 60),
    "target_active_risk": (0.03, 0.05, 0.08),
    "cost_bps": (10, 20, 30),
    "industry_set": (49, 30),
    "neutrality": ("dollar", "dollar_beta"),
}

FIG_DPI = 200
