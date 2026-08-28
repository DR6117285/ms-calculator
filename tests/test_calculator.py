"""
Tests for the minimum payment calculation module.

Coverage per spec:
  - Option A winning
  - Option B winning (the normal case during 0% promo)
  - Option C winning (£5 floor)
  - Sub-£5 full-balance override
  - A default charge flipping the result from Option B to Option A
  - Zero / negative balance
  - Payoff payment calculation
  - Months elapsed / remaining
  - Days until due date (via next_due_date)
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from datetime import date
from calculator import (
    calculate_minimum_payment,
    calculate_payoff_payment,
    months_elapsed_and_remaining,
    next_due_date,
    build_projection,
)
from config import MIN_PAYMENT_FLOOR_PENCE


# ── Helpers ───────────────────────────────────────────────────────────────────

def _p(pounds: float) -> int:
    """£ → pence, rounding to nearest penny."""
    return round(pounds * 100)


# ── Minimum payment — option coverage ────────────────────────────────────────

class TestMinimumPaymentOptions:

    def test_option_b_wins_normal_0pct_promo(self):
        """
        During 0% promo, no default charges: Option A = 1% of balance.
        Option B = 2.5%. Option B is larger, so Option B must win.
        """
        result = calculate_minimum_payment(balance_pence=_p(1000.00))
        assert result.winning_option == 'B'
        # 2.5% of £1000 = £25.00, rounded up = 2500 pence
        assert result.amount_pence == _p(25.00)

    def test_option_a_wins_with_default_charge(self):
        """
        A £12 default charge on a small balance can make Option A overtake Option B.

        Balance = £200. Default charge = £12 (1200p).
        Option A = £12 + 1% of (£200 − £12) = £12 + £1.88 = £13.88  → 1388p
        Option B = 2.5% × £200 = £5.00                               → 500p
        Option A wins.
        """
        balance = _p(200.00)
        charge  = _p(12.00)
        result  = calculate_minimum_payment(balance, default_charges_pence=charge)
        assert result.winning_option == 'A'
        assert result.amount_pence == _p(13.88)

    def test_option_b_without_default_charge_at_same_balance(self):
        """
        Same balance as above but no default charge — Option B must win.
        Confirms the charge is what flips the result.
        """
        balance = _p(200.00)
        result  = calculate_minimum_payment(balance, default_charges_pence=0)
        assert result.winning_option == 'B'
        assert result.amount_pence == _p(5.00)

    def test_option_c_floor_small_balance(self):
        """
        On a very small balance where both A and B compute below £5,
        Option C (£5 floor) must win.

        Balance = £100.
        Option A = 1% of £100 = £1.00  (no charges, no interest)
        Option B = 2.5% × £100 = £2.50
        Both < £5, so Option C wins with £5.
        """
        result = calculate_minimum_payment(balance_pence=_p(100.00))
        assert result.winning_option == 'C'
        assert result.amount_pence == MIN_PAYMENT_FLOOR_PENCE  # 500p

    def test_sub_five_balance_pays_in_full(self):
        """
        Balance under £5: minimum payment is the full balance, not £5.
        """
        result = calculate_minimum_payment(balance_pence=_p(3.17))
        assert result.winning_option == 'full_balance'
        assert result.amount_pence == _p(3.17)

    def test_exactly_five_pounds_uses_option_logic(self):
        """
        Balance exactly £5.00 is not under £5, so the override does not apply.
        Option B = 2.5% × £5 = £0.125 → rounds up to 13p. Option C floor wins.
        """
        result = calculate_minimum_payment(balance_pence=_p(5.00))
        assert result.winning_option == 'C'
        assert result.amount_pence == MIN_PAYMENT_FLOOR_PENCE

    def test_zero_balance_returns_zero(self):
        result = calculate_minimum_payment(balance_pence=0)
        assert result.winning_option == 'zero'
        assert result.amount_pence == 0

    def test_negative_balance_treated_as_zero(self):
        # Overpayment — T&Cs say it's refunded; no minimum due
        result = calculate_minimum_payment(balance_pence=-_p(50.00))
        assert result.winning_option == 'zero'
        assert result.amount_pence == 0

    def test_rounding_always_up(self):
        """
        Minimum payment must never be rounded down — rounding down could mean
        underpaying and losing the 0% rate.

        Balance = £199.99.
        Option B = 2.5% × £199.99 = £4.99975 → must round UP to £5.00.
        Option C = £5.00. Same value; winner is either B or C. Key: amount = 500p.
        """
        result = calculate_minimum_payment(balance_pence=_p(199.99))
        assert result.amount_pence == MIN_PAYMENT_FLOOR_PENCE  # £5.00, rounded up

    def test_large_balance_option_b(self):
        """Balance of £5000 — Option B governs, amount = 2.5% = £125.00."""
        result = calculate_minimum_payment(balance_pence=_p(5000.00))
        assert result.winning_option == 'B'
        assert result.amount_pence == _p(125.00)

    def test_option_a_with_interest_during_standard_rate(self):
        """
        If interest is non-zero (post-promo), Option A = interest + 1% of remainder.
        Balance=£1000, interest=£20, no charges.
        Option A = £20 + 1% of £980 = £20 + £9.80 = £29.80.
        Option B = 2.5% × £1000 = £25.00.
        Option A wins.
        """
        result = calculate_minimum_payment(
            balance_pence=_p(1000.00),
            interest_pence=_p(20.00),
        )
        assert result.winning_option == 'A'
        assert result.amount_pence == _p(29.80)

    def test_default_charge_flip_from_b_to_a(self):
        """
        Explicit regression for the spec requirement: 'a default charge flipping
        the result from Option B to Option A'.

        Balance = £500. No charge → Option B = £12.50.
        Add £12 charge → Option A = £12 + 1% of £488 = £12 + £4.88 = £16.88.
        Option A (£16.88) > Option B (£12.50), so A must win.
        """
        without_charge = calculate_minimum_payment(balance_pence=_p(500.00))
        assert without_charge.winning_option == 'B'
        assert without_charge.amount_pence == _p(12.50)

        with_charge = calculate_minimum_payment(
            balance_pence=_p(500.00),
            default_charges_pence=_p(12.00),
        )
        assert with_charge.winning_option == 'A'
        assert with_charge.amount_pence == _p(16.88)


# ── Payoff payment ────────────────────────────────────────────────────────────

class TestPayoffPayment:

    def test_simple_division(self):
        # £1200 / 12 months = £100 exactly
        assert calculate_payoff_payment(_p(1200.00), 12) == _p(100.00)

    def test_rounds_up_not_down(self):
        # £1000 / 3 = £333.33... → must round UP to £333.34 (334p × 100 = 33334? no)
        # £1000 = 100000p / 3 = 33333.33p → rounded up = 33334p = £333.34
        result = calculate_payoff_payment(100000, 3)
        assert result == 33334  # £333.34

    def test_zero_months_remaining_returns_full_balance(self):
        assert calculate_payoff_payment(_p(500.00), 0) == _p(500.00)

    def test_negative_months_remaining(self):
        # Promo expired — whole balance is due
        assert calculate_payoff_payment(_p(200.00), -1) == _p(200.00)

    def test_zero_balance(self):
        assert calculate_payoff_payment(0, 12) == 0


# ── Promotional period timing ─────────────────────────────────────────────────

class TestPromoTiming:

    def test_months_elapsed_start_of_period(self):
        start = date(2024, 1, 1)
        elapsed, remaining = months_elapsed_and_remaining(start, 26, today=date(2024, 1, 15))
        assert elapsed == 0
        assert remaining == 26

    def test_months_elapsed_mid_period(self):
        start = date(2024, 1, 1)
        elapsed, remaining = months_elapsed_and_remaining(start, 26, today=date(2025, 1, 1))
        assert elapsed == 12
        assert remaining == 14

    def test_months_elapsed_after_end(self):
        start = date(2023, 1, 1)
        elapsed, remaining = months_elapsed_and_remaining(start, 26, today=date(2025, 6, 1))
        assert elapsed == 29
        assert remaining == 0  # floored at 0

    def test_remaining_floored_at_zero(self):
        start = date(2020, 1, 1)
        _, remaining = months_elapsed_and_remaining(start, 26, today=date(2025, 1, 1))
        assert remaining == 0


# ── Due date calculation ──────────────────────────────────────────────────────

class TestDueDate:

    def test_due_date_this_month(self):
        # Statement day 1, today is 5th. Statement was 1st, due = 1+25 = 26th.
        days, due = next_due_date(statement_day=1, today=date(2024, 6, 5))
        assert due == date(2024, 6, 26)
        assert days == 21

    def test_due_date_next_month_when_past(self):
        # Statement day 1, today is 28th. Due for this month was 26th (past).
        # Next statement: 1 July, due = 26 July.
        days, due = next_due_date(statement_day=1, today=date(2024, 6, 28))
        assert due == date(2024, 7, 26)
        assert days == 28

    def test_statement_day_clamped_for_short_month(self):
        # Statement day 31, but February has 28 days (2025 is not a leap year).
        # Statement date → 28 Feb, due = 28 Feb + 25 = 25 Mar.
        days, due = next_due_date(statement_day=31, today=date(2025, 2, 1))
        assert due == date(2025, 3, 25)


# ── Projection ────────────────────────────────────────────────────────────────

class TestProjection:

    def test_projection_zero_balance(self):
        rows, min_end, payoff_end = build_projection(0, 12)
        assert rows == []
        assert min_end == 0
        assert payoff_end == 0

    def test_projection_zero_months(self):
        rows, min_end, payoff_end = build_projection(_p(1000.00), 0)
        assert rows == []

    def test_projection_reduces_to_zero_on_payoff(self):
        # £1200 over 12 months paying £100/month should clear to zero
        rows, min_end, payoff_end = build_projection(_p(1200.00), 12)
        assert payoff_end == 0

    def test_projection_min_only_leaves_residual(self):
        # 2.5%/month on £2000 never reaches zero in 5 months
        rows, min_end, _ = build_projection(_p(2000.00), 5)
        assert min_end > 0
        assert len(rows) == 5

    def test_projection_length_matches_months(self):
        rows, _, _ = build_projection(_p(1000.00), 10)
        assert len(rows) == 10
