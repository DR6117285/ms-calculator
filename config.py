"""
M&S Bank credit card calculator — all tunable constants live here.
A rate change, floor change, or charge amount change means editing this file only.
"""
from decimal import Decimal

# ── Minimum payment floors and charges (in pence) ──────────────────────────
MIN_PAYMENT_FLOOR_PENCE = 500       # £5.00 — Option C and the sub-£5 override

# Default charges per M&S Bank / HSBC UK T&Cs (post-23 March 2011 agreement)
DEFAULT_CHARGE_LATE_PENCE      = 1200   # £12.00 — late minimum payment
DEFAULT_CHARGE_OVER_LIMIT_PENCE = 1200  # £12.00 — over credit limit
DEFAULT_CHARGE_RETURNED_PENCE  = 1200   # £12.00 — returned payment

DEFAULT_CHARGE_SUBTYPES = {
    'late_payment':   ('Late payment', DEFAULT_CHARGE_LATE_PENCE),
    'over_limit':     ('Over credit limit', DEFAULT_CHARGE_OVER_LIMIT_PENCE),
    'returned_payment': ('Returned payment', DEFAULT_CHARGE_RETURNED_PENCE),
}

# ── Minimum payment percentages ─────────────────────────────────────────────
# Option A: interest + default_charges + this % of the remainder
OPTION_A_REMAINDER_PCT = Decimal('0.01')    # 1%

# Option B: this % of the full outstanding balance
OPTION_B_BALANCE_PCT = Decimal('0.025')     # 2.5%

# ── Non-sterling surcharge ──────────────────────────────────────────────────
NON_STERLING_SURCHARGE_PCT = Decimal('0.0299')  # 2.99% on top of sterling amount

# ── Statement / due date ────────────────────────────────────────────────────
STATEMENT_TO_DUE_DAYS = 25  # payment due 25 days after statement date

# ── Promotional period defaults (overridable via card setup UI) ─────────────
DEFAULT_PROMO_MONTHS = 26
DEFAULT_STATEMENT_DAY = 1   # day of month the statement is issued
