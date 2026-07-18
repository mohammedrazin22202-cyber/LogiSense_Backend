"""
fix_eta_dates.py — Rebase all shipment dates to today
======================================================
Run:  python backend/fix_eta_dates.py

Problem:
    Shipment ETAs were hardcoded at seeding time and are now 1400+ hours
    in the past, making every order look overdue in the customer portal.

What this script does:
    • In Transit  → dispatch set 2-18 hrs ago, ETA set 14 hrs-3 days ahead
    • Pending     → dispatch set now,           ETA set 14 hrs-3 days ahead
    • Delivered   → dispatch + actual_delivery shifted to 1-7 days ago
                    (keeps the "delivered" story believable and recent)
    • Clears sla_breached flag and resets delay alerts for In Transit orders
    • Prints a full before/after summary

Nothing is deleted — only datetime columns are updated.
"""

import os
import sys
import sqlite3
import random
from datetime import datetime, timedelta

# ── Locate fleet.db ────────────────────────────────────────────────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH    = os.path.join(SCRIPT_DIR, '..', 'data', 'fleet.db')
DB_PATH    = os.path.normpath(DB_PATH)

if not os.path.exists(DB_PATH):
    print(f"[ERROR] Database not found at: {DB_PATH}")
    sys.exit(1)

# ── Helpers ────────────────────────────────────────────────────────────────────
def rand_minutes(lo_hrs: float, hi_hrs: float) -> int:
    """Return a random number of minutes in the [lo_hrs, hi_hrs] range."""
    return random.randint(int(lo_hrs * 60), int(hi_hrs * 60))

def fmt(dt: datetime) -> str:
    """Format datetime as ISO string (no microseconds)."""
    return dt.strftime('%Y-%m-%dT%H:%M:%S')

# ── Main ───────────────────────────────────────────────────────────────────────
def fix_dates():
    now = datetime.now()
    print(f"\n{'='*55}")
    print(f"  Fleet Command — ETA Date Fixer")
    print(f"  Run time : {now.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Database : {DB_PATH}")
    print(f"{'='*55}\n")

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur  = conn.cursor()

    # Fetch all orders
    cur.execute("""
        SELECT id, order_status,
               dispatch_datetime, expected_delivery_datetime, actual_delivery_datetime,
               estimated_transit_hours
        FROM orders
    """)
    orders = cur.fetchall()

    in_transit_ids = []
    counts = {'In Transit': 0, 'Pending': 0, 'Created': 0, 'Delivered': 0, 'Other': 0}

    print(f"  Found {len(orders)} orders — updating datetimes...\n")

    for order in orders:
        oid    = order['id']
        status = (order['order_status'] or '').strip()
        transit_hrs = float(order['estimated_transit_hours'] or 24)

        # ── In Transit ──────────────────────────────────────────────────────
        if status == 'In Transit':
            dispatch_ago_min  = rand_minutes(2, 18)          # dispatched 2–18 hrs ago
            eta_ahead_min     = rand_minutes(14, 72)         # ETA 14 hrs–3 days ahead

            new_dispatch      = now - timedelta(minutes=dispatch_ago_min)
            new_expected      = now + timedelta(minutes=eta_ahead_min)

            cur.execute("""
                UPDATE orders
                SET dispatch_datetime          = ?,
                    expected_delivery_datetime = ?,
                    actual_delivery_datetime   = NULL,
                    sla_breached               = 0,
                    sla_deadline               = ?
                WHERE id = ?
            """, (fmt(new_dispatch), fmt(new_expected), fmt(new_expected), oid))

            in_transit_ids.append(oid)
            counts['In Transit'] += 1
            print(f"  [{status:10}] {oid}  dispatch={fmt(new_dispatch)}  eta={fmt(new_expected)}")

        # ── Pending / Created ───────────────────────────────────────────────
        elif status in ('Pending', 'Created'):
            eta_ahead_min = rand_minutes(14, 72)
            new_dispatch  = now
            new_expected  = now + timedelta(minutes=eta_ahead_min)

            cur.execute("""
                UPDATE orders
                SET dispatch_datetime          = ?,
                    expected_delivery_datetime = ?,
                    actual_delivery_datetime   = NULL,
                    sla_breached               = 0,
                    sla_deadline               = ?
                WHERE id = ?
            """, (fmt(new_dispatch), fmt(new_expected), fmt(new_expected), oid))

            counts[status] += 1
            print(f"  [{status:10}] {oid}  dispatch={fmt(new_dispatch)}  eta={fmt(new_expected)}")

        # ── Delivered ───────────────────────────────────────────────────────
        elif status == 'Delivered':
            # Make it look like it was delivered 1–7 days ago
            delivery_ago_min  = rand_minutes(24, 168)        # delivered 1–7 days ago
            dispatch_ago_min  = delivery_ago_min + int(transit_hrs * 60)

            new_actual        = now - timedelta(minutes=delivery_ago_min)
            new_dispatch      = now - timedelta(minutes=dispatch_ago_min)
            # Expected = dispatch + transit_hours (was on time for delivered ones)
            new_expected      = new_dispatch + timedelta(hours=transit_hrs)

            cur.execute("""
                UPDATE orders
                SET dispatch_datetime          = ?,
                    expected_delivery_datetime = ?,
                    actual_delivery_datetime   = ?
                WHERE id = ?
            """, (fmt(new_dispatch), fmt(new_expected), fmt(new_actual), oid))

            counts['Delivered'] += 1
            print(f"  [Delivered ] {oid}  delivered={fmt(new_actual)}")

        else:
            counts['Other'] += 1
            print(f"  [{'?' + status[:8]:10}] {oid}  — skipped (unknown status)")

    # ── Clear delay alerts for In Transit orders ────────────────────────────
    if in_transit_ids:
        placeholders = ','.join('?' * len(in_transit_ids))
        cur.execute(f"""
            UPDATE alerts
            SET delay_minutes = 0
            WHERE order_id IN ({placeholders})
              AND alert_type IN ('Delay', 'ETA Breach', 'Late Delivery')
        """, in_transit_ids)
        alert_rows = cur.rowcount
        print(f"\n  Cleared {alert_rows} delay alert(s) for In Transit orders.")

    conn.commit()
    conn.close()

    print(f"\n{'='*55}")
    print(f"  Summary")
    print(f"{'='*55}")
    for status, count in counts.items():
        if count:
            print(f"  {status:12} : {count} order(s) updated")
    print(f"\n  [OK] All dates rebased to today. Run your app now!\n")

if __name__ == '__main__':
    fix_dates()
