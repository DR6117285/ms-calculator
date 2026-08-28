"""
Flask application for M&S Bank credit card 0% promotion calculator.
"""
import os
from datetime import date
from decimal import Decimal, InvalidOperation

from flask import Flask, flash, redirect, render_template, request, url_for

import db
from calculator import build_dashboard, build_projection, calculate_minimum_payment
from config import (
    DEFAULT_CHARGE_SUBTYPES,
    DEFAULT_PROMO_MONTHS,
    DEFAULT_STATEMENT_DAY,
    NON_STERLING_SURCHARGE_PCT,
)

app = Flask(__name__)
app.secret_key = os.environ.get('MS_CALC_SECRET', 'change-me-in-production')

db.init_db()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_pounds(value: str) -> int | None:
    """Parse a pound sterling string like '123.45' and return integer pence."""
    try:
        d = Decimal(value.strip().lstrip('£'))
        pence = int((d * 100).to_integral_value())
        if pence < 0:
            return None
        return pence
    except (InvalidOperation, ValueError):
        return None


def _fmt(pence: int) -> str:
    """Format integer pence as £ string for templates."""
    return f'£{abs(pence) / 100:.2f}'


# Make _fmt available in all templates
app.jinja_env.globals['fmt'] = _fmt
app.jinja_env.globals['today'] = date.today


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    config = db.get_card_config()
    if not config:
        flash('Set up your card details first.', 'warning')
        return redirect(url_for('setup'))

    summary  = db.get_balance_summary()
    dashboard = build_dashboard(config, summary)
    ledger   = db.get_ledger_with_running_balance()

    min_result = calculate_minimum_payment(
        summary['balance_pence'],
        summary['default_charges_pence'],
    )

    return render_template(
        'index.html',
        config=config,
        dashboard=dashboard,
        ledger=ledger,
        min_result=min_result,
        charge_subtypes=DEFAULT_CHARGE_SUBTYPES,
    )


@app.route('/setup', methods=['GET', 'POST'])
def setup():
    config = db.get_card_config()
    if request.method == 'POST':
        promo_start = request.form.get('promo_start_date', '').strip()
        try:
            date.fromisoformat(promo_start)
        except ValueError:
            flash('Invalid promotional start date.', 'error')
            return render_template('setup.html', config=config)

        try:
            promo_months = int(request.form.get('promo_months', DEFAULT_PROMO_MONTHS))
            statement_day = int(request.form.get('statement_day', DEFAULT_STATEMENT_DAY))
            if not (1 <= statement_day <= 28):
                raise ValueError
        except ValueError:
            flash('Invalid months or statement day (must be 1–28).', 'error')
            return render_template('setup.html', config=config)

        limit_str = request.form.get('credit_limit_pence', '0')
        credit_limit = _parse_pounds(limit_str)
        if credit_limit is None:
            flash('Invalid credit limit.', 'error')
            return render_template('setup.html', config=config)

        db.save_card_config(promo_start, promo_months, statement_day, credit_limit)
        flash('Card settings saved.', 'success')
        return redirect(url_for('index'))

    return render_template('setup.html', config=config,
                           default_promo_months=DEFAULT_PROMO_MONTHS,
                           default_statement_day=DEFAULT_STATEMENT_DAY)


@app.route('/entry/add', methods=['POST'])
def add_entry():
    entry_type = request.form.get('entry_type', '')
    if entry_type not in ('purchase', 'payment', 'charge'):
        flash('Unknown entry type.', 'error')
        return redirect(url_for('index'))

    description  = request.form.get('description', '').strip()
    date_str     = request.form.get('entry_date', '').strip()
    amount_str   = request.form.get('amount', '').strip()
    non_sterling = request.form.get('non_sterling') == '1'
    charge_sub   = request.form.get('charge_subtype', '').strip() or None

    try:
        date.fromisoformat(date_str)
    except ValueError:
        flash('Invalid date.', 'error')
        return redirect(url_for('index'))

    amount_pence = _parse_pounds(amount_str)
    if amount_pence is None or amount_pence == 0:
        flash('Invalid amount.', 'error')
        return redirect(url_for('index'))

    if entry_type == 'purchase' and non_sterling:
        # Add 2.99% non-sterling surcharge on top of the entered sterling amount
        surcharge = int((Decimal(amount_pence) * NON_STERLING_SURCHARGE_PCT).to_integral_value())
        amount_pence += surcharge

    if entry_type == 'charge':
        if charge_sub not in DEFAULT_CHARGE_SUBTYPES:
            flash('Invalid charge type.', 'error')
            return redirect(url_for('index'))
        description = DEFAULT_CHARGE_SUBTYPES[charge_sub][0]

    db.add_entry(entry_type, description, amount_pence, date_str, non_sterling, charge_sub)
    flash(f'{entry_type.capitalize()} added.', 'success')
    return redirect(url_for('index'))


@app.route('/entry/<int:entry_id>/edit', methods=['GET', 'POST'])
def edit_entry(entry_id):
    entry = db.get_entry(entry_id)
    if not entry:
        flash('Entry not found.', 'error')
        return redirect(url_for('index'))

    if request.method == 'POST':
        entry_type   = request.form.get('entry_type', entry['entry_type'])
        description  = request.form.get('description', '').strip()
        date_str     = request.form.get('entry_date', '').strip()
        amount_str   = request.form.get('amount', '').strip()
        non_sterling = request.form.get('non_sterling') == '1'
        charge_sub   = request.form.get('charge_subtype', '').strip() or None

        try:
            date.fromisoformat(date_str)
        except ValueError:
            flash('Invalid date.', 'error')
            return render_template('edit.html', entry=entry, charge_subtypes=DEFAULT_CHARGE_SUBTYPES)

        amount_pence = _parse_pounds(amount_str)
        if amount_pence is None or amount_pence == 0:
            flash('Invalid amount.', 'error')
            return render_template('edit.html', entry=entry, charge_subtypes=DEFAULT_CHARGE_SUBTYPES)

        db.update_entry(entry_id, entry_type, description, amount_pence, date_str, non_sterling, charge_sub)
        flash('Entry updated.', 'success')
        return redirect(url_for('index'))

    return render_template('edit.html', entry=entry, charge_subtypes=DEFAULT_CHARGE_SUBTYPES)


@app.route('/entry/<int:entry_id>/delete', methods=['POST'])
def delete_entry(entry_id):
    entry = db.get_entry(entry_id)
    if not entry:
        flash('Entry not found.', 'error')
    else:
        db.delete_entry(entry_id)
        flash('Entry deleted.', 'success')
    return redirect(url_for('index'))


@app.route('/projection')
def projection():
    config = db.get_card_config()
    if not config:
        flash('Set up your card details first.', 'warning')
        return redirect(url_for('setup'))

    summary   = db.get_balance_summary()
    dashboard = build_dashboard(config, summary)
    rows, min_end, payoff_end = build_projection(
        summary['balance_pence'],
        dashboard.months_remaining,
        summary['default_charges_pence'],
    )
    return render_template(
        'projection.html',
        dashboard=dashboard,
        rows=rows,
        min_end=min_end,
        payoff_end=payoff_end,
    )


if __name__ == '__main__':
    # Bind to the Tailscale interface only. Override via env if needed.
    host = os.environ.get('MS_CALC_HOST', '127.0.0.1')
    port = int(os.environ.get('MS_CALC_PORT', '5000'))
    app.run(host=host, port=port, debug=False)
