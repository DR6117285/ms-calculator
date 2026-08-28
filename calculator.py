"""
Core calculation module for M&S Bank credit card 0% promotional period.

All monetary values are in integer pence unless a function says otherwise.
Rounding: always ROUND_CEILING (round up to the next penny) so we never
underpay the contractual minimum and inadvertently forfeit the 0% rate.
"""
import calendar
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP

from config import (
    MIN_PAYMENT_FLOOR_PENCE,
    OPTION_A_REMAINDER_PCT,
    OPTION_B_BALANCE_PCT,
    STATEMENT_TO_DUE_DAYS,
)


def _pence_to_decimal(pence: int) -> Decimal:
    return Decimal(pence)


def _round_up(d: Decimal) -> int:
    """Round a Decimal pence value up to the next whole penny."""
    return int(d.to_integral_value(rounding=ROUND_CEILING))


# ── Minimum payment ───────────────────────────────────────────────────────────

@dataclass
class MinPaymentResult:
    amount_pence: int
    winning_option: str          # 'A', 'B', 'C', 'full_balance', 'zero'
    explanation: str
    option_a_pence: int = 0
    option_b_pence: int = 0
    option_c_pence: int = MIN_PAYMENT_FLOOR_PENCE


def calculate_minimum_payment(
    balance_pence: int,
    default_charges_pence: int = 0,
    interest_pence: int = 0,          # zero during 0% promotion
) -> MinPaymentResult:
    """
    Contractual minimum payment per M&S Bank / HSBC post-23 March 2011 T&Cs.

    Option A: interest + default_charges + 1% of (balance − interest − default_charges)
    Option B: 2.5% of full balance
    Option C: £5.00 floor

    Override: if balance < £5.00, the minimum is the full balance.

    During the 0% promotional period interest_pence = 0, so Option A collapses
    to default_charges + 1% of remainder, and Option B (2.5%) normally governs
    until the balance drops below the £5 floor. Option A overtakes Option B only
    if a default charge lands — this is why we keep them separate.

    # INSTALMENT PLANS: excluded from scope per spec. If added later, their
    # amounts and fees would be appended to the Option A figure here, and the
    # remaining instalment balance would be excluded from the Option A remainder
    # calculation. See payment allocation order in the T&Cs.
    """
    if balance_pence <= 0:
        return MinPaymentResult(
            amount_pence=0,
            winning_option='zero',
            explanation='Balance is zero or negative — no payment required.',
        )

    if balance_pence < MIN_PAYMENT_FLOOR_PENCE:
        return MinPaymentResult(
            amount_pence=balance_pence,
            winning_option='full_balance',
            explanation=(
                f'Balance £{balance_pence / 100:.2f} is under £5.00 — '
                f'pay the full outstanding balance.'
            ),
        )

    bal      = _pence_to_decimal(balance_pence)
    interest = _pence_to_decimal(interest_pence)
    charges  = _pence_to_decimal(default_charges_pence)

    remainder = bal - interest - charges
    if remainder < 0:
        remainder = Decimal(0)

    raw_a = interest + charges + (OPTION_A_REMAINDER_PCT * remainder)
    raw_b = OPTION_B_BALANCE_PCT * bal
    raw_c = Decimal(MIN_PAYMENT_FLOOR_PENCE)

    option_a = _round_up(raw_a)
    option_b = _round_up(raw_b)
    option_c = MIN_PAYMENT_FLOOR_PENCE

    winning = max(option_a, option_b, option_c)

    # Determine winner; prefer A > B > C on a tie so the explanation is accurate
    if winning == option_a:
        winner = 'A'
        explanation = (
            f'Option A wins: £{interest_pence / 100:.2f} interest + '
            f'£{default_charges_pence / 100:.2f} charges + '
            f'1% of £{int(remainder) / 100:.2f} remainder = '
            f'£{winning / 100:.2f}'
        )
    elif winning == option_b:
        winner = 'B'
        explanation = (
            f'Option B wins: 2.5% × £{balance_pence / 100:.2f} balance = '
            f'£{winning / 100:.2f}'
        )
    else:
        winner = 'C'
        explanation = (
            f'Option C wins: £5.00 floor '
            f'(both A and B computed less than £5.00)'
        )

    return MinPaymentResult(
        amount_pence=winning,
        winning_option=winner,
        explanation=explanation,
        option_a_pence=option_a,
        option_b_pence=option_b,
        option_c_pence=option_c,
    )


# ── Payoff payment ────────────────────────────────────────────────────────────

def calculate_payoff_payment(balance_pence: int, months_remaining: int) -> int:
    """
    Level monthly payment that clears the balance before the promotional period
    ends. Rounded up so the final payment slightly overpays rather than leaving
    a residual penny.

    If months_remaining is 0 or negative the whole balance is due immediately.
    """
    if months_remaining <= 0:
        return balance_pence
    if balance_pence <= 0:
        return 0
    result = Decimal(balance_pence) / Decimal(months_remaining)
    return _round_up(result)


# ── Promotional period timing ─────────────────────────────────────────────────

def months_elapsed_and_remaining(promo_start_date: date, promo_months: int, today: date = None) -> tuple[int, int]:
    """
    Returns (months_elapsed, months_remaining).

    months_elapsed counts whole calendar months since promo_start_date.
    months_remaining = promo_months − months_elapsed, floored at 0.
    """
    if today is None:
        today = date.today()

    elapsed = (today.year - promo_start_date.year) * 12 + (today.month - promo_start_date.month)
    elapsed = max(0, elapsed)
    remaining = max(0, promo_months - elapsed)
    return elapsed, remaining


def promo_end_date(promo_start_date: date, promo_months: int) -> date:
    month = promo_start_date.month + promo_months
    year  = promo_start_date.year + (month - 1) // 12
    month = (month - 1) % 12 + 1
    # Clamp to valid day (e.g. start on Jan 31, end won't be Feb 31)
    last_day = calendar.monthrange(year, month)[1]
    day = min(promo_start_date.day, last_day)
    return date(year, month, day)


# ── Due date ──────────────────────────────────────────────────────────────────

def next_due_date(statement_day: int, today: date = None) -> tuple[int, date]:
    """
    Returns (days_until_due, due_date) for the next payment due date.

    Due date = statement date + 25 days.
    Walks forward through months until we find a due date strictly in the future.
    Handles months shorter than statement_day by clamping to the last day.
    """
    if today is None:
        today = date.today()

    def _statement_date(y, m):
        last = calendar.monthrange(y, m)[1]
        return date(y, m, min(statement_day, last))

    year, month = today.year, today.month
    for _ in range(14):  # safety: at most 14 months forward
        stmt = _statement_date(year, month)
        due  = stmt + timedelta(days=STATEMENT_TO_DUE_DAYS)
        if due > today:
            return (due - today).days, due
        month += 1
        if month > 12:
            month = 1
            year += 1

    # Fallback should never be reached
    stmt = _statement_date(today.year, today.month + 1)
    due  = stmt + timedelta(days=STATEMENT_TO_DUE_DAYS)
    return (due - today).days, due


# ── Projection ────────────────────────────────────────────────────────────────

@dataclass
class ProjectionRow:
    month_number: int
    balance_before_pence: int
    min_payment_pence: int
    min_option: str
    min_balance_after_pence: int
    payoff_payment_pence: int
    payoff_balance_after_pence: int


def build_projection(
    balance_pence: int,
    months_remaining: int,
    default_charges_pence: int = 0,
) -> tuple[list[ProjectionRow], int, int]:
    """
    Month-by-month projection for months_remaining months.

    Returns:
        rows                      — list of ProjectionRow
        min_only_end_balance      — projected balance at end of promo if paying min only
        payoff_end_balance        — projected balance at end if paying payoff amount

    Assumptions:
      - No new purchases or charges during the projection period
      - Interest remains 0 (0% promotion)
      - Default charges passed in affect only the first month's Option A calculation;
        subsequent months assume no new charges (conservative projection)
    """
    if months_remaining <= 0 or balance_pence <= 0:
        return [], balance_pence, balance_pence

    payoff_pmt = calculate_payoff_payment(balance_pence, months_remaining)

    min_bal    = balance_pence
    payoff_bal = balance_pence
    rows = []

    for m in range(1, months_remaining + 1):
        # Min-only path
        if min_bal > 0:
            charges_this_month = default_charges_pence if m == 1 else 0
            min_result = calculate_minimum_payment(min_bal, charges_this_month)
            min_pmt = min(min_result.amount_pence, min_bal)
            new_min_bal = max(0, min_bal - min_pmt)
        else:
            min_pmt = 0
            min_result = MinPaymentResult(0, 'zero', '')
            new_min_bal = 0

        # Payoff path
        if payoff_bal > 0:
            payoff_pmt_this = min(payoff_pmt, payoff_bal)
            new_payoff_bal = max(0, payoff_bal - payoff_pmt_this)
        else:
            payoff_pmt_this = 0
            new_payoff_bal = 0

        rows.append(ProjectionRow(
            month_number=m,
            balance_before_pence=min_bal,
            min_payment_pence=min_pmt,
            min_option=min_result.winning_option,
            min_balance_after_pence=new_min_bal,
            payoff_payment_pence=payoff_pmt_this,
            payoff_balance_after_pence=new_payoff_bal,
        ))

        min_bal    = new_min_bal
        payoff_bal = new_payoff_bal

    return rows, min_bal, payoff_bal


# ── Dashboard summary ─────────────────────────────────────────────────────────

@dataclass
class DashboardSummary:
    balance_pence: int
    credit_limit_pence: int
    headroom_pence: int
    months_elapsed: int
    months_remaining: int
    promo_end: date
    days_until_due: int
    next_due_date: date
    min_payment: MinPaymentResult
    payoff_payment_pence: int
    shortfall_pence: int                    # payoff − minimum
    projected_end_balance_min_pence: int    # if paying minimums only
    overpayment: bool


def build_dashboard(config: dict, balance_summary: dict, today: date = None) -> DashboardSummary:
    """
    Assembles the full dashboard from card config and balance summary.
    Handles all edge cases:
      - zero / negative balance
      - months_remaining = 0
      - overpayment (T&Cs say excess is refunded, not held as credit)
      - balance < £5 (min payment = full balance)
    """
    if today is None:
        today = date.today()

    from datetime import date as _date
    promo_start = _date.fromisoformat(config['promo_start_date'])
    promo_months = config['promo_months']
    statement_day = config['statement_day']
    credit_limit = config['credit_limit_pence']

    balance = balance_summary['balance_pence']
    charges = balance_summary['default_charges_pence']
    is_overpayment = balance_summary['overpayment']

    elapsed, remaining = months_elapsed_and_remaining(promo_start, promo_months, today)
    end_date = promo_end_date(promo_start, promo_months)
    days_due, due_date = next_due_date(statement_day, today)

    min_result = calculate_minimum_payment(balance, charges)
    payoff     = calculate_payoff_payment(balance, remaining)
    shortfall  = max(0, payoff - min_result.amount_pence)

    _, end_balance_min, _ = build_projection(balance, remaining, charges)

    headroom = max(0, credit_limit - balance)

    return DashboardSummary(
        balance_pence=balance,
        credit_limit_pence=credit_limit,
        headroom_pence=headroom,
        months_elapsed=elapsed,
        months_remaining=remaining,
        promo_end=end_date,
        days_until_due=days_due,
        next_due_date=due_date,
        min_payment=min_result,
        payoff_payment_pence=payoff,
        shortfall_pence=shortfall,
        projected_end_balance_min_pence=end_balance_min,
        overpayment=is_overpayment,
    )
