"""
SQLite persistence layer. All money stored as INTEGER pence.
Dates stored as TEXT in ISO-8601 format (YYYY-MM-DD).
"""
import sqlite3
import os
from datetime import date

DB_PATH = os.environ.get('MS_CALC_DB', os.path.join(os.path.dirname(__file__), 'card.db'))


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL')  # safe for concurrent reads
    conn.execute('PRAGMA foreign_keys=ON')
    return conn


def init_db():
    with get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS card_config (
                id                  INTEGER PRIMARY KEY CHECK (id = 1),
                promo_start_date    TEXT    NOT NULL,
                promo_months        INTEGER NOT NULL DEFAULT 26,
                statement_day       INTEGER NOT NULL DEFAULT 1,
                credit_limit_pence  INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS entries (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                entry_type      TEXT    NOT NULL CHECK (entry_type IN ('purchase','payment','charge')),
                description     TEXT    NOT NULL DEFAULT '',
                amount_pence    INTEGER NOT NULL,
                entry_date      TEXT    NOT NULL,
                non_sterling    INTEGER NOT NULL DEFAULT 0,
                charge_subtype  TEXT,
                created_at      TEXT    NOT NULL DEFAULT (datetime('now'))
            );
        """)


# ── card_config ──────────────────────────────────────────────────────────────

def get_card_config():
    with get_db() as conn:
        row = conn.execute('SELECT * FROM card_config WHERE id = 1').fetchone()
        return dict(row) if row else None


def save_card_config(promo_start_date, promo_months, statement_day, credit_limit_pence):
    with get_db() as conn:
        conn.execute("""
            INSERT INTO card_config (id, promo_start_date, promo_months, statement_day, credit_limit_pence)
            VALUES (1, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                promo_start_date   = excluded.promo_start_date,
                promo_months       = excluded.promo_months,
                statement_day      = excluded.statement_day,
                credit_limit_pence = excluded.credit_limit_pence
        """, (promo_start_date, promo_months, statement_day, credit_limit_pence))


# ── entries ──────────────────────────────────────────────────────────────────

def get_entries():
    """All entries in chronological order, oldest first."""
    with get_db() as conn:
        rows = conn.execute(
            'SELECT * FROM entries ORDER BY entry_date ASC, id ASC'
        ).fetchall()
        return [dict(r) for r in rows]


def get_entry(entry_id):
    with get_db() as conn:
        row = conn.execute('SELECT * FROM entries WHERE id = ?', (entry_id,)).fetchone()
        return dict(row) if row else None


def add_entry(entry_type, description, amount_pence, entry_date, non_sterling=False, charge_subtype=None):
    with get_db() as conn:
        conn.execute("""
            INSERT INTO entries (entry_type, description, amount_pence, entry_date, non_sterling, charge_subtype)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (entry_type, description, amount_pence, entry_date, 1 if non_sterling else 0, charge_subtype))


def update_entry(entry_id, entry_type, description, amount_pence, entry_date, non_sterling=False, charge_subtype=None):
    with get_db() as conn:
        conn.execute("""
            UPDATE entries
            SET entry_type = ?, description = ?, amount_pence = ?,
                entry_date = ?, non_sterling = ?, charge_subtype = ?
            WHERE id = ?
        """, (entry_type, description, amount_pence, entry_date, 1 if non_sterling else 0, charge_subtype, entry_id))


def delete_entry(entry_id):
    with get_db() as conn:
        conn.execute('DELETE FROM entries WHERE id = ?', (entry_id,))


def get_ledger_with_running_balance():
    """
    Returns entries with a running balance column (pence).
    Purchases and charges are positive (add to what you owe).
    Payments are negative (reduce what you owe).
    """
    entries = get_entries()
    running = 0
    result = []
    for e in entries:
        if e['entry_type'] == 'payment':
            running -= e['amount_pence']
        else:
            running += e['amount_pence']
        result.append({**e, 'running_balance_pence': running})
    return result


def get_balance_summary():
    """
    Returns:
      total_balance_pence      — outstanding balance
      total_purchases_pence
      total_charges_pence
      total_payments_pence
      total_default_charges_pence  — sum of charge-type entries (for Option A calc)
    """
    entries = get_entries()
    purchases = sum(e['amount_pence'] for e in entries if e['entry_type'] == 'purchase')
    charges   = sum(e['amount_pence'] for e in entries if e['entry_type'] == 'charge')
    payments  = sum(e['amount_pence'] for e in entries if e['entry_type'] == 'payment')
    balance   = purchases + charges - payments

    # Default charges outstanding: all charges still in the balance.
    # We treat all recorded charges as relevant to the current period's Option A
    # calculation (we're not modelling statement cycles). This errs on the safe
    # side — a slightly higher minimum is better than accidentally underpaying.
    default_charges = charges

    return {
        'balance_pence':          max(0, balance),
        'purchases_pence':        purchases,
        'charges_pence':          charges,
        'payments_pence':         payments,
        'default_charges_pence':  default_charges,
        'overpayment':            balance < 0,
    }
