"""
Fleet Command - SQLite → MongoDB Sync
======================================
Copies ALL data from fleet.db (SQLite) into MongoDB fleet_command database.
Run this once to populate MongoDB, then Compass will show everything.

Usage:
    cd fleet-command
    python backend/sync_to_mongo.py
"""

import sys, os
sys.path.insert(0, os.path.dirname(__file__))

import sqlite3
import json
import logging
from datetime import datetime

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

# ── Config ─────────────────────────────────────────────────────────────────────
MONGO_URI   = os.environ.get("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB    = os.environ.get("MONGO_DB",  "fleet_command")
SQLITE_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'fleet.db')

# Tables to sync — order matters for readability in Compass
TABLES = [
    "vehicles",
    "orders",
    "drivers",
    "warehouses",
    "routes",
    "trips",
    "trip_events",
    "vehicle_positions",
    "alerts",
    "temperature_logs",
    "order_documents",
    "clients",
    "freight_rate_cards",
    "geofences",
    "geofence_events",
    "fuel_logs",
    "maintenance_records",
    "maintenance_schedule",
    "sla_records",
    "performance_kpis",
    "notifications",
    "incidents",
    "insurance_policies",
    "invoices",
    "contracts",
    "yard_slots",
    "gate_logs",
    "dock_schedules",
    "containers",
    "hub_transfers",
    "cargo_inspections",
    "carrier_partners",
    "staff",
    "consolidation_batches",
    "network_analysis",
    "security_events",
    "system_logs",
    "dispatches",
    "load_plans",
    "load_plan_items",
    "warehouse_zones",
    "inventory",
]

def get_sqlite():
    if not os.path.exists(SQLITE_PATH):
        logger.error("fleet.db not found at: %s", SQLITE_PATH)
        logger.error("Run the app first (python backend/server.py) to create the database.")
        sys.exit(1)
    conn = sqlite3.connect(SQLITE_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def get_mongo():
    try:
        from pymongo import MongoClient
        client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
        client.admin.command("ping")
        logger.info("MongoDB connected: %s", MONGO_URI)
        return client[MONGO_DB]
    except Exception as e:
        logger.error("Cannot connect to MongoDB: %s", e)
        logger.error("Make sure MongoDB is running:  mongod")
        sys.exit(1)

def sqlite_to_dict(row):
    """Convert sqlite3.Row to a plain dict, fixing types for MongoDB."""
    d = dict(row)
    # Rename 'id' column to '_id' so MongoDB uses it as the document ID
    if 'id' in d:
        d['_id'] = d.pop('id')
    # Convert integer booleans to real booleans
    for k, v in d.items():
        if k in ('acknowledged', 'is_hub', 'is_return', 'sla_breached',
                 'requires_cold_chain', 'is_active', 'is_optimized',
                 'is_anomaly', 'is_insured', 'is_read', 'is_occupied',
                 'temperature_controlled'):
            d[k] = bool(v) if v is not None else False
    return d

def sync_table(sqlite_conn, mongo_db, table_name):
    """Copy one SQLite table → one MongoDB collection."""
    try:
        cursor = sqlite_conn.execute(f"SELECT * FROM {table_name}")
        rows = cursor.fetchall()
    except sqlite3.OperationalError:
        logger.warning("  [SKIP] Table not found: %s", table_name)
        return 0

    if not rows:
        logger.info("  [EMPTY] %s — no rows", table_name)
        return 0

    docs = [sqlite_to_dict(r) for r in rows]
    coll = mongo_db[table_name]

    # Wipe existing data in this collection before re-syncing
    coll.delete_many({})

    # Insert — handle duplicate _id gracefully
    try:
        result = coll.insert_many(docs, ordered=False)
        count = len(result.inserted_ids)
    except Exception as e:
        # Partial insert — count what got in
        count = mongo_db[table_name].count_documents({})
        logger.warning("  [WARN] %s partial insert: %s", table_name, e)

    logger.info("  [OK] %-30s  %d documents", table_name, count)
    return count

def main():
    print("\nFleet Command — SQLite → MongoDB Sync")
    print("=" * 45)
    print(f"Source : {SQLITE_PATH}")
    print(f"Target : {MONGO_URI} / {MONGO_DB}")
    print("=" * 45)

    sqlite_conn = get_sqlite()
    mongo_db    = get_mongo()

    total_docs  = 0
    total_colls = 0

    for table in TABLES:
        n = sync_table(sqlite_conn, mongo_db, table)
        if n > 0:
            total_docs  += n
            total_colls += 1

    sqlite_conn.close()

    print("\n" + "=" * 45)
    print(f"  Sync complete!")
    print(f"  Collections synced : {total_colls}")
    print(f"  Total documents    : {total_docs}")
    print(f"  Timestamp          : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 45)
    print("\n  Open MongoDB Compass and connect to:")
    print(f"  {MONGO_URI}")
    print(f"  Database: {MONGO_DB}\n")

if __name__ == "__main__":
    main()
