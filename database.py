"""
Fleet Command - Hybrid Database Layer
======================================
SQLite  → handles all existing server.py queries (conn.execute / SQL)
MongoDB → handles registry, analytics, new collections

server.py calls:
    get_db()     → returns SQLite connection  (unchanged, 328 uses still work)
    get_mongo_db()→ returns MongoDB database  (new features)
    init_db()    → initialises both
    log_event()  → writes to SQLite system_logs
"""
import sqlite3
import os
import json
import logging

logger = logging.getLogger(__name__)

# ── SQLite path ───────────────────────────────────────────────────────────────
DB_PATH = os.path.join(os.path.dirname(__file__), 'data', 'fleet.db')

# ── MongoDB settings ──────────────────────────────────────────────────────────
MONGO_URI = os.environ.get("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB_NAME = os.environ.get("MONGO_DB", "fleet_command")
_mongo_client = None
_mongo_db = None


# ══════════════════════════════════════════════════════════════════════════════
#  SQLITE  (unchanged — all existing server.py code works as-is)
# ══════════════════════════════════════════════════════════════════════════════

def get_db():
    """Return a SQLite connection. All existing conn.execute() calls use this."""
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """Initialise SQLite schema + connect to MongoDB."""
    _init_sqlite()
    _init_mongo()


def _init_sqlite():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = get_db()
    c = conn.cursor()
    c.executescript("""
    CREATE TABLE IF NOT EXISTS vehicles (
        id TEXT PRIMARY KEY,
        vehicle_type TEXT NOT NULL,
        vehicle_number TEXT,
        plate_number TEXT,
        driver_name TEXT,
        driver_contact TEXT,
        status TEXT DEFAULT 'idle',
        current_lat REAL,
        current_lng REAL,
        current_speed REAL DEFAULT 0,
        heading REAL DEFAULT 0,
        current_order_id TEXT,
        assigned_route TEXT,
        last_updated TEXT,
        capacity_tons REAL,
        capacity_cbm REAL,
        insurance_expiry TEXT,
        maintenance_due TEXT,
        fuel_type TEXT DEFAULT 'Diesel',
        assigned_driver_id TEXT,
        fuel_level_pct REAL DEFAULT 100,
        odometer_km REAL DEFAULT 0,
        loaded_distance_km REAL DEFAULT 0,
        total_distance_km REAL DEFAULT 0,
        engine_temp_c REAL,
        engine_health TEXT DEFAULT 'Good',
        permit_expiry TEXT,
        fitness_expiry TEXT,
        pollution_expiry TEXT,
        yard_slot TEXT,
        transport_mode TEXT DEFAULT 'road',
        created_at TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS orders (
        id TEXT PRIMARY KEY,
        customer_name TEXT,
        customer_company TEXT,
        customer_contact TEXT,
        pickup_address TEXT,
        delivery_address TEXT,
        source_city TEXT,
        source_state TEXT,
        source_pincode TEXT,
        destination_city TEXT,
        destination_state TEXT,
        destination_pincode TEXT,
        goods_type TEXT,
        goods_category TEXT,
        quantity REAL,
        unit TEXT,
        vehicle_id TEXT,
        vehicle_number TEXT,
        dispatch_datetime TEXT,
        expected_delivery_datetime TEXT,
        actual_delivery_datetime TEXT,
        distance_km REAL,
        estimated_transit_hours REAL,
        order_status TEXT,
        transport_cost_inr REAL,
        lifecycle_stage TEXT DEFAULT 'Created',
        pod_type TEXT,
        pod_reference TEXT,
        pod_collected_at TEXT,
        pod_status TEXT DEFAULT 'Pending',
        priority_tier TEXT DEFAULT 'Economy',
        weight_kg REAL,
        length_cm REAL,
        width_cm REAL,
        height_cm REAL,
        volumetric_weight_kg REAL,
        sla_deadline TEXT,
        sla_breached INTEGER DEFAULT 0,
        fuel_cost_inr REAL DEFAULT 0,
        toll_cost_inr REAL DEFAULT 0,
        maintenance_cost_inr REAL DEFAULT 0,
        other_cost_inr REAL DEFAULT 0,
        total_cost_inr REAL DEFAULT 0,
        client_id TEXT,
        delivery_window_start TEXT,
        delivery_window_end TEXT,
        is_return INTEGER DEFAULT 0,
        parent_order_id TEXT,
        consolidated_batch_id TEXT,
        container_id TEXT,
        insurance_policy_id TEXT,
        requires_cold_chain INTEGER DEFAULT 0,
        packaging_type TEXT,
        co2_kg REAL DEFAULT 0,
        dispatcher_id TEXT,
        hub_id TEXT,
        FOREIGN KEY (vehicle_id) REFERENCES vehicles(id)
    );

    CREATE TABLE IF NOT EXISTS drivers (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        contact TEXT,
        license_number TEXT,
        license_expiry TEXT,
        license_type TEXT,
        availability TEXT DEFAULT 'Available',
        current_vehicle_id TEXT,
        working_hours_today REAL DEFAULT 0,
        total_trips INTEGER DEFAULT 0,
        rating REAL DEFAULT 5.0,
        rating_count INTEGER DEFAULT 0,
        joined_date TEXT,
        address TEXT,
        emergency_contact TEXT,
        created_at TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS warehouses (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        location TEXT,
        city TEXT,
        lat REAL,
        lng REAL,
        total_capacity_cbm REAL,
        used_capacity_cbm REAL DEFAULT 0,
        manager_name TEXT,
        contact TEXT,
        is_hub INTEGER DEFAULT 0,
        created_at TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS vehicle_positions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        vehicle_id TEXT NOT NULL,
        lat REAL NOT NULL,
        lng REAL NOT NULL,
        speed REAL DEFAULT 0,
        heading REAL DEFAULT 0,
        status TEXT DEFAULT 'moving',
        order_id TEXT,
        fuel_level_pct REAL,
        engine_temp_c REAL,
        recorded_at TEXT DEFAULT (datetime('now')),
        FOREIGN KEY (vehicle_id) REFERENCES vehicles(id)
    );

    CREATE TABLE IF NOT EXISTS alerts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_id TEXT,
        vehicle_id TEXT,
        alert_type TEXT NOT NULL,
        alert_reason TEXT,
        severity TEXT DEFAULT 'Medium',
        delay_minutes INTEGER DEFAULT 0,
        acknowledged INTEGER DEFAULT 0,
        incident_type TEXT,
        resolution_notes TEXT,
        resolved_at TEXT,
        created_at TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS temperature_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_id TEXT NOT NULL,
        vehicle_id TEXT,
        temp_at_dispatch REAL,
        temp_during_transit REAL,
        temp_at_delivery REAL,
        required_range TEXT,
        condition_status TEXT,
        recorded_at TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS order_documents (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_id TEXT NOT NULL,
        invoice_status TEXT,
        eway_bill_status TEXT,
        other_documents TEXT,
        document_status TEXT,
        customs_declaration TEXT,
        hs_code TEXT,
        duties_inr REAL DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS routes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        source_city TEXT,
        destination_city TEXT,
        distance_km REAL,
        estimated_hours REAL,
        toll_cost_inr REAL DEFAULT 0,
        traffic_factor REAL DEFAULT 1.0,
        via_cities TEXT,
        transport_mode TEXT DEFAULT 'road',
        is_optimized INTEGER DEFAULT 0,
        created_at TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS trips (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        vehicle_id TEXT NOT NULL,
        order_id TEXT,
        route_id INTEGER,
        trip_status TEXT DEFAULT 'Planned',
        planned_start TEXT,
        actual_start TEXT,
        hub_arrival TEXT,
        completed_at TEXT,
        distance_km REAL DEFAULT 0,
        fuel_consumed_liters REAL DEFAULT 0,
        notes TEXT,
        created_at TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS trip_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        trip_id INTEGER NOT NULL,
        event_type TEXT NOT NULL,
        event_time TEXT DEFAULT (datetime('now')),
        lat REAL,
        lng REAL,
        notes TEXT
    );

    CREATE TABLE IF NOT EXISTS clients (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        company TEXT,
        email TEXT,
        phone TEXT,
        address TEXT,
        city TEXT,
        gstin TEXT,
        credit_limit_inr REAL DEFAULT 500000,
        payment_terms_days INTEGER DEFAULT 30,
        account_status TEXT DEFAULT 'Active',
        created_at TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS freight_rate_cards (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        client_id TEXT,
        vehicle_type TEXT,
        base_rate_per_km REAL NOT NULL,
        fuel_surcharge_pct REAL DEFAULT 0,
        tax_pct REAL DEFAULT 18,
        min_charge_inr REAL DEFAULT 0,
        priority_tier TEXT DEFAULT 'Economy',
        effective_from TEXT,
        effective_to TEXT,
        created_at TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS geofences (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        zone_type TEXT DEFAULT 'circle',
        center_lat REAL,
        center_lng REAL,
        radius_km REAL,
        polygon_coords TEXT,
        trigger_on TEXT DEFAULT 'enter',
        action TEXT,
        is_active INTEGER DEFAULT 1,
        created_at TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS fuel_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        vehicle_id TEXT NOT NULL,
        trip_id INTEGER,
        liters_consumed REAL,
        cost_inr REAL,
        odometer_km REAL,
        fuel_efficiency_kmpl REAL,
        is_anomaly INTEGER DEFAULT 0,
        anomaly_reason TEXT,
        logged_at TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS maintenance_records (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        vehicle_id TEXT NOT NULL,
        maintenance_type TEXT,
        description TEXT,
        cost_inr REAL DEFAULT 0,
        vendor TEXT,
        performed_at TEXT,
        next_due_at TEXT,
        status TEXT DEFAULT 'Completed',
        created_at TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS sla_records (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_id TEXT NOT NULL,
        sla_type TEXT,
        target_datetime TEXT,
        actual_datetime TEXT,
        is_breached INTEGER DEFAULT 0,
        breach_minutes INTEGER DEFAULT 0,
        notes TEXT,
        created_at TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS performance_kpis (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        period_start TEXT NOT NULL,
        period_end TEXT NOT NULL,
        period_type TEXT DEFAULT 'daily',
        total_deliveries INTEGER DEFAULT 0,
        on_time_deliveries INTEGER DEFAULT 0,
        on_time_rate REAL DEFAULT 0,
        avg_delivery_hours REAL DEFAULT 0,
        total_revenue_inr REAL DEFAULT 0,
        total_distance_km REAL DEFAULT 0,
        fleet_utilization_pct REAL DEFAULT 0,
        sla_breach_count INTEGER DEFAULT 0,
        incident_count INTEGER DEFAULT 0,
        computed_at TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS notifications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        recipient_type TEXT,
        recipient_id TEXT,
        channel TEXT DEFAULT 'app',
        subject TEXT,
        message TEXT,
        order_id TEXT,
        vehicle_id TEXT,
        is_read INTEGER DEFAULT 0,
        sent_at TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS incidents (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_id TEXT,
        vehicle_id TEXT,
        incident_type TEXT,
        description TEXT,
        location TEXT,
        severity TEXT DEFAULT 'Medium',
        damage_value_inr REAL DEFAULT 0,
        is_insured INTEGER DEFAULT 0,
        claim_status TEXT DEFAULT 'Not Filed',
        reported_at TEXT DEFAULT (datetime('now')),
        resolved_at TEXT
    );

    CREATE TABLE IF NOT EXISTS insurance_policies (
        id TEXT PRIMARY KEY,
        policy_type TEXT,
        provider TEXT,
        coverage_inr REAL,
        premium_inr REAL,
        start_date TEXT,
        end_date TEXT,
        vehicle_id TEXT,
        order_id TEXT,
        is_active INTEGER DEFAULT 1,
        created_at TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS invoices (
        id TEXT PRIMARY KEY,
        client_id TEXT,
        order_id TEXT,
        invoice_date TEXT,
        due_date TEXT,
        subtotal_inr REAL DEFAULT 0,
        tax_inr REAL DEFAULT 0,
        total_inr REAL DEFAULT 0,
        status TEXT DEFAULT 'Draft',
        paid_at TEXT,
        created_at TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS contracts (
        id TEXT PRIMARY KEY,
        client_id TEXT,
        contract_type TEXT,
        start_date TEXT,
        end_date TEXT,
        capacity_commitment TEXT,
        rate_terms TEXT,
        sla_terms TEXT,
        status TEXT DEFAULT 'Active',
        created_at TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS demand_forecasts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        period TEXT,
        source_city TEXT,
        destination_city TEXT,
        predicted_shipments INTEGER,
        actual_shipments INTEGER,
        confidence_pct REAL,
        model_version TEXT,
        generated_at TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS security_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        vehicle_id TEXT,
        order_id TEXT,
        event_type TEXT,
        description TEXT,
        lat REAL,
        lng REAL,
        severity TEXT DEFAULT 'Medium',
        is_resolved INTEGER DEFAULT 0,
        detected_at TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS system_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        log_type TEXT NOT NULL,
        entity_type TEXT,
        entity_id TEXT,
        message TEXT NOT NULL,
        metadata TEXT,
        created_at TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS consolidation_batches (
        id TEXT PRIMARY KEY,
        destination_city TEXT,
        vehicle_id TEXT,
        status TEXT DEFAULT 'Open',
        total_weight_kg REAL DEFAULT 0,
        total_volume_cbm REAL DEFAULT 0,
        created_at TEXT DEFAULT (datetime('now')),
        dispatched_at TEXT
    );

    CREATE TABLE IF NOT EXISTS yard_slots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        warehouse_id TEXT,
        slot_code TEXT NOT NULL,
        slot_type TEXT DEFAULT 'parking',
        is_occupied INTEGER DEFAULT 0,
        vehicle_id TEXT,
        occupied_since TEXT
    );

    CREATE TABLE IF NOT EXISTS gate_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        vehicle_id TEXT,
        warehouse_id TEXT,
        event_type TEXT,
        driver_name TEXT,
        order_ref TEXT,
        logged_at TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS dock_schedules (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        warehouse_id TEXT,
        dock_number TEXT,
        vehicle_id TEXT,
        order_id TEXT,
        scheduled_start TEXT,
        scheduled_end TEXT,
        actual_start TEXT,
        actual_end TEXT,
        dock_type TEXT DEFAULT 'loading',
        status TEXT DEFAULT 'Scheduled',
        created_at TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS containers (
        id TEXT PRIMARY KEY,
        container_type TEXT,
        status TEXT DEFAULT 'Available',
        current_location TEXT,
        current_lat REAL,
        current_lng REAL,
        order_id TEXT,
        vehicle_id TEXT,
        last_updated TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS hub_transfers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_id TEXT NOT NULL,
        from_hub_id TEXT,
        to_hub_id TEXT,
        transfer_status TEXT DEFAULT 'Pending',
        arrived_at TEXT,
        departed_at TEXT,
        sort_lane TEXT,
        created_at TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS cargo_inspections (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_id TEXT NOT NULL,
        hub_id TEXT,
        inspector_name TEXT,
        inspection_result TEXT DEFAULT 'Pass',
        damage_notes TEXT,
        photos TEXT,
        inspected_at TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS carrier_partners (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        contact TEXT,
        modes TEXT,
        rate_per_km REAL,
        coverage_zones TEXT,
        api_endpoint TEXT,
        is_active INTEGER DEFAULT 1,
        created_at TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS staff (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        role TEXT NOT NULL,
        department TEXT DEFAULT 'Operations',
        email TEXT,
        phone TEXT,
        joined_date TEXT,
        shift TEXT DEFAULT 'Day',
        salary_inr REAL DEFAULT 0,
        status TEXT DEFAULT 'Active',
        created_at TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS network_analysis (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        analysis_type TEXT,
        hub_id TEXT,
        route_pair TEXT,
        metric_name TEXT,
        metric_value REAL,
        recommendation TEXT,
        computed_at TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS geofence_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        geofence_id INTEGER,
        vehicle_id TEXT,
        event_type TEXT,
        lat REAL,
        lng REAL,
        triggered_at TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS customer_accounts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        phone TEXT,
        company TEXT,
        created_at TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS dispatches (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_id TEXT NOT NULL,
        vehicle_id TEXT,
        driver_id TEXT,
        route_id INTEGER,
        dispatcher_id TEXT,
        dispatch_status TEXT DEFAULT 'Pending',
        dispatched_at TEXT,
        notes TEXT,
        created_at TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS load_plans (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        vehicle_id TEXT NOT NULL,
        trip_date TEXT,
        total_weight_kg REAL DEFAULT 0,
        total_volume_cbm REAL DEFAULT 0,
        utilization_pct REAL DEFAULT 0,
        status TEXT DEFAULT 'Draft',
        created_by TEXT,
        created_at TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS load_plan_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        load_plan_id INTEGER NOT NULL,
        order_id TEXT NOT NULL,
        weight_kg REAL,
        volume_cbm REAL,
        sequence INTEGER
    );

    CREATE TABLE IF NOT EXISTS warehouse_zones (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        warehouse_id TEXT NOT NULL,
        zone_code TEXT NOT NULL,
        zone_type TEXT,
        capacity_cbm REAL,
        used_cbm REAL DEFAULT 0,
        temperature_controlled INTEGER DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS inventory (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        warehouse_id TEXT NOT NULL,
        zone_id INTEGER,
        order_id TEXT,
        goods_type TEXT,
        quantity REAL,
        unit TEXT,
        cbm REAL DEFAULT 0,
        inbound_at TEXT,
        outbound_at TEXT,
        status TEXT DEFAULT 'stored'
    );

    CREATE TABLE IF NOT EXISTS maintenance_schedule (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        vehicle_id TEXT,
        maintenance_type TEXT DEFAULT 'Routine Service',
        scheduled_date TEXT NOT NULL,
        estimated_cost_inr REAL DEFAULT 0,
        actual_cost_inr REAL,
        vendor TEXT,
        notes TEXT,
        status TEXT DEFAULT 'Scheduled',
        completed_at TEXT,
        created_at TEXT DEFAULT (datetime('now'))
    );

    -- Indexes
    CREATE INDEX IF NOT EXISTS idx_vp_vid    ON vehicle_positions(vehicle_id);
    CREATE INDEX IF NOT EXISTS idx_vp_time   ON vehicle_positions(recorded_at);
    CREATE INDEX IF NOT EXISTS idx_ord_vid   ON orders(vehicle_id);
    CREATE INDEX IF NOT EXISTS idx_alrt_oid  ON alerts(order_id);
    CREATE INDEX IF NOT EXISTS idx_ord_stat  ON orders(order_status);
    CREATE INDEX IF NOT EXISTS idx_ord_cli   ON orders(client_id);
    CREATE INDEX IF NOT EXISTS idx_trips_v   ON trips(vehicle_id);
    CREATE INDEX IF NOT EXISTS idx_fuel_v    ON fuel_logs(vehicle_id);
    CREATE INDEX IF NOT EXISTS idx_notif_r   ON notifications(recipient_id);
    CREATE INDEX IF NOT EXISTS idx_inc_ord   ON incidents(order_id);
    """)
    conn.commit()

    # Graceful column additions (idempotent)
    _safe_add = [
        ("vehicles", "fitness_expiry",      "TEXT"),
        ("vehicles", "pollution_expiry",     "TEXT"),
        ("vehicles", "permit_expiry",        "TEXT"),
        ("vehicles", "assigned_driver_id",   "TEXT"),
        ("orders",   "customer_company",     "TEXT"),
        ("orders",   "client_id",            "TEXT"),
        ("orders",   "delivery_address",     "TEXT"),
        ("orders",   "pod_type",             "TEXT"),
        ("orders",   "pod_reference",        "TEXT"),
        ("orders",   "pod_collected_at",     "TEXT"),
        ("orders",   "pod_status",           "TEXT DEFAULT 'Pending'"),
        ("orders",   "lifecycle_stage",      "TEXT DEFAULT 'Created'"),
        ("orders",   "actual_delivery_datetime", "TEXT"),
        ("orders",   "sla_deadline",         "TEXT"),
        ("orders",   "fuel_cost_inr",        "REAL DEFAULT 0"),
        ("orders",   "toll_cost_inr",        "REAL DEFAULT 0"),
        ("orders",   "maintenance_cost_inr", "REAL DEFAULT 0"),
        ("orders",   "other_cost_inr",       "REAL DEFAULT 0"),
        ("orders",   "total_cost_inr",       "REAL DEFAULT 0"),
        ("orders",   "parent_order_id",      "TEXT"),
    ]
    for table, col, coltype in _safe_add:
        try:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {coltype}")
            conn.commit()
        except Exception:
            pass

    # Graceful column addition for inventory.cbm (idempotent)
    try:
        conn.execute("ALTER TABLE inventory ADD COLUMN cbm REAL DEFAULT 0")
        conn.commit()
    except Exception:
        pass  # column already exists

    try:
        # B-24: Seed demo customer with a HASHED password
        from werkzeug.security import generate_password_hash as _gph
        _hashed = _gph('password123')
        conn.execute(
            "INSERT OR IGNORE INTO customer_accounts "
            "(id, name, email, password, phone, company) "
            "VALUES (1, 'Demo Customer', 'customer@logisense.com', ?, '9840112233', 'Demo Corp')",
            (_hashed,)
        )
        conn.commit()
    except Exception as e:
        logger.warning("Failed to seed default customer account: %s", e)

    conn.close()
    logger.info("SQLite database initialised at %s", DB_PATH)


# ══════════════════════════════════════════════════════════════════════════════
#  MONGODB  (new features — import get_mongo_db() where needed)
# ══════════════════════════════════════════════════════════════════════════════

def _init_mongo():
    """Connect to MongoDB (non-fatal if unavailable)."""
    global _mongo_client, _mongo_db
    try:
        from pymongo import MongoClient
        _mongo_client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=3000)
        _mongo_client.admin.command("ping")
        _mongo_db = _mongo_client[MONGO_DB_NAME]
        logger.info("MongoDB connected: %s / %s", MONGO_URI, MONGO_DB_NAME)
    except Exception as e:
        logger.warning("MongoDB not available (%s) — MongoDB features disabled", e)
        _mongo_db = None
        # B-20: Clearly warn if MONGO_URI was never configured
        if 'localhost' in MONGO_URI:
            logger.warning(
                "MONGO_URI is pointing to localhost (default). "
                "Set the MONGO_URI environment variable for production deployment. "
                "Vehicle registry and analytics features will be unavailable.")


def get_mongo_db():
    """
    Return the MongoDB database object, or None if unavailable.
    Use this in any new feature that needs MongoDB.

    Example:
        from database import get_mongo_db
        db = get_mongo_db()
        if db:
            db.analytics.insert_one({...})
    """
    return _mongo_db


# ══════════════════════════════════════════════════════════════════════════════
#  SHARED HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def log_event(log_type: str, message: str,
              entity_type: str = None, entity_id: str = None,
              metadata=None):
    """Write a system log entry to SQLite (same as original)."""
    from datetime import datetime
    conn = get_db()
    conn.execute(
        "INSERT INTO system_logs "
        "(log_type, entity_type, entity_id, message, metadata) "
        "VALUES (?,?,?,?,?)",
        (log_type, entity_type, entity_id, message,
         json.dumps(metadata) if metadata else None)
    )
    conn.commit()
    conn.close()