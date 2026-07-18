"""
Fleet Command - Database Layer
SQLite-backed persistent storage with comprehensive schema covering all 50 logistics features
"""
import sqlite3
import os
import logging

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'fleet.db')

logger = logging.getLogger(__name__)


def get_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = get_db()
    c = conn.cursor()
    c.executescript("""
    -- ═══════════════════════════════════════════════
    --  CORE TABLES
    -- ═══════════════════════════════════════════════

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
        -- Fleet Registry fields (Q1)
        capacity_tons REAL,
        capacity_cbm REAL,
        insurance_expiry TEXT,
        maintenance_due TEXT,
        fuel_type TEXT DEFAULT 'Diesel',
        -- Driver assignment (Q6)
        assigned_driver_id TEXT,
        -- Fuel monitoring (Q25)
        fuel_level_pct REAL DEFAULT 100,
        odometer_km REAL DEFAULT 0,
        -- Fleet utilization (Q24)
        loaded_distance_km REAL DEFAULT 0,
        total_distance_km REAL DEFAULT 0,
        -- Vehicle telemetry (Q11)
        engine_temp_c REAL,
        engine_health TEXT DEFAULT 'Good',
        -- Compliance (Q26)
        permit_expiry TEXT,
        fitness_expiry TEXT,
        -- Yard management (Q31)
        yard_slot TEXT,
        -- Multi-modal type (Q19)
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
        -- Shipment lifecycle (Q8)
        lifecycle_stage TEXT DEFAULT 'Created',
        -- Proof of delivery (Q7)
        pod_type TEXT,
        pod_reference TEXT,
        pod_collected_at TEXT,
        pod_status TEXT DEFAULT 'Pending',
        -- Priority handling (Q40)
        priority_tier TEXT DEFAULT 'Economy',
        -- Package dimensions (Q18)
        weight_kg REAL,
        length_cm REAL,
        width_cm REAL,
        height_cm REAL,
        volumetric_weight_kg REAL,
        -- SLA tracking (Q14)
        sla_deadline TEXT,
        sla_breached INTEGER DEFAULT 0,
        -- Cost tracking (Q10)
        fuel_cost_inr REAL DEFAULT 0,
        toll_cost_inr REAL DEFAULT 0,
        maintenance_cost_inr REAL DEFAULT 0,
        other_cost_inr REAL DEFAULT 0,
        -- Client (Q16)
        client_id TEXT,
        -- Delivery scheduling (Q27)
        delivery_window_start TEXT,
        delivery_window_end TEXT,
        -- Reverse logistics (Q13)
        is_return INTEGER DEFAULT 0,
        parent_order_id TEXT,
        -- Shipment consolidation (Q20)
        consolidated_batch_id TEXT,
        -- Container tracking (Q33)
        container_id TEXT,
        -- Insurance (Q35)
        insurance_policy_id TEXT,
        -- Cold chain (Q36)
        requires_cold_chain INTEGER DEFAULT 0,
        -- Packaging (Q37)
        packaging_type TEXT,
        -- Carbon emissions (Q49)
        co2_kg REAL DEFAULT 0,
        -- Dispatch system (Q5)
        dispatcher_id TEXT,
        hub_id TEXT,
        FOREIGN KEY (vehicle_id) REFERENCES vehicles(id)
    );

    -- ═══════════════════════════════════════════════
    --  DRIVER MANAGEMENT (Q6)
    -- ═══════════════════════════════════════════════
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
        photo_url TEXT,
        created_at TEXT DEFAULT (datetime('now'))
    );

    -- ═══════════════════════════════════════════════
    --  WAREHOUSE MANAGEMENT (Q3)
    -- ═══════════════════════════════════════════════
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

    CREATE TABLE IF NOT EXISTS warehouse_zones (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        warehouse_id TEXT NOT NULL,
        zone_code TEXT NOT NULL,
        zone_type TEXT,
        capacity_cbm REAL,
        used_cbm REAL DEFAULT 0,
        temperature_controlled INTEGER DEFAULT 0,
        FOREIGN KEY (warehouse_id) REFERENCES warehouses(id)
    );

    CREATE TABLE IF NOT EXISTS inventory (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        warehouse_id TEXT NOT NULL,
        zone_id INTEGER,
        order_id TEXT,
        goods_type TEXT,
        quantity REAL,
        unit TEXT,
        inbound_at TEXT,
        outbound_at TEXT,
        status TEXT DEFAULT 'stored',
        FOREIGN KEY (warehouse_id) REFERENCES warehouses(id)
    );

    -- ═══════════════════════════════════════════════
    --  LOAD PLANNING (Q4)
    -- ═══════════════════════════════════════════════
    CREATE TABLE IF NOT EXISTS load_plans (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        vehicle_id TEXT NOT NULL,
        trip_date TEXT,
        total_weight_kg REAL DEFAULT 0,
        total_volume_cbm REAL DEFAULT 0,
        utilization_pct REAL DEFAULT 0,
        status TEXT DEFAULT 'Draft',
        created_by TEXT,
        created_at TEXT DEFAULT (datetime('now')),
        FOREIGN KEY (vehicle_id) REFERENCES vehicles(id)
    );

    CREATE TABLE IF NOT EXISTS load_plan_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        load_plan_id INTEGER NOT NULL,
        order_id TEXT NOT NULL,
        weight_kg REAL,
        volume_cbm REAL,
        sequence INTEGER,
        FOREIGN KEY (load_plan_id) REFERENCES load_plans(id)
    );

    -- ═══════════════════════════════════════════════
    --  DISPATCH SYSTEM (Q5)
    -- ═══════════════════════════════════════════════
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

    -- ═══════════════════════════════════════════════
    --  ROUTE OPTIMIZATION (Q2)
    -- ═══════════════════════════════════════════════
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

    -- ═══════════════════════════════════════════════
    --  TRIP LIFECYCLE (Q22)
    -- ═══════════════════════════════════════════════
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
        created_at TEXT DEFAULT (datetime('now')),
        FOREIGN KEY (vehicle_id) REFERENCES vehicles(id)
    );

    CREATE TABLE IF NOT EXISTS trip_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        trip_id INTEGER NOT NULL,
        event_type TEXT NOT NULL,
        event_time TEXT DEFAULT (datetime('now')),
        lat REAL,
        lng REAL,
        notes TEXT,
        FOREIGN KEY (trip_id) REFERENCES trips(id)
    );

    -- ═══════════════════════════════════════════════
    --  VEHICLE POSITIONS (existing, enhanced)
    -- ═══════════════════════════════════════════════
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

    -- ═══════════════════════════════════════════════
    --  ALERTS (enhanced)
    -- ═══════════════════════════════════════════════
    CREATE TABLE IF NOT EXISTS alerts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_id TEXT,
        vehicle_id TEXT,
        alert_type TEXT NOT NULL,
        alert_reason TEXT,
        severity TEXT DEFAULT 'Medium',
        delay_minutes INTEGER DEFAULT 0,
        acknowledged INTEGER DEFAULT 0,
        -- Exception handling (Q9)
        incident_type TEXT,
        resolution_notes TEXT,
        resolved_at TEXT,
        created_at TEXT DEFAULT (datetime('now'))
    );

    -- ═══════════════════════════════════════════════
    --  TEMPERATURE LOGS (Q36 - Cold Chain)
    -- ═══════════════════════════════════════════════
    CREATE TABLE IF NOT EXISTS temperature_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_id TEXT NOT NULL,
        vehicle_id TEXT,
        temp_at_dispatch REAL,
        temp_during_transit REAL,
        temp_at_delivery REAL,
        required_range TEXT,
        condition_status TEXT,
        recorded_at TEXT DEFAULT (datetime('now')),
        FOREIGN KEY (order_id) REFERENCES orders(id)
    );

    -- ═══════════════════════════════════════════════
    --  DOCUMENTS
    -- ═══════════════════════════════════════════════
    CREATE TABLE IF NOT EXISTS order_documents (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_id TEXT NOT NULL,
        invoice_status TEXT,
        eway_bill_status TEXT,
        other_documents TEXT,
        document_status TEXT,
        -- Customs handling (Q34)
        customs_declaration TEXT,
        hs_code TEXT,
        duties_inr REAL DEFAULT 0,
        FOREIGN KEY (order_id) REFERENCES orders(id)
    );

    -- ═══════════════════════════════════════════════
    --  CLIENT MANAGEMENT (Q16)
    -- ═══════════════════════════════════════════════
    CREATE TABLE IF NOT EXISTS clients (
        id TEXT PRIMARY KEY,
        company_name TEXT NOT NULL,
        contact_name TEXT,
        contact_email TEXT,
        contact_phone TEXT,
        address TEXT,
        payment_terms TEXT DEFAULT 'Net30',
        credit_limit_inr REAL DEFAULT 0,
        contract_start TEXT,
        contract_end TEXT,
        negotiated_rate_per_km REAL,
        status TEXT DEFAULT 'Active',
        created_at TEXT DEFAULT (datetime('now'))
    );

    -- ═══════════════════════════════════════════════
    --  FREIGHT RATE CALCULATION (Q17)
    -- ═══════════════════════════════════════════════
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

    -- ═══════════════════════════════════════════════
    --  GEOFENCING (Q23)
    -- ═══════════════════════════════════════════════
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

    CREATE TABLE IF NOT EXISTS geofence_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        geofence_id INTEGER,
        vehicle_id TEXT,
        event_type TEXT,
        lat REAL,
        lng REAL,
        triggered_at TEXT DEFAULT (datetime('now')),
        FOREIGN KEY (geofence_id) REFERENCES geofences(id)
    );

    -- ═══════════════════════════════════════════════
    --  FUEL MONITORING (Q25)
    -- ═══════════════════════════════════════════════
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
        logged_at TEXT DEFAULT (datetime('now')),
        FOREIGN KEY (vehicle_id) REFERENCES vehicles(id)
    );

    -- ═══════════════════════════════════════════════
    --  MAINTENANCE / COMPLIANCE (Q26)
    -- ═══════════════════════════════════════════════
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
        created_at TEXT DEFAULT (datetime('now')),
        FOREIGN KEY (vehicle_id) REFERENCES vehicles(id)
    );

    -- ═══════════════════════════════════════════════
    --  SLA MONITORING (Q14)
    -- ═══════════════════════════════════════════════
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

    -- ═══════════════════════════════════════════════
    --  PERFORMANCE METRICS (Q30)
    -- ═══════════════════════════════════════════════
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

    -- ═══════════════════════════════════════════════
    --  REAL-TIME NOTIFICATIONS (Q28)
    -- ═══════════════════════════════════════════════
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

    -- ═══════════════════════════════════════════════
    --  RISK / INSURANCE (Q29, Q35)
    -- ═══════════════════════════════════════════════
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

    -- ═══════════════════════════════════════════════
    --  YARD MANAGEMENT (Q31)
    -- ═══════════════════════════════════════════════
    CREATE TABLE IF NOT EXISTS yard_slots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        warehouse_id TEXT,
        slot_code TEXT NOT NULL,
        slot_type TEXT DEFAULT 'parking',
        is_occupied INTEGER DEFAULT 0,
        vehicle_id TEXT,
        occupied_since TEXT,
        FOREIGN KEY (warehouse_id) REFERENCES warehouses(id)
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

    -- ═══════════════════════════════════════════════
    --  DOCK SCHEDULING (Q32)
    -- ═══════════════════════════════════════════════
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

    -- ═══════════════════════════════════════════════
    --  CONTAINER TRACKING (Q33)
    -- ═══════════════════════════════════════════════
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

    -- ═══════════════════════════════════════════════
    --  HUB SORTING / MULTI-HUB (Q12, Q39)
    -- ═══════════════════════════════════════════════
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

    -- ═══════════════════════════════════════════════
    --  CARGO INSPECTION (Q38)
    -- ═══════════════════════════════════════════════
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

    -- ═══════════════════════════════════════════════
    --  CROSS-DOCKING (Q21)
    -- ═══════════════════════════════════════════════
    CREATE TABLE IF NOT EXISTS cross_dock_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_id TEXT NOT NULL,
        warehouse_id TEXT,
        inbound_vehicle_id TEXT,
        outbound_vehicle_id TEXT,
        docked_at TEXT DEFAULT (datetime('now')),
        transferred_at TEXT,
        status TEXT DEFAULT 'Docked'
    );

    -- ═══════════════════════════════════════════════
    --  CARRIER PARTNERS (Q43)
    -- ═══════════════════════════════════════════════
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

    -- ═══════════════════════════════════════════════
    --  MULTI-TENANT (Q44)
    -- ═══════════════════════════════════════════════
    CREATE TABLE IF NOT EXISTS tenants (
        id TEXT PRIMARY KEY,
        company_name TEXT NOT NULL,
        plan TEXT DEFAULT 'standard',
        admin_email TEXT,
        is_active INTEGER DEFAULT 1,
        created_at TEXT DEFAULT (datetime('now'))
    );

    -- ═══════════════════════════════════════════════
    --  AUTOMATED BILLING (Q45)
    -- ═══════════════════════════════════════════════
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

    -- ═══════════════════════════════════════════════
    --  CONTRACT LOGISTICS (Q46)
    -- ═══════════════════════════════════════════════
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

    -- ═══════════════════════════════════════════════
    --  DEMAND FORECASTING (Q47)
    -- ═══════════════════════════════════════════════
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

    -- ═══════════════════════════════════════════════
    --  SECURITY MONITORING (Q50)
    -- ═══════════════════════════════════════════════
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

    -- ═══════════════════════════════════════════════
    --  SYSTEM LOGS
    -- ═══════════════════════════════════════════════
    CREATE TABLE IF NOT EXISTS system_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        log_type TEXT NOT NULL,
        entity_type TEXT,
        entity_id TEXT,
        message TEXT NOT NULL,
        metadata TEXT,
        created_at TEXT DEFAULT (datetime('now'))
    );

    -- ═══════════════════════════════════════════════
    --  SHIPMENT CONSOLIDATION (Q20)
    -- ═══════════════════════════════════════════════
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

    -- ═══════════════════════════════════════════════
    --  NETWORK OPTIMIZATION (Q48)
    -- ═══════════════════════════════════════════════
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

    -- ═══════════════════════════════════════════════
    --  INDEXES
    -- ═══════════════════════════════════════════════
    CREATE INDEX IF NOT EXISTS idx_vp_vid ON vehicle_positions(vehicle_id);
    CREATE INDEX IF NOT EXISTS idx_vp_time ON vehicle_positions(recorded_at);
    CREATE INDEX IF NOT EXISTS idx_ord_vid ON orders(vehicle_id);
    CREATE INDEX IF NOT EXISTS idx_alrt_oid ON alerts(order_id);
    CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(order_status);
    CREATE INDEX IF NOT EXISTS idx_orders_client ON orders(client_id);
    CREATE INDEX IF NOT EXISTS idx_trips_vehicle ON trips(vehicle_id);
    CREATE INDEX IF NOT EXISTS idx_fuel_vehicle ON fuel_logs(vehicle_id);
    CREATE INDEX IF NOT EXISTS idx_notif_recipient ON notifications(recipient_id);
    CREATE INDEX IF NOT EXISTS idx_incidents_order ON incidents(order_id);

    -- ═══════════════════════════════════════════════
    --  FEATURES 16-25 TABLES
    -- ═══════════════════════════════════════════════

    -- Feature 16: Customer / Client Management
    CREATE TABLE IF NOT EXISTS clients (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        name            TEXT NOT NULL,
        company         TEXT,
        email           TEXT,
        phone           TEXT,
        address         TEXT,
        city            TEXT,
        gstin           TEXT,
        credit_limit_inr REAL DEFAULT 500000,
        payment_terms_days INTEGER DEFAULT 30,
        account_status  TEXT DEFAULT 'Active',
        notes           TEXT,
        created_at      TEXT DEFAULT (datetime('now'))
    );

    -- Feature 17: Billing & Invoicing
    CREATE TABLE IF NOT EXISTS invoices (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        invoice_number  TEXT UNIQUE,
        order_id        TEXT REFERENCES orders(id),
        customer_name   TEXT,
        customer_company TEXT,
        base_amount_inr REAL DEFAULT 0,
        gst_amount_inr  REAL DEFAULT 0,
        total_amount_inr REAL DEFAULT 0,
        payment_status  TEXT DEFAULT 'Unpaid',
        payment_date    TEXT,
        payment_method  TEXT,
        due_date        TEXT,
        billing_address TEXT,
        notes           TEXT,
        created_at      TEXT DEFAULT (datetime('now'))
    );

    -- Feature 20: GPS Geofencing
    CREATE TABLE IF NOT EXISTS geofences (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        name        TEXT NOT NULL,
        lat         REAL NOT NULL,
        lng         REAL NOT NULL,
        radius_km   REAL DEFAULT 5.0,
        zone_type   TEXT DEFAULT 'Delivery Zone',
        active      INTEGER DEFAULT 1,
        created_at  TEXT DEFAULT (datetime('now'))
    );

    -- Feature 21: Maintenance Scheduling
    CREATE TABLE IF NOT EXISTS maintenance_schedule (
        id                  INTEGER PRIMARY KEY AUTOINCREMENT,
        vehicle_id          TEXT REFERENCES vehicles(id),
        maintenance_type    TEXT DEFAULT 'Routine Service',
        scheduled_date      TEXT NOT NULL,
        estimated_cost_inr  REAL DEFAULT 0,
        actual_cost_inr     REAL,
        vendor              TEXT,
        notes               TEXT,
        status              TEXT DEFAULT 'Scheduled',
        completed_at        TEXT,
        created_at          TEXT DEFAULT (datetime('now'))
    );

    -- Feature 22: Contract Management
    CREATE TABLE IF NOT EXISTS contracts (
        id                  INTEGER PRIMARY KEY AUTOINCREMENT,
        title               TEXT NOT NULL,
        client_id           INTEGER REFERENCES clients(id),
        client_name         TEXT,
        start_date          TEXT,
        end_date            TEXT,
        contract_value_inr  REAL DEFAULT 0,
        payment_terms       TEXT DEFAULT '30 days',
        rate_per_km         REAL DEFAULT 0,
        min_orders_per_month INTEGER DEFAULT 0,
        routes_covered      TEXT,
        status              TEXT DEFAULT 'Active',
        created_at          TEXT DEFAULT (datetime('now'))
    );

    -- Feature 24: Staff / HR
    CREATE TABLE IF NOT EXISTS staff (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        name        TEXT NOT NULL,
        role        TEXT NOT NULL,
        department  TEXT DEFAULT 'Operations',
        email       TEXT,
        phone       TEXT,
        joined_date TEXT,
        shift       TEXT DEFAULT 'Day',
        salary_inr  REAL DEFAULT 0,
        status      TEXT DEFAULT 'Active',
        created_at  TEXT DEFAULT (datetime('now'))
    );

    -- Compliance columns on vehicles (added via ALTER TABLE if not exists)
    -- handled at runtime; no-op if they exist
    """)

    conn.commit()

    # ── Graceful column additions (idempotent) ──────────────────────────
    _safe_add = [
        ("vehicles", "fitness_expiry", "TEXT"),
        ("vehicles", "pollution_expiry", "TEXT"),
        ("vehicles", "permit_expiry", "TEXT"),
        ("vehicles", "assigned_driver_id", "TEXT"),
        ("orders",   "customer_company",  "TEXT"),
        ("orders",   "client_id",         "INTEGER"),
        ("orders",   "delivery_address",  "TEXT"),
        ("orders",   "pod_type",          "TEXT"),
        ("orders",   "pod_reference",     "TEXT"),
        ("orders",   "pod_collected_at",  "TEXT"),
        ("orders",   "pod_status",        "TEXT DEFAULT 'Pending'"),
        ("orders",   "lifecycle_stage",   "TEXT DEFAULT 'Created'"),
        ("orders",   "actual_delivery_datetime", "TEXT"),
        ("orders",   "sla_deadline",      "TEXT"),
        ("orders",   "fuel_cost_inr",     "REAL DEFAULT 0"),
        ("orders",   "toll_cost_inr",     "REAL DEFAULT 0"),
        ("orders",   "maintenance_cost_inr","REAL DEFAULT 0"),
        ("orders",   "other_cost_inr",    "REAL DEFAULT 0"),
        ("orders",   "total_cost_inr",    "REAL DEFAULT 0"),
        ("orders",   "parent_order_id",   "TEXT"),
    ]
    for table, col, coltype in _safe_add:
        try:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {coltype}")
            conn.commit()
        except Exception:
            pass  # column already exists – ignore

    conn.close()
    logger.info("Database initialized at %s", DB_PATH)



def log_event(log_type, message, entity_type=None, entity_id=None, metadata=None):
    import json
    conn = get_db()
    conn.execute(
        "INSERT INTO system_logs (log_type, entity_type, entity_id, message, metadata) VALUES (?,?,?,?,?)",
        (log_type, entity_type, entity_id, message, json.dumps(metadata) if metadata else None)
    )
    conn.commit()
    conn.close()