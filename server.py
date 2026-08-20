"""
Fleet Command - Backend Server
Flask REST API + Server-Sent Events for real-time updates
"""
import sys, os

# Fix Windows console encoding (prevents UnicodeEncodeError)
if sys.platform == "win32":
    import io as _io
    sys.stdout = _io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = _io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(__file__))

import io
import json
import logging
import math
import queue
import random
import string
import threading
import uuid
from datetime import datetime, timezone
from flask import Flask, Response, request, jsonify
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash

from database import init_db, get_db, log_event
import mongo_registry
from simulation import simulation_engine

# ── Ensure data directory exists BEFORE setting up the file log handler ──────
_DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')
os.makedirs(_DATA_DIR, exist_ok=True)

# ── Logging ─────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(os.path.join(_DATA_DIR, 'fleet.log'))
    ]
)
logger = logging.getLogger(__name__)

# ── Flask App ────────────────────────────────────────────────────────────────
_FRONTEND_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), '..', 'frontend'))
app = Flask(__name__, static_folder=_FRONTEND_DIR, static_url_path='')

# ── CORS ─────────────────────────────────────────────────────────────────────
# Allow any origin on all /api/* routes so the separately-hosted
# frontend can call the backend without browser cross-origin errors.
CORS(app, resources={r"/api/*": {"origins": "*"}})

# ── Serve frontend ───────────────────────────────────────────────────────────
@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def serve_frontend(path):
    """Serve the frontend SPA. Falls back to index.html for any unknown path."""
    from flask import send_from_directory
    target = os.path.join(_FRONTEND_DIR, path)
    if path and os.path.isfile(target):
        return send_from_directory(_FRONTEND_DIR, path)
    return send_from_directory(_FRONTEND_DIR, 'index.html')

# ── SSE broadcast ────────────────────────────────────────────────────────────
_sse_clients: list[queue.Queue] = []
_sse_lock = threading.Lock()

def broadcast(message: str):
    with _sse_lock:
        dead = []
        for q in _sse_clients:
            try:
                q.put_nowait(message)
            except queue.Full:
                dead.append(q)
        for q in dead:
            _sse_clients.remove(q)

simulation_engine.set_broadcast(broadcast)

# ── Helpers ──────────────────────────────────────────────────────────────────
def row_to_dict(row):
    return dict(row) if row else None

def rows_to_list(rows):
    return [dict(r) for r in rows]

def now_iso():
    return datetime.now(timezone.utc).isoformat()

# ── SSE endpoint ─────────────────────────────────────────────────────────────
@app.route('/api/stream')
def stream():
    client_q = queue.Queue(maxsize=100)
    with _sse_lock:
        _sse_clients.append(client_q)

    log_event('system', 'SSE client connected', 'sse', request.remote_addr)

    def generate():
        # Send initial snapshot
        conn = get_db()
        vehicles = rows_to_list(conn.execute("SELECT * FROM vehicles").fetchall())
        alerts = rows_to_list(conn.execute(
            "SELECT * FROM alerts WHERE acknowledged=0 ORDER BY created_at DESC LIMIT 20").fetchall())
        conn.close()
        snapshot = json.dumps({'type': 'snapshot', 'vehicles': vehicles, 'alerts': alerts, 'timestamp': now_iso()})
        yield f"data: {snapshot}\n\n"

        try:
            while True:
                try:
                    msg = client_q.get(timeout=30)
                    yield f"data: {msg}\n\n"
                except queue.Empty:
                    yield f"data: {json.dumps({'type':'heartbeat','timestamp':now_iso()})}\n\n"
        except GeneratorExit:
            pass
        finally:
            with _sse_lock:
                if client_q in _sse_clients:
                    _sse_clients.remove(client_q)
            log_event('system', 'SSE client disconnected', 'sse', request.remote_addr)

    return Response(generate(), mimetype='text/event-stream',
                    headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no',
                             'Access-Control-Allow-Origin': '*'})

# ── Vehicles ─────────────────────────────────────────────────────────────────
@app.route('/api/vehicles', methods=['GET'])
def get_vehicles():
    conn = get_db()
    vehicles = rows_to_list(conn.execute("SELECT * FROM vehicles ORDER BY id").fetchall())
    conn.close()
    log_event('user_action', f'Fetched all vehicles ({len(vehicles)})', 'vehicles')
    return jsonify({'success': True, 'data': vehicles, 'count': len(vehicles)})

@app.route('/api/vehicles', methods=['POST'])
def create_vehicle():
    data = request.json or {}
    vid = (data.get('id') or '').strip().upper()
    vehicle_type = (data.get('vehicle_type') or '').strip()
    if not vid:
        return jsonify({'success': False, 'error': 'Vehicle ID is required'}), 400
    if not vehicle_type:
        return jsonify({'success': False, 'error': 'Vehicle type is required'}), 400
    conn = get_db()
    existing = conn.execute("SELECT id FROM vehicles WHERE id=?", (vid,)).fetchone()
    if existing:
        conn.close()
        return jsonify({'success': False, 'error': f'Vehicle ID {vid} already exists'}), 409
    conn.execute("""
        INSERT INTO vehicles (
            id, vehicle_type, vehicle_number, plate_number,
            driver_name, driver_contact, status,
            capacity_tons, capacity_cbm, fuel_type,
            insurance_expiry, maintenance_due,
            permit_expiry, fitness_expiry, pollution_expiry,
            transport_mode, yard_slot, last_updated
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        vid,
        vehicle_type,
        data.get('vehicle_number'),
        data.get('plate_number'),
        data.get('driver_name'),
        data.get('driver_contact'),
        data.get('status', 'idle'),
        float(data['capacity_tons']) if data.get('capacity_tons') else None,
        float(data['capacity_cbm']) if data.get('capacity_cbm') else None,
        data.get('fuel_type', 'Diesel'),
        data.get('insurance_expiry'),
        data.get('maintenance_due'),
        data.get('permit_expiry'),
        data.get('fitness_expiry'),
        data.get('pollution_expiry'),
        data.get('transport_mode', 'road'),
        data.get('yard_slot'),
        now_iso()
    ))
    conn.commit()
    conn.close()
    log_event('user_action', f'New vehicle added: {vid} ({vehicle_type})', 'vehicle', vid)
    return jsonify({'success': True, 'vehicle_id': vid, 'message': f'Vehicle {vid} added successfully'})


@app.route('/api/vehicles/<vid>', methods=['DELETE'])
def delete_vehicle(vid):
    conn = get_db()
    existing = conn.execute("SELECT id FROM vehicles WHERE id=?", (vid,)).fetchone()
    if not existing:
        conn.close()
        return jsonify({'success': False, 'error': 'Vehicle not found'}), 404
    # Remove related position history
    conn.execute("DELETE FROM vehicle_positions WHERE vehicle_id=?", (vid,))
    conn.execute("DELETE FROM vehicles WHERE id=?", (vid,))
    conn.commit()
    conn.close()
    log_event('user_action', f'Vehicle deleted: {vid}', 'vehicle', vid)
    return jsonify({'success': True, 'message': f'Vehicle {vid} deleted'})


@app.route('/api/vehicles/<vid>', methods=['GET'])
def get_vehicle(vid):
    conn = get_db()
    v = row_to_dict(conn.execute("SELECT * FROM vehicles WHERE id=?", (vid,)).fetchone())
    if not v:
        conn.close()
        return jsonify({'success': False, 'error': 'Vehicle not found'}), 404
    # Get current order
    if v.get('current_order_id'):
        v['current_order'] = row_to_dict(conn.execute(
            "SELECT * FROM orders WHERE id=?", (v['current_order_id'],)).fetchone())
    # Recent positions (last 50)
    v['position_history'] = rows_to_list(conn.execute("""
        SELECT lat, lng, speed, heading, status, recorded_at FROM vehicle_positions
        WHERE vehicle_id=? ORDER BY recorded_at DESC LIMIT 50
    """, (vid,)).fetchall())
    conn.close()
    return jsonify({'success': True, 'data': v})

@app.route('/api/vehicles/<vid>/history', methods=['GET'])
def get_vehicle_history(vid=None):
    limit = request.args.get('limit', 200, type=int)
    conn = get_db()
    history = rows_to_list(conn.execute("""
        SELECT lat, lng, speed, heading, status, recorded_at FROM vehicle_positions
        WHERE vehicle_id=? ORDER BY recorded_at DESC LIMIT ?
    """, (vid, limit)).fetchall())
    conn.close()
    return jsonify({'success': True, 'data': history, 'vehicle_id': vid})

@app.route('/api/vehicles/<vid>/status', methods=['PUT'])
def update_vehicle_status(vid):
    body = request.get_json()
    if not body or 'status' not in body:
        return jsonify({'success': False, 'error': 'Missing status field'}), 400
    valid_statuses = {'moving', 'idle', 'stopped', 'offline', 'maintenance', 'sea'}
    new_status = body['status']
    if new_status not in valid_statuses:
        return jsonify({'success': False, 'error': f'Invalid status. Valid: {valid_statuses}'}), 400
    conn = get_db()
    conn.execute("UPDATE vehicles SET status=?, last_updated=? WHERE id=?",
                 (new_status, now_iso(), vid))
    conn.commit()
    conn.close()
    log_event('user_action', f'Vehicle {vid} status changed to {new_status}', 'vehicle', vid)
    broadcast(json.dumps({'type': 'status_change', 'vehicle_id': vid, 'status': new_status, 'timestamp': now_iso()}))
    return jsonify({'success': True, 'message': f'Vehicle {vid} status updated to {new_status}'})

# GPS ingest endpoint (for real GPS devices - future)
@app.route('/api/vehicles/<vid>/location', methods=['POST'])
def ingest_location(vid):
    body = request.get_json()
    required = ('lat', 'lng')
    if not body or not all(k in body for k in required):
        return jsonify({'success': False, 'error': 'Missing lat/lng'}), 400
    lat, lng = float(body['lat']), float(body['lng'])
    speed = float(body.get('speed', 0))
    heading = float(body.get('heading', 0))
    status = body.get('status', 'moving')
    recorded_at = body.get('timestamp', now_iso())

    conn = get_db()
    conn.execute("""
        UPDATE vehicles SET current_lat=?, current_lng=?, current_speed=?,
        heading=?, status=?, last_updated=? WHERE id=?
    """, (lat, lng, speed, heading, status, recorded_at, vid))
    conn.execute("""
        INSERT INTO vehicle_positions (vehicle_id, lat, lng, speed, heading, status, recorded_at)
        VALUES (?,?,?,?,?,?,?)
    """, (vid, lat, lng, speed, heading, status, recorded_at))
    conn.commit()
    conn.close()

    update = json.dumps({'type': 'vehicle_update', 'timestamp': recorded_at,
                         'vehicles': [{'id': vid,
                                       'current_lat': lat, 'current_lng': lng,
                                       'current_speed': speed,
                                       'heading': heading, 'status': status,
                                       '_driver_gps': True}], 'alerts': []})
    broadcast(update)
    log_event('gps', f'GPS update for {vid}', 'vehicle', vid, {'lat': lat, 'lng': lng, 'speed': speed})
    return jsonify({'success': True})

# ── Orders ───────────────────────────────────────────────────────────────────
@app.route('/api/orders', methods=['GET'])
def get_orders():
    status_filter = request.args.get('status')
    search = request.args.get('search', '').strip()
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)

    conn = get_db()
    query = "SELECT * FROM orders WHERE 1=1"
    params = []
    if status_filter:
        query += " AND order_status=?"
        params.append(status_filter)
    if search:
        query += " AND (id LIKE ? OR customer_name LIKE ? OR customer_company LIKE ? OR vehicle_id LIKE ?)"
        s = f"%{search}%"
        params += [s, s, s, s]

    total = conn.execute(f"SELECT COUNT(*) FROM ({query})", params).fetchone()[0]
    query += " ORDER BY dispatch_datetime DESC LIMIT ? OFFSET ?"
    params += [per_page, (page - 1) * per_page]
    orders = rows_to_list(conn.execute(query, params).fetchall())
    conn.close()
    return jsonify({'success': True, 'data': orders, 'total': total, 'page': page, 'per_page': per_page})

@app.route('/api/orders/<oid>', methods=['GET'])
def get_order(oid):
    conn = get_db()
    o = row_to_dict(conn.execute("SELECT * FROM orders WHERE id=?", (oid,)).fetchone())
    if not o:
        conn.close()
        return jsonify({'success': False, 'error': 'Order not found'}), 404
    o['tracking'] = row_to_dict(conn.execute(
        "SELECT * FROM vehicle_positions WHERE order_id=? ORDER BY recorded_at DESC LIMIT 1", (oid,)).fetchone())
    o['alerts'] = rows_to_list(conn.execute("SELECT * FROM alerts WHERE order_id=?", (oid,)).fetchall())
    o['temperature'] = row_to_dict(conn.execute("SELECT * FROM temperature_logs WHERE order_id=?", (oid,)).fetchone())
    o['documents'] = row_to_dict(conn.execute("SELECT * FROM order_documents WHERE order_id=?", (oid,)).fetchone())
    conn.close()
    return jsonify({'success': True, 'data': o})

# ── Alerts ───────────────────────────────────────────────────────────────────
@app.route('/api/alerts', methods=['GET'])
def get_alerts():
    limit = request.args.get('limit', 50, type=int)
    unread_only = request.args.get('unread', 'false').lower() == 'true'
    conn = get_db()
    query = "SELECT a.*, v.driver_name, v.vehicle_type FROM alerts a LEFT JOIN vehicles v ON a.vehicle_id=v.id"
    if unread_only:
        query += " WHERE a.acknowledged=0"
    query += " ORDER BY a.created_at DESC LIMIT ?"
    alerts = rows_to_list(conn.execute(query, (limit,)).fetchall())
    conn.close()
    return jsonify({'success': True, 'data': alerts, 'count': len(alerts)})

@app.route('/api/alerts/<int:aid>/acknowledge', methods=['PUT'])
def ack_alert(aid):
    conn = get_db()
    conn.execute("UPDATE alerts SET acknowledged=1 WHERE id=?", (aid,))
    conn.commit()
    conn.close()
    log_event('user_action', f'Alert {aid} acknowledged', 'alert', str(aid))
    return jsonify({'success': True})

# ── Analytics ────────────────────────────────────────────────────────────────
@app.route('/api/analytics/summary', methods=['GET'])
def analytics_summary():
    conn = get_db()
    total_vehicles = conn.execute("SELECT COUNT(*) FROM vehicles").fetchone()[0]
    active_vehicles = conn.execute("SELECT COUNT(*) FROM vehicles WHERE status='moving'").fetchone()[0]
    idle_vehicles = conn.execute("SELECT COUNT(*) FROM vehicles WHERE status='idle'").fetchone()[0]
    maintenance_vehicles = conn.execute("SELECT COUNT(*) FROM vehicles WHERE status='maintenance'").fetchone()[0]
    offline_vehicles = conn.execute("SELECT COUNT(*) FROM vehicles WHERE status='offline'").fetchone()[0]

    total_orders = conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
    delivered = conn.execute("SELECT COUNT(*) FROM orders WHERE order_status='Delivered'").fetchone()[0]
    in_transit = conn.execute("SELECT COUNT(*) FROM orders WHERE order_status='In Transit'").fetchone()[0]

    avg_speed_row = conn.execute(
        "SELECT AVG(current_speed) FROM vehicles WHERE status='moving' AND current_speed > 0").fetchone()
    avg_speed = round(avg_speed_row[0] or 0, 1)

    total_revenue = conn.execute("SELECT SUM(transport_cost_inr) FROM orders").fetchone()[0] or 0
    total_distance = conn.execute("SELECT SUM(distance_km) FROM orders").fetchone()[0] or 0

    unread_alerts = conn.execute("SELECT COUNT(*) FROM alerts WHERE acknowledged=0").fetchone()[0]

    on_time_rows = conn.execute("""
        SELECT COUNT(*) FROM orders
        WHERE order_status='Delivered'
        AND actual_delivery_datetime <= expected_delivery_datetime
    """).fetchone()[0]

    # Average speed by vehicle
    avg_by_vehicle = rows_to_list(conn.execute("""
        SELECT v.id, v.driver_name, AVG(vp.speed) as avg_speed, MAX(vp.speed) as max_speed,
               COUNT(vp.id) as position_count
        FROM vehicles v
        JOIN vehicle_positions vp ON v.id = vp.vehicle_id
        WHERE vp.speed > 0
        GROUP BY v.id ORDER BY avg_speed DESC LIMIT 10
    """).fetchall())

    # Orders by route
    orders_by_route = rows_to_list(conn.execute("""
        SELECT source_city, destination_city, COUNT(*) as count,
               SUM(transport_cost_inr) as revenue, AVG(distance_km) as avg_distance
        FROM orders GROUP BY source_city, destination_city ORDER BY count DESC
    """).fetchall())

    # Alert breakdown
    alert_breakdown = rows_to_list(conn.execute("""
        SELECT alert_type, severity, COUNT(*) as count
        FROM alerts GROUP BY alert_type, severity ORDER BY count DESC
    """).fetchall())

    conn.close()
    on_time_pct = round((on_time_rows / delivered * 100) if delivered > 0 else 0, 1)

    return jsonify({'success': True, 'data': {
        'vehicles': {
            'total': total_vehicles, 'active': active_vehicles, 'idle': idle_vehicles,
            'maintenance': maintenance_vehicles, 'offline': offline_vehicles
        },
        'orders': {
            'total': total_orders, 'delivered': delivered, 'in_transit': in_transit,
            'on_time_pct': on_time_pct
        },
        'performance': {
            'avg_speed_kmh': avg_speed,
            'total_revenue_inr': round(total_revenue, 2),
            'total_distance_km': round(total_distance, 2),
        },
        'alerts': {'unread': unread_alerts},
        'top_vehicles_by_speed': avg_by_vehicle,
        'routes': orders_by_route,
        'alert_breakdown': alert_breakdown,
    }})

# ── Driver Auth ──────────────────────────────────────────────────────────────
@app.route('/api/driver/login', methods=['POST'])
def driver_login():
    body = request.get_json()
    if not body or 'vehicle_id' not in body:
        return jsonify({'success': False, 'error': 'Missing vehicle_id'}), 400

    vehicle_id = str(body['vehicle_id']).strip().upper()
    auth_mode  = str(body.get('auth_mode', 'contact'))   # 'contact' | 'pin' | 'otp'

    conn = get_db()
    v = row_to_dict(conn.execute(
        "SELECT * FROM vehicles WHERE id=?", (vehicle_id,)).fetchone())

    if not v:
        conn.close()
        return jsonify({'success': False, 'error': 'Vehicle not found'}), 404

    # Normalize: keep only last 10 digits of stored contact (strips country code like 91)
    db_contact = ''.join(filter(str.isdigit, str(v.get('driver_contact') or '')))
    if len(db_contact) > 10:
        db_contact = db_contact[-10:]

    if auth_mode == 'pin':
        # PIN = last 4 digits of contact (default); can be overridden by driver_pin column
        provided_pin = ''.join(filter(str.isdigit, str(body.get('pin', ''))))
        stored_pin   = str(v.get('driver_pin') or (db_contact[-4:] if len(db_contact) >= 4 else ''))
        if not provided_pin or provided_pin != stored_pin:
            conn.close()
            log_event('user_action', f'Driver PIN login failed for vehicle {vehicle_id}', 'driver', vehicle_id)
            return jsonify({'success': False, 'error': 'Invalid PIN'}), 401
    elif auth_mode == 'otp':
        # Bug G fix: OTP verification was accepting any non-empty string as valid.
        # Server-side OTP issuance/validation is not yet implemented; refuse the
        # request rather than grant access with an unverified token.
        conn.close()
        return jsonify({
            'success': False,
            'error': 'OTP login is not yet supported server-side. Use contact or PIN auth.'
        }), 501
    else:
        # Default: contact number match (last 10 digits)
        contact    = str(body.get('contact', '')).strip()
        in_contact = ''.join(filter(str.isdigit, contact))
        if len(in_contact) > 10:
            in_contact = in_contact[-10:]
        if not db_contact or not in_contact or db_contact != in_contact:
            conn.close()
            log_event('user_action', f'Driver login failed for vehicle {vehicle_id}', 'driver', vehicle_id)
            return jsonify({'success': False, 'error': 'Contact number does not match'}), 401


    # Get current order if any
    current_order = None
    if v.get('current_order_id'):
        current_order = row_to_dict(conn.execute(
            "SELECT id, source_city, destination_city, customer_name, order_status, expected_delivery_datetime, distance_km FROM orders WHERE id=?",
            (v['current_order_id'],)).fetchone())

    conn.close()
    log_event('user_action', f'Driver {v["driver_name"]} logged in via {auth_mode} (vehicle {vehicle_id})', 'driver', vehicle_id)
    return jsonify({'success': True, 'data': {**v, 'current_order': current_order}})

# ── Customer Auth ─────────────────────────────────────────────────────────────
@app.route('/api/customer/signup', methods=['POST'])
def customer_signup():
    body = request.get_json() or {}
    name = body.get('name', '').strip()
    email = body.get('email', '').strip()
    password = body.get('password', '').strip()

    if not name or not email or not password:
        return jsonify({'success': False, 'error': 'Name, email, and password required'}), 400

    conn = get_db()
    existing = conn.execute("SELECT id FROM customer_accounts WHERE email=?", (email,)).fetchone()
    if existing:
        conn.close()
        return jsonify({'success': False, 'error': 'Email already registered'}), 409

    # B-02: Store passwords as hashes, never plaintext
    conn.execute("INSERT INTO customer_accounts (name, email, password) VALUES (?, ?, ?)",
                 (name, email, generate_password_hash(password)))
    conn.commit()
    user = row_to_dict(conn.execute("SELECT id, name, email FROM customer_accounts WHERE email=?", (email,)).fetchone())
    conn.close()
    
    log_event('user_action', f'New customer account created: {email}', 'customer', str(user['id']))
    return jsonify({'success': True, 'data': user})

@app.route('/api/customer/auth', methods=['POST'])
def customer_auth():
    body = request.get_json() or {}
    email = body.get('email', '').strip()
    password = body.get('password', '').strip()

    if not email or not password:
        return jsonify({'success': False, 'error': 'Email and password required'}), 400

    conn = get_db()
    # B-02: Fetch the stored hash and verify with check_password_hash
    row = row_to_dict(conn.execute(
        "SELECT id, name, email, password FROM customer_accounts WHERE email=?", (email,)).fetchone())
    conn.close()

    if not row or not check_password_hash(row['password'], password):
        return jsonify({'success': False, 'error': 'Invalid credentials'}), 401

    user = {k: row[k] for k in ('id', 'name', 'email')}
    log_event('user_action', f'Customer account logged in: {email}', 'customer', str(user['id']))
    return jsonify({'success': True, 'data': user})

# ── Admin Auth (B-03: credentials validated server-side via env vars) ─────────
@app.route('/api/admin/auth', methods=['POST'])
def admin_auth():
    """Validates admin credentials server-side. Credentials are read from
    environment variables ADMIN_USER, ADMIN_PASS, ADMIN_OTP, ADMIN_PIN.
    Falls back to defaults only if env vars are not set (dev mode)."""
    body = request.get_json() or {}
    method = body.get('method', 'password')  # 'password', 'otp', or 'pin'
    user = body.get('user', '').strip()

    admin_user = os.environ.get('ADMIN_USER', 'MegaTron')
    admin_pass = os.environ.get('ADMIN_PASS', 'MG@88307')
    admin_otp  = os.environ.get('ADMIN_OTP',  '213069')
    admin_pin  = os.environ.get('ADMIN_PIN',  '8181')

    if not user or user != admin_user:
        return jsonify({'success': False, 'error': 'Invalid username'}), 401

    ok = False
    if method == 'password':
        ok = (body.get('pass', '') == admin_pass)
    elif method == 'otp':
        ok = (body.get('otp', '') == admin_otp)
    elif method == 'pin':
        ok = (body.get('pin', '') == admin_pin)

    if not ok:
        return jsonify({'success': False, 'error': 'Invalid credentials'}), 401

    log_event('user_action', f'Admin logged in via {method}', 'admin', user)
    return jsonify({'success': True})

# ── Logs ─────────────────────────────────────────────────────────────────────
@app.route('/api/logs', methods=['GET'])
def get_logs():
    limit = request.args.get('limit', 100, type=int)
    log_type = request.args.get('type')
    conn = get_db()
    query = "SELECT * FROM system_logs"
    params = []
    if log_type:
        query += " WHERE log_type=?"
        params.append(log_type)
    query += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    logs = rows_to_list(conn.execute(query, params).fetchall())
    conn.close()
    return jsonify({'success': True, 'data': logs})

# ── Serve frontend (no-cache so reseeding shows fresh data) ───────────────────

# ── FEATURE 1: Fleet Registry ─────────────────────────────────────────────────
@app.route('/api/fleet/registry', methods=['GET'])
def fleet_registry():
    conn = get_db()
    rows = rows_to_list(conn.execute("""
        SELECT v.*,
               m.performed_at AS last_maintenance, m.next_due_at AS next_maintenance,
               (SELECT COUNT(*) FROM orders WHERE vehicle_id=v.id) AS total_orders
        FROM vehicles v
        LEFT JOIN maintenance_records m ON m.vehicle_id=v.id AND m.id=(
            SELECT id FROM maintenance_records WHERE vehicle_id=v.id ORDER BY performed_at DESC LIMIT 1)
        ORDER BY v.id
    """).fetchall())
    conn.close()

    # ── Merge MongoDB registry details ─────────────────────────────────────────
    mongo_docs = {d['vehicle_id']: d for d in mongo_registry.get_all_registry()}
    for row in rows:
        vid  = row.get('id')
        mdoc = mongo_docs.get(vid, {})
        # MongoDB fields override / supplement SQLite nulls
        for field in ['capacity_tons', 'capacity_cbm', 'insurance_expiry',
                      'permit_expiry', 'fitness_expiry', 'maintenance_due',
                      'fuel_type', 'transport_mode']:
            if not row.get(field) and mdoc.get(field):
                row[field] = mdoc[field]
        # Attach extra Mongo-only fields
        for extra in ['insurance_provider', 'insurance_policy', 'insurance_coverage_inr',
                      'pollution_expiry', 'year_of_manufacture', 'chassis_no',
                      'engine_no', 'notes']:
            row[extra] = mdoc.get(extra)

    return jsonify({'success': True, 'data': rows, 'count': len(rows)})

# ── MongoDB Fleet Registry CRUD ───────────────────────────────────────────────
@app.route('/api/fleet/mongo-registry', methods=['GET'])
def mongo_registry_get_all():
    docs = mongo_registry.get_all_registry()
    return jsonify({'success': True, 'data': docs, 'count': len(docs)})

@app.route('/api/fleet/mongo-registry/<vid>', methods=['GET'])
def mongo_registry_get_one(vid):
    doc = mongo_registry.get_registry_by_id(vid)
    if not doc:
        return jsonify({'success': False, 'error': 'Vehicle not found in registry'}), 404
    return jsonify({'success': True, 'data': doc})

@app.route('/api/fleet/mongo-registry/<vid>', methods=['PUT'])
def mongo_registry_upsert(vid):
    body = request.get_json() or {}
    body.pop('vehicle_id', None)   # enforce URL-sourced vehicle_id
    ok = mongo_registry.upsert_registry(vid, body)
    if ok:
        log_event('user_action', f'MongoDB registry updated for {vid}', 'vehicle', vid)
        return jsonify({'success': True})
    return jsonify({'success': False, 'error': 'Failed to update registry'}), 500

@app.route('/api/fleet/mongo-registry/<vid>', methods=['DELETE'])
def mongo_registry_delete(vid):
    deleted = mongo_registry.delete_registry(vid)
    if deleted:
        log_event('user_action', f'MongoDB registry deleted for {vid}', 'vehicle', vid)
        return jsonify({'success': True})
    return jsonify({'success': False, 'error': 'Vehicle registry not found'}), 404

@app.route('/api/fleet/registry/<vid>', methods=['PUT'])
def update_fleet_registry(vid):
    body = request.get_json() or {}
    allowed = ['capacity_tons','capacity_cbm','insurance_expiry','maintenance_due',
                'fuel_type','transport_mode','permit_expiry','fitness_expiry']
    sets = ', '.join(f"{k}=?" for k in allowed if k in body)
    vals = [body[k] for k in allowed if k in body]
    if not sets:
        return jsonify({'success': False, 'error': 'No valid fields'}), 400
    vals.append(vid)
    conn = get_db()
    conn.execute(f"UPDATE vehicles SET {sets} WHERE id=?", vals)
    conn.commit()
    conn.close()
    log_event('user_action', f'Fleet registry updated for {vid}', 'vehicle', vid)
    return jsonify({'success': True})

@app.route('/api/fleet/maintenance', methods=['GET'])
def fleet_maintenance():
    conn = get_db()
    rows = rows_to_list(conn.execute("""
        SELECT m.*, v.vehicle_number, v.driver_name FROM maintenance_records m
        JOIN vehicles v ON m.vehicle_id=v.id ORDER BY m.performed_at DESC LIMIT 100
    """).fetchall())
    conn.close()
    return jsonify({'success': True, 'data': rows})

@app.route('/api/fleet/maintenance', methods=['POST'])
def add_maintenance():
    body = request.get_json() or {}
    required = ('vehicle_id', 'maintenance_type', 'description')
    if not all(k in body for k in required):
        return jsonify({'success': False, 'error': 'Missing fields'}), 400
    conn = get_db()
    conn.execute("""
        INSERT INTO maintenance_records
            (vehicle_id,maintenance_type,description,cost_inr,vendor,performed_at,next_due_at,status)
        VALUES (?,?,?,?,?,?,?,?)
    """, (body['vehicle_id'], body['maintenance_type'], body['description'],
          body.get('cost_inr', 0), body.get('vendor'), body.get('performed_at', now_iso()),
          body.get('next_due_at'), body.get('status', 'Completed')))
    conn.execute("UPDATE vehicles SET maintenance_due=? WHERE id=?",
                 (body.get('next_due_at'), body['vehicle_id']))
    conn.commit()
    conn.close()
    log_event('user_action', f"Maintenance logged for {body['vehicle_id']}", 'vehicle', body['vehicle_id'])
    return jsonify({'success': True})

@app.route('/api/fleet/expiry-alerts', methods=['GET'])
def fleet_expiry_alerts():
    conn = get_db()
    rows = rows_to_list(conn.execute("""
        SELECT id, vehicle_number, driver_name,
               insurance_expiry, permit_expiry, fitness_expiry, maintenance_due
        FROM vehicles
        WHERE insurance_expiry IS NOT NULL OR permit_expiry IS NOT NULL
           OR fitness_expiry IS NOT NULL OR maintenance_due IS NOT NULL
        ORDER BY insurance_expiry ASC
    """).fetchall())
    conn.close()
    return jsonify({'success': True, 'data': rows})

def seed_maintenance_records():
    """Insert 6 sample maintenance records if table is empty."""
    conn = get_db()
    count = conn.execute('SELECT COUNT(*) FROM maintenance_records').fetchone()[0]
    if count == 0:
        records = [
            ('OFE-TRK-001', 'Oil Change',          'Engine oil & filter replacement — 15W-40 diesel grade',     4500,  'Ashok Leyland Service Centre', '2025-09-15', '2026-03-15', 'Completed'),
            ('OFE-TRK-003', 'Tire Rotation',       'All 6 tyres rotated and pressure balanced to 110 PSI',      2800,  'CEAT Tyre Hub, Chennai',       '2025-10-20', '2026-04-20', 'Completed'),
            ('OFE-TRK-005', 'Brake Service',       'Front disc brake pads replaced, rear drums adjusted',        9200,  'MRF Service, Hyderabad',       '2025-11-08', '2026-05-08', 'Completed'),
            ('OFE-TRK-007', 'Engine Check',        'Full ECU diagnostic, fuel injectors cleaned, coolant flush', 6800,  'Tata Motors Authorised Centre','2025-12-01', '2026-06-01', 'Completed'),
            ('OFE-TRK-009', 'Battery',             '12V 150Ah battery replaced — Exide make',                   8500,  'National Battery Dealers',     '2026-01-18', '2027-01-18', 'Completed'),
            ('OFE-TRK-011', 'General Inspection',  'Pre-monsoon full vehicle inspection, AC regas, wiper blades',3900,  'Quick Lube Mumbai',            '2026-02-10', '2026-08-10', 'Completed'),
        ]
        conn.executemany("""
            INSERT INTO maintenance_records
                (vehicle_id,maintenance_type,description,cost_inr,vendor,performed_at,next_due_at,status)
            VALUES (?,?,?,?,?,?,?,?)
        """, records)
        conn.commit()
        logger.info("Seeded 6 maintenance records")
    conn.close()

# ── FEATURE 2: Route Optimization ────────────────────────────────────────────
@app.route('/api/routes', methods=['GET'])
def get_routes():
    conn = get_db()
    rows = rows_to_list(conn.execute("SELECT * FROM routes ORDER BY distance_km ASC").fetchall())
    conn.close()
    return jsonify({'success': True, 'data': rows})

@app.route('/api/routes', methods=['POST'])
def create_route():
    body = request.get_json() or {}
    conn = get_db()
    conn.execute("""
        INSERT INTO routes (name,source_city,destination_city,distance_km,estimated_hours,
                            toll_cost_inr,traffic_factor,via_cities,transport_mode,is_optimized)
        VALUES (?,?,?,?,?,?,?,?,?,?)
    """, (body.get('name'), body.get('source_city'), body.get('destination_city'),
          body.get('distance_km', 0), body.get('estimated_hours', 0),
          body.get('toll_cost_inr', 0), body.get('traffic_factor', 1.0),
          body.get('via_cities'), body.get('transport_mode', 'road'),
          body.get('is_optimized', 0)))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/api/routes/optimize', methods=['POST'])
def optimize_route():
    """Score routes by composite: distance + tolls + traffic + priority weight."""
    body = request.get_json() or {}
    src = body.get('source_city', '')
    dst = body.get('destination_city', '')
    priority = body.get('priority', 'Economy')   # Economy / Priority / Express

    conn = get_db()
    routes = rows_to_list(conn.execute("""
        SELECT * FROM routes WHERE source_city=? AND destination_city=?
    """, (src, dst)).fetchall())
    conn.close()

    priority_factor = {'Express': 0.6, 'Priority': 0.8, 'Economy': 1.0}.get(priority, 1.0)
    for r in routes:
        toll   = r.get('toll_cost_inr') or 0
        dist   = r.get('distance_km') or 1
        tf     = r.get('traffic_factor') or 1.0
        # composite score (lower = better)
        r['score'] = round((dist * tf + toll * 0.01) * priority_factor, 2)
    routes.sort(key=lambda x: x['score'])
    return jsonify({'success': True, 'data': routes,
                    'best_route': routes[0] if routes else None})

@app.route('/api/routes/<int:rid>', methods=['DELETE'])
def delete_route(rid):
    conn = get_db()
    existing = conn.execute("SELECT id FROM routes WHERE id=?", (rid,)).fetchone()
    if not existing:
        conn.close()
        return jsonify({'success': False, 'error': 'Route not found'}), 404
    conn.execute("DELETE FROM routes WHERE id=?", (rid,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

# ── FEATURE 3: Warehouse Management ──────────────────────────────────────────
@app.route('/api/warehouses', methods=['GET'])
def get_warehouses():
    conn = get_db()
    rows = rows_to_list(conn.execute("SELECT * FROM warehouses ORDER BY name").fetchall())
    for wh in rows:
        try:
            wh['zones'] = rows_to_list(conn.execute(
                "SELECT * FROM warehouse_zones WHERE warehouse_id=?", (wh['id'],)).fetchall())
            wh['inventory_count'] = conn.execute(
                "SELECT COUNT(*) FROM inventory WHERE warehouse_id=? AND status='stored'",
                (wh['id'],)).fetchone()[0]
        except Exception:
            wh['zones'] = []
            wh['inventory_count'] = 0
    conn.close()
    return jsonify({'success': True, 'data': rows})

@app.route('/api/warehouses', methods=['POST'])
def add_warehouse():
    body = request.get_json() or {}
    if not body.get('name'):
        return jsonify({'success': False, 'error': 'Warehouse name is required'}), 400
    import uuid
    wid = body.get('id') or ('WH-' + str(uuid.uuid4())[:6].upper())
    conn = get_db()
    try:
        conn.execute("""
            INSERT INTO warehouses (id,name,location,city,lat,lng,total_capacity_cbm,manager_name,contact,is_hub)
            VALUES (?,?,?,?,?,?,?,?,?,?)
        """, (wid, body.get('name'), body.get('location'), body.get('city'),
              body.get('lat'), body.get('lng'), body.get('total_capacity_cbm', 0),
              body.get('manager_name'), body.get('contact'), body.get('is_hub', 0)))
        conn.commit()
        log_event('user_action', f'Warehouse added: {wid} ({body.get("name")})', 'warehouse', wid)
        return jsonify({'success': True, 'id': wid})
    except Exception as e:
        conn.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        conn.close()

@app.route('/api/warehouses/<wid>', methods=['DELETE'])
def delete_warehouse(wid):
    conn = get_db()
    existing = conn.execute("SELECT id, name FROM warehouses WHERE id=?", (wid,)).fetchone()
    if not existing:
        conn.close()
        return jsonify({'success': False, 'error': 'Warehouse not found'}), 404
    try:
        conn.execute("DELETE FROM inventory WHERE warehouse_id=?", (wid,))
        conn.execute("DELETE FROM warehouse_zones WHERE warehouse_id=?", (wid,))
        conn.execute("DELETE FROM warehouses WHERE id=?", (wid,))
        conn.commit()
        log_event('user_action', f'Warehouse deleted: {wid}', 'warehouse', wid)
        return jsonify({'success': True, 'message': f'Warehouse {wid} deleted'})
    except Exception as e:
        conn.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        conn.close()

@app.route('/api/warehouses/<wid>/inventory', methods=['GET'])
def warehouse_inventory(wid):
    conn = get_db()
    rows = rows_to_list(conn.execute(
        "SELECT * FROM inventory WHERE warehouse_id=? ORDER BY inbound_at DESC", (wid,)).fetchall())
    conn.close()
    return jsonify({'success': True, 'data': rows})

@app.route('/api/warehouses/<wid>/inventory/inbound', methods=['POST'])
def inventory_inbound(wid):
    body = request.get_json() or {}
    conn = get_db()
    conn.execute("""
        INSERT INTO inventory (warehouse_id,zone_id,order_id,goods_type,quantity,unit,inbound_at,status)
        VALUES (?,?,?,?,?,?,?,?)
    """, (wid, body.get('zone_id'), body.get('order_id'), body.get('goods_type'),
          body.get('quantity', 0), body.get('unit'), now_iso(), 'stored'))
    conn.execute("UPDATE warehouses SET used_capacity_cbm=used_capacity_cbm+? WHERE id=?",
                 (body.get('cbm', 0), wid))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/api/warehouses/<wid>/inventory/<int:iid>/outbound', methods=['PUT'])
def inventory_outbound(wid, iid):
    conn = get_db()
    conn.execute("UPDATE inventory SET status='dispatched', outbound_at=? WHERE id=?",
                 (now_iso(), iid))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/api/warehouses/<wid>/inventory/<int:iid>', methods=['DELETE'])
def delete_inventory_item(wid, iid):
    conn = get_db()
    existing = conn.execute(
        "SELECT id, goods_type FROM inventory WHERE id=? AND warehouse_id=?", (iid, wid)).fetchone()
    if not existing:
        conn.close()
        return jsonify({'success': False, 'error': 'Inventory item not found'}), 404
    try:
        # Reduce used_capacity_cbm — best-effort, cbm column may be null
        conn.execute("""
            UPDATE warehouses
            SET used_capacity_cbm = MAX(0, used_capacity_cbm - COALESCE(
                (SELECT cbm FROM inventory WHERE id=?), 0))
            WHERE id=?
        """, (iid, wid))
        conn.execute("DELETE FROM inventory WHERE id=? AND warehouse_id=?", (iid, wid))
        conn.commit()
        log_event('user_action', f'Inventory item {iid} deleted from warehouse {wid}', 'warehouse', wid)
        return jsonify({'success': True, 'message': 'Item deleted'})
    except Exception as e:
        conn.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        conn.close()

@app.route('/api/warehouses/<wid>/stock-count', methods=['GET'])
def stock_count(wid):
    conn = get_db()
    rows = rows_to_list(conn.execute("""
        SELECT goods_type, SUM(quantity) as total_qty, unit, COUNT(*) as line_items
        FROM inventory WHERE warehouse_id=? AND status='stored'
        GROUP BY goods_type, unit
    """, (wid,)).fetchall())
    conn.close()
    return jsonify({'success': True, 'data': rows})

# ── FEATURE 4: Load Planning ──────────────────────────────────────────────────
@app.route('/api/load-plans', methods=['GET'])
def get_load_plans():
    conn = get_db()
    plans = rows_to_list(conn.execute("""
        SELECT lp.*, v.vehicle_number, v.driver_name, v.capacity_tons, v.capacity_cbm
        FROM load_plans lp
        LEFT JOIN vehicles v ON lp.vehicle_id=v.id
        ORDER BY lp.created_at DESC LIMIT 50
    """).fetchall())
    for p in plans:
        p['items'] = rows_to_list(conn.execute(
            "SELECT lpi.*,o.goods_type,o.customer_name FROM load_plan_items lpi "
            "JOIN orders o ON lpi.order_id=o.id WHERE lpi.load_plan_id=?", (p['id'],)).fetchall())
    conn.close()
    return jsonify({'success': True, 'data': plans})

@app.route('/api/load-plans/optimize', methods=['POST'])
def optimize_load():
    """Auto-assign orders to vehicles respecting weight/volume caps."""
    body = request.get_json() or {}
    vehicle_id = body.get('vehicle_id')
    order_ids  = body.get('order_ids', [])

    conn = get_db()
    v = row_to_dict(conn.execute("SELECT * FROM vehicles WHERE id=?", (vehicle_id,)).fetchone())
    if not v:
        conn.close()
        return jsonify({'success': False, 'error': 'Vehicle not found'}), 404

    cap_tons = v.get('capacity_tons') or 20
    cap_cbm  = v.get('capacity_cbm') or 80
    selected, total_w, total_v = [], 0.0, 0.0

    for oid in order_ids:
        o = row_to_dict(conn.execute("SELECT * FROM orders WHERE id=?", (oid,)).fetchone())
        if not o:
            continue
        w = o.get('weight_kg') or 0
        vol = 0
        if o.get('length_cm') and o.get('width_cm') and o.get('height_cm'):
            vol = (o['length_cm'] * o['width_cm'] * o['height_cm']) / 1e6
        if (total_w + w/1000) <= cap_tons and (total_v + vol) <= cap_cbm:
            selected.append({'order_id': oid, 'weight_kg': w, 'volume_cbm': round(vol, 3)})
            total_w += w / 1000
            total_v += vol

    # Save plan
    cur = conn.execute("""
        INSERT INTO load_plans (vehicle_id,trip_date,total_weight_kg,total_volume_cbm,utilization_pct,status)
        VALUES (?,?,?,?,?,?)
    """, (vehicle_id, body.get('trip_date', now_iso()),
          round(total_w*1000, 2), round(total_v, 3),
          round(total_w/cap_tons*100, 1), 'Optimized'))
    plan_id = cur.lastrowid
    for i, item in enumerate(selected):
        conn.execute("""
            INSERT INTO load_plan_items (load_plan_id,order_id,weight_kg,volume_cbm,sequence)
            VALUES (?,?,?,?,?)
        """, (plan_id, item['order_id'], item['weight_kg'], item['volume_cbm'], i+1))
    conn.commit()
    conn.close()
    return jsonify({'success': True, 'plan_id': plan_id, 'items': selected,
                    'total_weight_kg': total_w*1000, 'total_volume_cbm': total_v,
                    'utilization_pct': round(total_w/cap_tons*100, 1)})

@app.route('/api/load-plans/<int:pid>', methods=['GET'])
def get_load_plan(pid):
    conn = get_db()
    plan = row_to_dict(conn.execute("SELECT * FROM load_plans WHERE id=?", (pid,)).fetchone())
    if plan:
        plan['items'] = rows_to_list(conn.execute(
            "SELECT * FROM load_plan_items WHERE load_plan_id=?", (pid,)).fetchall())
    conn.close()
    return jsonify({'success': True, 'data': plan})

# ── FEATURE 5: Dispatch System ────────────────────────────────────────────────
@app.route('/api/dispatch', methods=['GET'])
def get_dispatches():
    conn = get_db()
    rows = rows_to_list(conn.execute("""
        SELECT d.*, o.customer_name, o.source_city, o.destination_city,
               v.vehicle_number, v.driver_name
        FROM dispatches d
        LEFT JOIN orders o ON d.order_id=o.id
        LEFT JOIN vehicles v ON d.vehicle_id=v.id
        ORDER BY d.created_at DESC LIMIT 100
    """).fetchall())
    conn.close()
    return jsonify({'success': True, 'data': rows})

@app.route('/api/dispatch', methods=['POST'])
def create_dispatch():
    body = request.get_json() or {}
    required = ('order_id', 'vehicle_id')
    if not all(k in body for k in required):
        return jsonify({'success': False, 'error': 'order_id and vehicle_id required'}), 400
    conn = get_db()
    conn.execute("""
        INSERT INTO dispatches (order_id,vehicle_id,driver_id,route_id,dispatcher_id,
                                dispatch_status,dispatched_at,notes)
        VALUES (?,?,?,?,?,?,?,?)
    """, (body['order_id'], body['vehicle_id'], body.get('driver_id'),
          body.get('route_id'), body.get('dispatcher_id', 'admin'),
          'Dispatched', now_iso(), body.get('notes')))
    # Update order status & vehicle assignment
    conn.execute("UPDATE orders SET order_status='In Transit', vehicle_id=?, lifecycle_stage='Dispatched' WHERE id=?",
                 (body['vehicle_id'], body['order_id']))
    conn.execute("UPDATE vehicles SET current_order_id=?, status='moving' WHERE id=?",
                 (body['order_id'], body['vehicle_id']))
    conn.commit()
    conn.close()
    log_event('user_action', f"Dispatched order {body['order_id']} to vehicle {body['vehicle_id']}",
              'dispatch', body['order_id'])
    broadcast(json.dumps({'type': 'dispatch', 'order_id': body['order_id'],
                          'vehicle_id': body['vehicle_id'], 'timestamp': now_iso()}))
    return jsonify({'success': True})

@app.route('/api/dispatch/<int:did>/status', methods=['PUT'])
def update_dispatch_status(did):
    body = request.get_json() or {}
    status = body.get('status', 'Pending')
    conn = get_db()
    conn.execute("UPDATE dispatches SET dispatch_status=? WHERE id=?", (status, did))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/api/dispatch/pending-orders', methods=['GET'])
def pending_orders_for_dispatch():
    """Orders ready to be dispatched (not yet assigned to a vehicle)."""
    conn = get_db()
    rows = rows_to_list(conn.execute("""
        SELECT id, customer_name, source_city, destination_city,
               goods_type, quantity, unit, priority_tier, weight_kg, distance_km
        FROM orders
        WHERE (order_status='Created' OR order_status='Packed' OR order_status IS NULL)
          AND vehicle_id IS NULL
        ORDER BY priority_tier DESC, dispatch_datetime ASC
        LIMIT 100
    """).fetchall())
    conn.close()
    return jsonify({'success': True, 'data': rows})

@app.route('/api/dispatch/available-vehicles', methods=['GET'])
def available_vehicles_for_dispatch():
    """Idle vehicles with no active order."""
    conn = get_db()
    rows = rows_to_list(conn.execute("""
        SELECT id, vehicle_type, vehicle_number, driver_name,
               driver_contact, capacity_tons, capacity_cbm, current_lat, current_lng
        FROM vehicles
        WHERE status='idle' AND (current_order_id IS NULL OR current_order_id='')
        ORDER BY id
    """).fetchall())
    conn.close()
    return jsonify({'success': True, 'data': rows})


# ══════════════════════════════════════════════════════════════════
#  FEATURE 6 – Driver Management
# ══════════════════════════════════════════════════════════════════

@app.route('/api/drivers', methods=['GET'])
def get_drivers():
    conn = get_db()
    rows = rows_to_list(conn.execute("""
        SELECT d.*,
               v.vehicle_number, v.vehicle_type, v.status AS vehicle_status
        FROM drivers d
        LEFT JOIN vehicles v ON v.assigned_driver_id = d.id
        ORDER BY d.name
    """).fetchall())
    conn.close()
    return jsonify({'success': True, 'data': rows})

@app.route('/api/drivers', methods=['POST'])
def create_driver():
    data = request.json or {}
    if not data.get('name'):
        return jsonify({'success': False, 'error': 'name required'}), 400
    # B-15: Use uuid to avoid the 10K-ID collision risk
    did = 'DRV-' + str(uuid.uuid4()).replace('-', '')[:8].upper()
    conn = get_db()
    conn.execute("""
        INSERT INTO drivers (id, name, contact, license_number, license_expiry,
            license_type, availability, joined_date, address, emergency_contact)
        VALUES (?,?,?,?,?,?,?,?,?,?)
    """, (did, data['name'], data.get('contact'), data.get('license_number'),
          data.get('license_expiry'), data.get('license_type','LMV'),
          data.get('availability','Available'),
          data.get('joined_date', datetime.now().date().isoformat()),
          data.get('address'), data.get('emergency_contact')))
    conn.commit(); conn.close()
    return jsonify({'success': True, 'driver_id': did})

@app.route('/api/drivers/<did>', methods=['PUT'])
def update_driver(did):
    data = request.json or {}
    conn = get_db()
    conn.execute("""
        UPDATE drivers SET availability=?, rating=?, working_hours_today=?,
            license_expiry=?, contact=?
        WHERE id=?
    """, (data.get('availability'), data.get('rating'), data.get('working_hours_today'),
          data.get('license_expiry'), data.get('contact'), did))
    conn.commit(); conn.close()
    return jsonify({'success': True})

@app.route('/api/drivers/<did>/rate', methods=['POST'])
def rate_driver(did):
    data = request.json or {}
    rating = float(data.get('rating', 5))
    conn = get_db()
    d = conn.execute('SELECT rating, rating_count FROM drivers WHERE id=?', (did,)).fetchone()
    if not d:
        conn.close()
        return jsonify({'success': False, 'error': 'Driver not found'}), 404
    new_count = (d['rating_count'] or 0) + 1
    new_rating = round(((d['rating'] or 5) * (d['rating_count'] or 0) + rating) / new_count, 2)
    conn.execute('UPDATE drivers SET rating=?, rating_count=? WHERE id=?',
                 (new_rating, new_count, did))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

# ══════════════════════════════════════════════════════════════════
#  FEATURE 7 – Proof of Delivery (POD)
# ══════════════════════════════════════════════════════════════════

@app.route('/api/pod', methods=['GET'])
def get_pods():
    status = request.args.get('status', '')
    conn = get_db()
    q = """
        SELECT o.id AS order_id, o.customer_name, o.source_city, o.destination_city,
               o.order_status, o.pod_type, o.pod_reference, o.pod_collected_at, o.pod_status,
               o.vehicle_id, o.vehicle_number
        FROM orders o
        WHERE 1=1
    """
    params = []
    if status:
        q += ' AND o.pod_status=?'; params.append(status)
    q += ' ORDER BY o.dispatch_datetime DESC LIMIT 200'
    rows = rows_to_list(conn.execute(q, params).fetchall())
    conn.close()
    return jsonify({'success': True, 'data': rows})

@app.route('/api/pod/<order_id>', methods=['POST'])
def submit_pod(order_id):
    data = request.json or {}
    conn = get_db()
    now = datetime.now().isoformat()
    # B-14: Fetch vehicle_id BEFORE the UPDATE to avoid a race condition
    v = conn.execute('SELECT vehicle_id FROM orders WHERE id=?', (order_id,)).fetchone()
    conn.execute("""
        UPDATE orders SET pod_type=?, pod_reference=?, pod_collected_at=?,
            pod_status='Collected', order_status='Delivered', actual_delivery_datetime=?,
            lifecycle_stage='Delivered'
        WHERE id=?
    """, (data.get('pod_type','Digital'), data.get('pod_reference'),
          data.get('pod_collected_at', now), now, order_id))
    # Update vehicle to idle
    if v and v['vehicle_id']:
        conn.execute("UPDATE vehicles SET status='idle', current_order_id=NULL WHERE id=?",
                     (v['vehicle_id'],))
    conn.commit(); conn.close()
    broadcast(json.dumps({'type':'pod_collected','order_id':order_id}))
    log_event('pod', f'POD collected for {order_id}', 'order', order_id)
    return jsonify({'success': True})

@app.route('/api/pod/pending', methods=['GET'])
def get_pending_pod():
    conn = get_db()
    rows = rows_to_list(conn.execute("""
        SELECT id AS order_id, customer_name, destination_city, vehicle_id,
               vehicle_number, expected_delivery_datetime, pod_status
        FROM orders
        WHERE order_status='In Transit' AND (pod_status IS NULL OR pod_status='Pending')
        ORDER BY expected_delivery_datetime
        LIMIT 100
    """).fetchall())
    conn.close()
    return jsonify({'success': True, 'data': rows})

# ══════════════════════════════════════════════════════════════════
#  FEATURE 8 – Shipment Lifecycle
# ══════════════════════════════════════════════════════════════════

LIFECYCLE_STAGES = ['Created','Picked Up','At Hub','In Transit','Out for Delivery','Delivered']

@app.route('/api/lifecycle/<order_id>', methods=['GET'])
def get_lifecycle(order_id):
    conn = get_db()
    o = conn.execute("""
        SELECT id, lifecycle_stage, order_status, dispatch_datetime,
               expected_delivery_datetime, actual_delivery_datetime,
               source_city, destination_city, customer_name
        FROM orders WHERE id=?
    """, (order_id,)).fetchone()
    conn.close()
    if not o:
        return jsonify({'success': False, 'error': 'Not found'}), 404
    o = dict(o)
    stage = o.get('lifecycle_stage') or 'Created'
    current_idx = LIFECYCLE_STAGES.index(stage) if stage in LIFECYCLE_STAGES else 0
    o['stages'] = [{'name': s, 'status': ('done' if i < current_idx else ('current' if i == current_idx else 'pending'))}
                   for i, s in enumerate(LIFECYCLE_STAGES)]
    return jsonify({'success': True, 'data': o})

@app.route('/api/lifecycle/<order_id>', methods=['PUT'])
def advance_lifecycle(order_id):
    data = request.json or {}
    stage = data.get('stage')
    if stage not in LIFECYCLE_STAGES:
        return jsonify({'success': False, 'error': 'Invalid stage'}), 400
    conn = get_db()
    conn.execute('UPDATE orders SET lifecycle_stage=? WHERE id=?', (stage, order_id))
    if stage == 'Delivered':
        conn.execute("UPDATE orders SET order_status='Delivered', actual_delivery_datetime=? WHERE id=?",
                     (datetime.now().isoformat(), order_id))
    conn.commit(); conn.close()
    broadcast(json.dumps({'type':'lifecycle_update','order_id':order_id,'stage':stage}))
    return jsonify({'success': True})

@app.route('/api/lifecycle', methods=['GET'])
def get_all_lifecycles():
    conn = get_db()
    rows = rows_to_list(conn.execute("""
        SELECT id AS order_id, customer_name, source_city, destination_city,
               lifecycle_stage, order_status, dispatch_datetime,
               expected_delivery_datetime
        FROM orders ORDER BY dispatch_datetime DESC LIMIT 200
    """).fetchall())
    conn.close()
    return jsonify({'success': True, 'data': rows, 'stages': LIFECYCLE_STAGES})

# ══════════════════════════════════════════════════════════════════
#  FEATURE 9 – Exception Handling
# ══════════════════════════════════════════════════════════════════

@app.route('/api/incidents', methods=['GET'])
def get_incidents():
    sev = request.args.get('severity', '')
    conn = get_db()
    q = 'SELECT * FROM incidents WHERE 1=1'
    params = []
    if sev:
        q += ' AND severity=?'; params.append(sev)
    q += ' ORDER BY reported_at DESC LIMIT 200'
    rows = rows_to_list(conn.execute(q, params).fetchall())
    conn.close()
    return jsonify({'success': True, 'data': rows})

@app.route('/api/incidents', methods=['POST'])
def create_incident():
    data = request.json or {}
    if not data.get('incident_type'):
        return jsonify({'success': False, 'error': 'incident_type required'}), 400
    conn = get_db()
    cur = conn.execute("""
        INSERT INTO incidents (order_id, vehicle_id, incident_type, description,
            location, severity, damage_value_inr, is_insured, claim_status)
        VALUES (?,?,?,?,?,?,?,?,?)
    """, (data.get('order_id'), data.get('vehicle_id'), data['incident_type'],
          data.get('description'), data.get('location'),
          data.get('severity','Medium'), data.get('damage_value_inr',0),
          1 if data.get('is_insured') else 0,
          data.get('claim_status','Not Filed')))
    iid = cur.lastrowid
    # Create a linked alert
    if data.get('order_id') or data.get('vehicle_id'):
        conn.execute("""
            INSERT INTO alerts (order_id, vehicle_id, alert_type, alert_reason, severity)
            VALUES (?,?,?,?,?)
        """, (data.get('order_id'), data.get('vehicle_id'),
              'Incident', data.get('description','Incident reported'),
              data.get('severity','Medium')))
    conn.commit(); conn.close()
    broadcast(json.dumps({'type':'incident','incident_id':iid,'severity':data.get('severity','Medium')}))
    return jsonify({'success': True, 'incident_id': iid})

@app.route('/api/incidents/<int:iid>/resolve', methods=['POST'])
def resolve_incident(iid):
    data = request.json or {}
    conn = get_db()
    conn.execute("""
        UPDATE incidents SET resolved_at=?, claim_status=?
        WHERE id=?
    """, (datetime.now().isoformat(), data.get('claim_status','Resolved'), iid))
    conn.commit(); conn.close()
    return jsonify({'success': True})

# ══════════════════════════════════════════════════════════════════
#  FEATURE 10 – Cost Tracking
# ══════════════════════════════════════════════════════════════════

@app.route('/api/costs', methods=['GET'])
def get_costs():
    conn = get_db()
    rows = rows_to_list(conn.execute("""
        SELECT id AS order_id, customer_name, source_city, destination_city,
               transport_cost_inr, fuel_cost_inr, toll_cost_inr,
               maintenance_cost_inr, other_cost_inr,
               (COALESCE(transport_cost_inr,0)+COALESCE(fuel_cost_inr,0)+
                COALESCE(toll_cost_inr,0)+COALESCE(maintenance_cost_inr,0)+
                COALESCE(other_cost_inr,0)) AS total_cost_inr,
               order_status, dispatch_datetime
        FROM orders ORDER BY dispatch_datetime DESC LIMIT 300
    """).fetchall())
    totals = conn.execute("""
        SELECT SUM(transport_cost_inr) AS transport,
               SUM(fuel_cost_inr) AS fuel,
               SUM(toll_cost_inr) AS toll,
               SUM(maintenance_cost_inr) AS maintenance,
               SUM(other_cost_inr) AS other
        FROM orders
    """).fetchone()
    conn.close()
    return jsonify({'success': True, 'data': rows, 'totals': dict(totals) if totals else {}})

@app.route('/api/costs/<order_id>', methods=['PUT'])
def update_costs(order_id):
    data = request.json or {}
    conn = get_db()
    conn.execute("""
        UPDATE orders SET fuel_cost_inr=?, toll_cost_inr=?,
            maintenance_cost_inr=?, other_cost_inr=?
        WHERE id=?
    """, (data.get('fuel_cost_inr',0), data.get('toll_cost_inr',0),
          data.get('maintenance_cost_inr',0), data.get('other_cost_inr',0), order_id))
    conn.commit(); conn.close()
    return jsonify({'success': True})

@app.route('/api/costs/summary', methods=['GET'])
def cost_summary():
    conn = get_db()
    by_route = rows_to_list(conn.execute("""
        SELECT source_city, destination_city,
               COUNT(*) AS trips,
               ROUND(AVG(COALESCE(transport_cost_inr,0)+COALESCE(fuel_cost_inr,0)+
                   COALESCE(toll_cost_inr,0)),0) AS avg_total_inr,
               ROUND(SUM(COALESCE(transport_cost_inr,0)+COALESCE(fuel_cost_inr,0)+
                   COALESCE(toll_cost_inr,0)),0) AS sum_total_inr
        FROM orders GROUP BY source_city, destination_city
        ORDER BY sum_total_inr DESC LIMIT 20
    """).fetchall())
    conn.close()
    return jsonify({'success': True, 'data': by_route})

# ══════════════════════════════════════════════════════════════════
#  FEATURE 11 – Vehicle Telemetry
# ══════════════════════════════════════════════════════════════════

@app.route('/api/telemetry', methods=['GET'])
def get_telemetry():
    conn = get_db()
    rows = rows_to_list(conn.execute("""
        SELECT id, vehicle_type, vehicle_number, driver_name, status,
               fuel_level_pct, odometer_km, engine_temp_c, engine_health,
               current_speed, current_lat, current_lng, last_updated
        FROM vehicles ORDER BY id
    """).fetchall())
    conn.close()
    return jsonify({'success': True, 'data': rows})

@app.route('/api/telemetry/<vid>', methods=['GET'])
def get_vehicle_telemetry(vid):
    conn = get_db()
    # B-13: Check vehicle exists BEFORE running extra queries
    v = conn.execute('SELECT * FROM vehicles WHERE id=?', (vid,)).fetchone()
    if not v:
        conn.close()
        return jsonify({'success': False, 'error': 'Not found'}), 404
    fuel_history = rows_to_list(conn.execute("""
        SELECT * FROM fuel_logs WHERE vehicle_id=? ORDER BY logged_at DESC LIMIT 10
    """, (vid,)).fetchall())
    positions = rows_to_list(conn.execute("""
        SELECT lat, lng, speed, recorded_at FROM vehicle_positions
        WHERE vehicle_id=? ORDER BY recorded_at DESC LIMIT 50
    """, (vid,)).fetchall())
    conn.close()
    return jsonify({'success': True, 'data': dict(v),
                    'fuel_history': fuel_history, 'positions': positions})

@app.route('/api/telemetry/<vid>', methods=['PUT'])
def update_telemetry(vid):
    data = request.json or {}
    conn = get_db()
    conn.execute("""
        UPDATE vehicles SET fuel_level_pct=?, engine_temp_c=?,
            engine_health=?, odometer_km=?
        WHERE id=?
    """, (data.get('fuel_level_pct'), data.get('engine_temp_c'),
          data.get('engine_health','Good'), data.get('odometer_km'), vid))
    if data.get('fuel_consumed_liters'):
        conn.execute("""
            INSERT INTO fuel_logs (vehicle_id, liters_consumed, cost_inr,
                odometer_km, fuel_efficiency_kmpl)
            VALUES (?,?,?,?,?)
        """, (vid, data.get('fuel_consumed_liters'), data.get('fuel_cost_inr'),
              data.get('odometer_km'), data.get('fuel_efficiency_kmpl')))
    conn.commit(); conn.close()
    return jsonify({'success': True})

# ══════════════════════════════════════════════════════════════════
#  FEATURE 12 – Multi-Hub Logistics
# ══════════════════════════════════════════════════════════════════

@app.route('/api/hubs', methods=['GET'])
def get_hubs():
    conn = get_db()
    hubs = rows_to_list(conn.execute("""
        SELECT w.*, COUNT(i.id) AS inventory_count,
               COUNT(DISTINCT ht.id) AS transfers_in_progress
        FROM warehouses w
        LEFT JOIN inventory i ON i.warehouse_id=w.id AND i.status='stored'
        LEFT JOIN hub_transfers ht ON (ht.from_hub_id=w.id OR ht.to_hub_id=w.id)
            AND ht.transfer_status='In Transit'
        WHERE w.is_hub=1
        GROUP BY w.id
    """).fetchall())
    conn.close()
    return jsonify({'success': True, 'data': hubs})

@app.route('/api/hubs/transfers', methods=['GET'])
def get_hub_transfers():
    conn = get_db()
    rows = rows_to_list(conn.execute("""
        SELECT ht.*, o.customer_name, o.goods_type, o.source_city, o.destination_city,
               wf.name AS from_hub_name, wt.name AS to_hub_name
        FROM hub_transfers ht
        LEFT JOIN orders o ON o.id=ht.order_id
        LEFT JOIN warehouses wf ON wf.id=ht.from_hub_id
        LEFT JOIN warehouses wt ON wt.id=ht.to_hub_id
        ORDER BY ht.created_at DESC LIMIT 100
    """).fetchall())
    conn.close()
    return jsonify({'success': True, 'data': rows})

@app.route('/api/hubs/transfers', methods=['POST'])
def create_hub_transfer():
    data = request.json or {}
    conn = get_db()
    cur = conn.execute("""
        INSERT INTO hub_transfers (order_id, from_hub_id, to_hub_id,
            transfer_status, sort_lane)
        VALUES (?,?,?,?,?)
    """, (data.get('order_id'), data.get('from_hub_id'), data.get('to_hub_id'),
          'Pending', data.get('sort_lane')))
    tid = cur.lastrowid
    conn.execute("UPDATE orders SET hub_id=? WHERE id=?",
                 (data.get('to_hub_id'), data.get('order_id')))
    conn.commit(); conn.close()
    return jsonify({'success': True, 'transfer_id': tid})

@app.route('/api/hubs/transfers/<int:tid>', methods=['PUT'])
def update_hub_transfer(tid):
    data = request.json or {}
    status = data.get('status', 'In Transit')
    now = datetime.now().isoformat()
    conn = get_db()
    if status == 'Arrived':
        conn.execute('UPDATE hub_transfers SET transfer_status=?, arrived_at=? WHERE id=?',
                     (status, now, tid))
    elif status == 'Departed':
        conn.execute('UPDATE hub_transfers SET transfer_status=?, departed_at=? WHERE id=?',
                     ('In Transit', now, tid))
    else:
        conn.execute('UPDATE hub_transfers SET transfer_status=? WHERE id=?', (status, tid))
    conn.commit(); conn.close()
    return jsonify({'success': True})

# ══════════════════════════════════════════════════════════════════
#  FEATURE 13 – Reverse Logistics
# ══════════════════════════════════════════════════════════════════

@app.route('/api/returns', methods=['GET'])
def get_returns():
    conn = get_db()
    rows = rows_to_list(conn.execute("""
        SELECT o.*, p.customer_name AS parent_customer,
               p.destination_city AS return_from_city
        FROM orders o
        LEFT JOIN orders p ON p.id=o.parent_order_id
        WHERE o.is_return=1
        ORDER BY o.dispatch_datetime DESC LIMIT 100
    """).fetchall())
    conn.close()
    return jsonify({'success': True, 'data': rows})

@app.route('/api/returns', methods=['POST'])
def create_return():
    data = request.json or {}
    parent_id = data.get('parent_order_id')
    if not parent_id:
        return jsonify({'success': False, 'error': 'parent_order_id required'}), 400
    conn = get_db()
    parent = conn.execute('SELECT * FROM orders WHERE id=?', (parent_id,)).fetchone()
    if not parent:
        conn.close(); return jsonify({'success': False, 'error': 'Parent order not found'}), 404
    # B-25: Add uuid suffix to prevent collision if same order is returned twice
    rid = f"RET-{parent_id}-{str(uuid.uuid4())[:6].upper()}"
    try:
        conn.execute("""
            INSERT INTO orders (id, customer_name, customer_contact, source_city, destination_city,
                goods_type, quantity, unit, vehicle_id, order_status, is_return,
                parent_order_id, lifecycle_stage, priority_tier, dispatch_datetime,
                goods_category, pickup_address, delivery_address)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (rid, parent['customer_name'], parent['customer_contact'],
              parent['destination_city'], parent['source_city'],
              parent['goods_type'], parent['quantity'], parent['unit'],
              data.get('vehicle_id'), 'Pending', 1, parent_id, 'Created',
              data.get('priority_tier','Economy'),
              datetime.now().isoformat(),
              parent['goods_category'],
              parent['delivery_address'], parent['pickup_address']))
    except Exception as e:
        conn.close(); return jsonify({'success': False, 'error': str(e)}), 400
    conn.commit(); conn.close()
    return jsonify({'success': True, 'return_order_id': rid})

# ══════════════════════════════════════════════════════════════════
#  FEATURE 14 – SLA Monitoring
# ══════════════════════════════════════════════════════════════════

@app.route('/api/sla', methods=['GET'])
def get_sla():
    conn = get_db()
    rows = rows_to_list(conn.execute("""
        SELECT o.id AS order_id, o.customer_name, o.source_city, o.destination_city,
               o.order_status, o.priority_tier,
               o.expected_delivery_datetime AS sla_deadline,
               o.actual_delivery_datetime,
               o.sla_breached,
               CASE
                 WHEN o.order_status='Delivered' AND o.actual_delivery_datetime <= o.expected_delivery_datetime
                   THEN 'on-time'
                 WHEN o.order_status='Delivered' AND o.actual_delivery_datetime > o.expected_delivery_datetime
                   THEN 'breached'
                 WHEN o.order_status != 'Delivered' AND datetime('now') > o.expected_delivery_datetime
                   THEN 'breached'
                 WHEN o.order_status != 'Delivered' AND
                      (julianday(o.expected_delivery_datetime) - julianday('now')) < 0.25
                   THEN 'at-risk'
                 ELSE 'on-time'
               END AS sla_status
        FROM orders o
        WHERE o.expected_delivery_datetime IS NOT NULL
        ORDER BY o.expected_delivery_datetime DESC LIMIT 200
    """).fetchall())
    summary = {
        'total': len(rows),
        'on_time': sum(1 for r in rows if r['sla_status'] == 'on-time'),
        'breached': sum(1 for r in rows if r['sla_status'] == 'breached'),
        'at_risk': sum(1 for r in rows if r['sla_status'] == 'at-risk'),
    }
    summary['on_time_pct'] = round(summary['on_time'] / summary['total'] * 100, 1) if summary['total'] else 0
    conn.close()
    return jsonify({'success': True, 'data': rows, 'summary': summary})

@app.route('/api/sla/<order_id>', methods=['PUT'])
def update_sla(order_id):
    data = request.json or {}
    conn = get_db()
    conn.execute("""
        UPDATE orders SET sla_deadline=?, sla_breached=? WHERE id=?
    """, (data.get('sla_deadline'), 1 if data.get('sla_breached') else 0, order_id))
    conn.commit(); conn.close()
    return jsonify({'success': True})

# ══════════════════════════════════════════════════════════════════
#  FEATURE 15 – Performance Analytics / KPIs
# ══════════════════════════════════════════════════════════════════

@app.route('/api/kpis', methods=['GET'])
def get_kpis():
    conn = get_db()
    totals = dict(conn.execute("""
        SELECT COUNT(*) AS total_orders,
               SUM(order_status='Delivered') AS delivered,
               SUM(order_status='In Transit') AS in_transit,
               SUM(order_status='Pending') AS pending,
               ROUND(AVG(distance_km),1) AS avg_distance_km,
               ROUND(SUM(COALESCE(transport_cost_inr,0)),0) AS total_revenue,
               ROUND(AVG(COALESCE(transport_cost_inr,0)),0) AS avg_revenue_per_order
        FROM orders
    """).fetchone())

    vehicles_kpi = dict(conn.execute("""
        SELECT COUNT(*) AS total_vehicles,
               SUM(status='moving') AS moving,
               SUM(status='idle') AS idle
        FROM vehicles
    """).fetchone())

    sla_kpi = dict(conn.execute("""
        SELECT COUNT(*) AS sla_total,
               SUM(CASE WHEN (order_status='Delivered' AND actual_delivery_datetime <= expected_delivery_datetime)
                   OR (order_status != 'Delivered' AND datetime('now') <= expected_delivery_datetime)
                   THEN 1 ELSE 0 END) AS on_time
        FROM orders WHERE expected_delivery_datetime IS NOT NULL
    """).fetchone())

    route_perf = rows_to_list(conn.execute("""
        SELECT source_city, destination_city, COUNT(*) AS trips,
               SUM(order_status='Delivered') AS delivered,
               ROUND(AVG(distance_km),0) AS avg_km,
               ROUND(AVG(COALESCE(transport_cost_inr,0)),0) AS avg_cost
        FROM orders
        GROUP BY source_city, destination_city
        ORDER BY trips DESC LIMIT 10
    """).fetchall())

    driver_perf = rows_to_list(conn.execute("""
        SELECT d.name, d.rating, d.total_trips, d.working_hours_today,
               d.availability, v.vehicle_number,
               COUNT(o.id) AS active_orders
        FROM drivers d
        LEFT JOIN vehicles v ON v.assigned_driver_id=d.id
        LEFT JOIN orders o ON o.vehicle_id=v.id AND o.order_status='In Transit'
        GROUP BY d.id ORDER BY d.rating DESC LIMIT 10
    """).fetchall())

    conn.close()

    sla_pct = round(sla_kpi['on_time'] / sla_kpi['sla_total'] * 100, 1) if sla_kpi.get('sla_total') else 0

    return jsonify({
        'success': True,
        'totals': totals,
        'vehicles': vehicles_kpi,
        'sla': {**sla_kpi, 'on_time_pct': sla_pct},
        'route_performance': route_perf,
        'driver_performance': driver_perf,
    })

# ─────────────────────────────────────────────────────────────────────────────


# ══════════════════════════════════════════════════════════════════
#  FEATURE 16 – Customer Management
# ══════════════════════════════════════════════════════════════════

@app.route('/api/customers', methods=['GET'])
def get_customers():
    conn = get_db()
    search = request.args.get('q', '').strip()
    q = """
        SELECT c.*,
               COUNT(o.id) AS total_orders,
               SUM(COALESCE(o.transport_cost_inr,0)) AS total_revenue,
               MAX(o.dispatch_datetime) AS last_order_date,
               SUM(CASE WHEN o.order_status='In Transit' THEN 1 ELSE 0 END) AS active_orders
        FROM clients c
        LEFT JOIN orders o ON o.customer_name=c.name OR o.client_id=c.id
        WHERE 1=1
    """
    params = []
    if search:
        q += ' AND (c.name LIKE ? OR c.company LIKE ? OR c.email LIKE ?)'
        params += [f'%{search}%', f'%{search}%', f'%{search}%']
    q += ' GROUP BY c.id ORDER BY total_revenue DESC LIMIT 200'
    rows = rows_to_list(conn.execute(q, params).fetchall())
    conn.close()
    return jsonify({'success': True, 'data': rows})

@app.route('/api/customers', methods=['POST'])
def create_customer():
    data = request.json or {}
    if not data.get('name'):
        return jsonify({'success': False, 'error': 'name required'}), 400
    conn = get_db()
    cur = conn.execute("""
        INSERT INTO clients (name, company, email, phone, address, city,
            gstin, credit_limit_inr, payment_terms_days, account_status)
        VALUES (?,?,?,?,?,?,?,?,?,?)
    """, (data['name'], data.get('company'), data.get('email'), data.get('phone'),
          data.get('address'), data.get('city'),
          data.get('gstin'), data.get('credit_limit_inr', 500000),
          data.get('payment_terms_days', 30), data.get('account_status', 'Active')))
    cid = cur.lastrowid
    conn.commit(); conn.close()
    return jsonify({'success': True, 'client_id': cid})

@app.route('/api/customers/<int:cid>', methods=['PUT'])
def update_customer(cid):
    import traceback as _tb
    try:
        data = request.get_json(force=True, silent=True) or {}
        if data.get('_delete'):
            conn = get_db()
            row = conn.execute('SELECT id FROM clients WHERE id=?', (cid,)).fetchone()
            if not row:
                conn.close()
                return jsonify({'success': False, 'error': 'Customer not found'}), 404
            conn.execute('DELETE FROM clients WHERE id=?', (cid,))
            conn.commit()
            conn.close()
            return jsonify({'success': True, 'deleted': True})
        conn = get_db()
        conn.execute("""
            UPDATE clients SET name=?, company=?, email=?, phone=?,
                credit_limit_inr=?, payment_terms_days=?, account_status=?
            WHERE id=?
        """, (data.get('name'), data.get('company'), data.get('email'), data.get('phone'),
              data.get('credit_limit_inr'), data.get('payment_terms_days'),
              data.get('account_status'), cid))
        conn.commit()
        conn.close()
        return jsonify({'success': True})
    except Exception as ex:
        _tb.print_exc()
        return jsonify({'success': False, 'error': str(ex)}), 500

@app.route('/api/customers/<int:cid>/orders', methods=['GET'])
def get_customer_orders(cid):
    conn = get_db()
    client = conn.execute('SELECT * FROM clients WHERE id=?', (cid,)).fetchone()
    if not client:
        conn.close(); return jsonify({'success': False, 'error': 'Not found'}), 404
    orders = rows_to_list(conn.execute("""
        SELECT id, source_city, destination_city, goods_type, order_status,
               dispatch_datetime, transport_cost_inr, lifecycle_stage
        FROM orders WHERE customer_name=? ORDER BY dispatch_datetime DESC LIMIT 50
    """, (client['name'],)).fetchall())
    conn.close()
    return jsonify({'success': True, 'client': dict(client), 'orders': orders})

# ══════════════════════════════════════════════════════════════════
#  FEATURE 17 – Billing & Invoicing
# ══════════════════════════════════════════════════════════════════

@app.route('/api/invoices', methods=['GET'])
def get_invoices():
    status = request.args.get('status', '')
    conn = get_db()
    q = 'SELECT * FROM invoices WHERE 1=1'
    params = []
    # B-07: Schema column is 'status', not 'payment_status'
    if status:
        q += ' AND status=?'; params.append(status)
    q += ' ORDER BY created_at DESC LIMIT 200'
    rows = rows_to_list(conn.execute(q, params).fetchall())
    conn.close()
    return jsonify({'success': True, 'data': rows})

@app.route('/api/invoices', methods=['POST'])
def create_invoice():
    data = request.json or {}
    if not data.get('order_id'):
        return jsonify({'success': False, 'error': 'order_id required'}), 400
    conn = get_db()
    order = row_to_dict(conn.execute('SELECT * FROM orders WHERE id=?', (data['order_id'],)).fetchone())
    if not order:
        conn.close(); return jsonify({'success': False, 'error': 'Order not found'}), 404
    # B-06: Column names must match the 'invoices' schema (id, client_id, order_id,
    #        invoice_date, due_date, subtotal_inr, tax_inr, total_inr, status)
    inv_no = f"INV-{datetime.now().strftime('%Y%m')}-{random.randint(1000,9999)}"
    base  = float(order['transport_cost_inr'] or 0)
    tax   = round(base * 0.18, 2)
    total = round(base + tax, 2)
    cur = conn.execute("""
        INSERT INTO invoices (id, order_id, client_id,
            invoice_date, due_date,
            subtotal_inr, tax_inr, total_inr, status)
        VALUES (?,?,?,?,?,?,?,?,?)
    """, (inv_no, data['order_id'], order.get('client_id'),
          datetime.now().strftime('%Y-%m-%d'),
          data.get('due_date', datetime.now().strftime('%Y-%m-%d')),
          base, tax, total, 'Draft'))
    iid = cur.lastrowid
    conn.commit(); conn.close()
    return jsonify({'success': True, 'invoice_id': inv_no, 'invoice_number': inv_no,
                    'total': total})

@app.route('/api/invoices/<iid>/pay', methods=['POST'])
def mark_invoice_paid(iid):
    data = request.get_json(silent=True) or {}
    conn = get_db()
    # B-06/B-07: Schema uses 'status' and 'paid_at'; no payment_method column
    conn.execute("""
        UPDATE invoices SET status='Paid', paid_at=?
        WHERE id=?
    """, (datetime.now().isoformat(), iid))
    conn.commit(); conn.close()
    return jsonify({'success': True})

@app.route('/api/invoices/summary', methods=['GET'])
def invoice_summary():
    conn = get_db()
    # B-06/B-07: Use correct schema column names (status, total_inr)
    s = dict(conn.execute("""
        SELECT COUNT(*) AS total,
               SUM(CASE WHEN status='Paid' THEN 1 ELSE 0 END) AS paid,
               SUM(CASE WHEN status='Draft' OR status='Unpaid' THEN 1 ELSE 0 END) AS unpaid,
               SUM(CASE WHEN status='Overdue' THEN 1 ELSE 0 END) AS overdue,
               ROUND(SUM(total_inr),0) AS total_revenue,
               ROUND(SUM(CASE WHEN status='Draft' OR status='Unpaid' THEN total_inr ELSE 0 END),0) AS outstanding
        FROM invoices
    """).fetchone())
    conn.close()
    return jsonify({'success': True, 'data': s})

# ══════════════════════════════════════════════════════════════════
#  FEATURE 18 – Fuel Management
# ══════════════════════════════════════════════════════════════════

@app.route('/api/fuel', methods=['GET'])
def get_fuel_logs():
    vid = request.args.get('vehicle_id', '')
    conn = get_db()
    q = 'SELECT f.*, v.vehicle_number, v.driver_name FROM fuel_logs f LEFT JOIN vehicles v ON v.id=f.vehicle_id WHERE 1=1'
    params = []
    if vid:
        q += ' AND f.vehicle_id=?'; params.append(vid)
    q += ' ORDER BY f.logged_at DESC LIMIT 300'
    rows = rows_to_list(conn.execute(q, params).fetchall())
    summary = dict(conn.execute("""
        SELECT ROUND(SUM(liters_consumed),1) AS total_liters,
               ROUND(SUM(cost_inr),0) AS total_cost,
               ROUND(AVG(fuel_efficiency_kmpl),2) AS avg_efficiency
        FROM fuel_logs
    """).fetchone())
    conn.close()
    return jsonify({'success': True, 'data': rows, 'summary': summary})

@app.route('/api/fuel', methods=['POST'])
def log_fuel():
    data = request.json or {}
    if not data.get('vehicle_id') or not data.get('liters_consumed'):
        return jsonify({'success': False, 'error': 'vehicle_id and liters_consumed required'}), 400
    conn = get_db()
    # Bug B fix: 'fuel_station' does not exist in the fuel_logs schema — removed
    conn.execute("""
        INSERT INTO fuel_logs (vehicle_id, liters_consumed, cost_inr,
            odometer_km, fuel_efficiency_kmpl)
        VALUES (?,?,?,?,?)
    """, (data['vehicle_id'], data['liters_consumed'], data.get('cost_inr'),
          data.get('odometer_km'), data.get('fuel_efficiency_kmpl')))
    # Update vehicle fuel level
    if data.get('fuel_level_pct'):
        conn.execute('UPDATE vehicles SET fuel_level_pct=? WHERE id=?',
                     (data['fuel_level_pct'], data['vehicle_id']))
    conn.commit(); conn.close()
    return jsonify({'success': True})

@app.route('/api/fuel/analytics', methods=['GET'])
def fuel_analytics():
    conn = get_db()
    by_vehicle = rows_to_list(conn.execute("""
        SELECT f.vehicle_id, v.vehicle_number, v.vehicle_type,
               ROUND(SUM(f.liters_consumed),1) AS total_liters,
               ROUND(SUM(f.cost_inr),0) AS total_cost,
               ROUND(AVG(f.fuel_efficiency_kmpl),2) AS avg_kmpl,
               COUNT(*) AS fill_ups
        FROM fuel_logs f
        LEFT JOIN vehicles v ON v.id=f.vehicle_id
        GROUP BY f.vehicle_id ORDER BY total_cost DESC LIMIT 20
    """).fetchall())
    conn.close()
    return jsonify({'success': True, 'data': by_vehicle})

# ══════════════════════════════════════════════════════════════════
#  FEATURE 19 – Compliance & Documents
# ══════════════════════════════════════════════════════════════════

@app.route('/api/compliance', methods=['GET'])
def get_compliance():
    conn = get_db()
    rows = rows_to_list(conn.execute("""
        SELECT v.id AS vehicle_id, v.vehicle_number, v.vehicle_type,
               v.insurance_expiry, v.permit_expiry, v.fitness_expiry,
               v.pollution_expiry, v.driver_name,
               d.license_expiry AS driver_license_expiry,
               CASE WHEN v.insurance_expiry < date('now','+30 days') THEN 1 ELSE 0 END AS insurance_alert,
               CASE WHEN v.permit_expiry < date('now','+30 days') THEN 1 ELSE 0 END AS permit_alert,
               CASE WHEN v.fitness_expiry < date('now','+30 days') THEN 1 ELSE 0 END AS fitness_alert
        FROM vehicles v
        LEFT JOIN drivers d ON d.id=v.assigned_driver_id
        ORDER BY v.id
    """).fetchall())
    conn.close()
    alerts = sum(1 for r in rows if r.get('insurance_alert') or r.get('permit_alert') or r.get('fitness_alert'))
    return jsonify({'success': True, 'data': rows, 'alert_count': alerts})

@app.route('/api/compliance/<vid>', methods=['PUT'])
def update_compliance(vid):
    data = request.json or {}
    conn = get_db()
    conn.execute("""
        UPDATE vehicles SET insurance_expiry=?, permit_expiry=?,
            fitness_expiry=?, pollution_expiry=?
        WHERE id=?
    """, (data.get('insurance_expiry'), data.get('permit_expiry'),
          data.get('fitness_expiry'), data.get('pollution_expiry'), vid))
    conn.commit(); conn.close()
    log_event('compliance', f'Compliance updated for {vid}', 'vehicle', vid)
    return jsonify({'success': True})

@app.route('/api/compliance/expiring', methods=['GET'])
def get_expiring_docs():
    # B-08: Use parameterized query to prevent SQL injection
    try:
        days = int(request.args.get('days', 30))
        if not (0 <= days <= 3650):
            raise ValueError
    except (ValueError, TypeError):
        return jsonify({'success': False, 'error': 'days must be an integer 0–3650'}), 400
    conn = get_db()
    days_param = f'+{days} days'
    rows = rows_to_list(conn.execute("""
        SELECT vehicle_id, vehicle_number, doc_type, expiry_date,
               julianday(expiry_date) - julianday('now') AS days_remaining
        FROM (
            SELECT id AS vehicle_id, vehicle_number,
                   'Insurance' AS doc_type, insurance_expiry AS expiry_date FROM vehicles
            UNION ALL
            SELECT id, vehicle_number, 'Permit', permit_expiry FROM vehicles
            UNION ALL
            SELECT id, vehicle_number, 'Fitness', fitness_expiry FROM vehicles
            UNION ALL
            SELECT id, vehicle_number, 'Pollution', pollution_expiry FROM vehicles
        ) WHERE expiry_date IS NOT NULL AND expiry_date <= date('now', ?)
        ORDER BY expiry_date
    """, (days_param,)).fetchall())
    conn.close()
    return jsonify({'success': True, 'data': rows})

# ══════════════════════════════════════════════════════════════════
#  FEATURE 20 – GPS Geofencing
# ══════════════════════════════════════════════════════════════════

@app.route('/api/geofences', methods=['GET'])
def get_geofences():
    conn = get_db()
    rows = rows_to_list(conn.execute('SELECT * FROM geofences ORDER BY name').fetchall())
    conn.close()
    return jsonify({'success': True, 'data': rows})

@app.route('/api/geofences', methods=['POST'])
def create_geofence():
    data = request.json or {}
    if not data.get('name') or data.get('lat') is None:
        return jsonify({'success': False, 'error': 'name, lat, lng required'}), 400
    conn = get_db()
    # B-05: Use correct schema column names: center_lat, center_lng, is_active
    cur = conn.execute("""
        INSERT INTO geofences (name, zone_type, center_lat, center_lng, radius_km, is_active)
        VALUES (?,?,?,?,?,1)
    """, (data['name'], data.get('zone_type', 'Delivery Zone'),
          data['lat'], data['lng'], data.get('radius_km', 5.0)))
    gid = cur.lastrowid
    conn.commit(); conn.close()
    return jsonify({'success': True, 'geofence_id': gid})

@app.route('/api/geofences/<int:gid>', methods=['DELETE'])
def delete_geofence(gid):
    conn = get_db()
    # B-05: Schema uses is_active, not active
    conn.execute('UPDATE geofences SET is_active=0 WHERE id=?', (gid,))
    conn.commit(); conn.close()
    return jsonify({'success': True})

def _haversine_km(lat1, lon1, lat2, lon2):
    """Accurate great-circle distance in km (B-21: replaces flat-earth approx)."""
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

@app.route('/api/geofences/check', methods=['GET'])
def check_geofence_violations():
    """Check which vehicles are outside their expected geofences."""
    conn = get_db()
    # B-05: Schema uses is_active, center_lat, center_lng
    geofences = rows_to_list(conn.execute('SELECT * FROM geofences WHERE is_active=1').fetchall())
    vehicles  = rows_to_list(conn.execute("""
        SELECT id, vehicle_number, current_lat, current_lng, status, current_order_id
        FROM vehicles WHERE current_lat IS NOT NULL AND current_lng IS NOT NULL
    """).fetchall())
    violations = []
    for v in vehicles:
        for g in geofences:
            # B-21: Use Haversine for accurate distance across India
            dist = _haversine_km(
                v['current_lat'], v['current_lng'],
                g.get('center_lat') or g.get('lat', 0),
                g.get('center_lng') or g.get('lng', 0)
            )
            if dist > (g['radius_km'] or 5):
                violations.append({
                    'vehicle_id': v['id'],
                    'vehicle_number': v['vehicle_number'],
                    'geofence': g['name'],
                    'distance_km': round(dist, 2),
                    'limit_km': g['radius_km'],
                })
    conn.close()
    return jsonify({'success': True, 'geofences': geofences, 'vehicles': vehicles, 'violations': violations})

# ══════════════════════════════════════════════════════════════════
#  FEATURE 21 – Maintenance Scheduling
# ══════════════════════════════════════════════════════════════════

@app.route('/api/maintenance/schedule', methods=['GET'])
def get_maintenance_schedule():
    conn = get_db()
    rows = rows_to_list(conn.execute("""
        SELECT ms.*, v.vehicle_number, v.vehicle_type, v.driver_name
        FROM maintenance_schedule ms
        LEFT JOIN vehicles v ON v.id=ms.vehicle_id
        ORDER BY ms.scheduled_date
    """).fetchall())
    conn.close()
    return jsonify({'success': True, 'data': rows})

@app.route('/api/maintenance/schedule', methods=['POST'])
def create_maintenance_schedule():
    data = request.json or {}
    if not data.get('vehicle_id') or not data.get('scheduled_date'):
        return jsonify({'success': False, 'error': 'vehicle_id and scheduled_date required'}), 400
    conn = get_db()
    cur = conn.execute("""
        INSERT INTO maintenance_schedule
            (vehicle_id, maintenance_type, scheduled_date, estimated_cost_inr,
             vendor, notes, status)
        VALUES (?,?,?,?,?,?,?)
    """, (data['vehicle_id'], data.get('maintenance_type', 'Routine Service'),
          data['scheduled_date'], data.get('estimated_cost_inr', 0),
          data.get('vendor'), data.get('notes'), 'Scheduled'))
    sid = cur.lastrowid
    conn.commit(); conn.close()
    return jsonify({'success': True, 'schedule_id': sid})

@app.route('/api/maintenance/schedule/<int:sid>', methods=['PUT'])
def update_maintenance_schedule(sid):
    data = request.json or {}
    conn = get_db()
    conn.execute("""
        UPDATE maintenance_schedule SET status=?, actual_cost_inr=?, completed_at=?
        WHERE id=?
    """, (data.get('status', 'Completed'),
          data.get('actual_cost_inr'),
          datetime.now().isoformat() if data.get('status') == 'Completed' else None,
          sid))
    conn.commit(); conn.close()
    return jsonify({'success': True})

@app.route('/api/maintenance/upcoming', methods=['GET'])
def get_upcoming_maintenance():
    conn = get_db()
    rows = rows_to_list(conn.execute("""
        SELECT ms.*, v.vehicle_number, v.vehicle_type,
               julianday(ms.scheduled_date) - julianday('now') AS days_until
        FROM maintenance_schedule ms
        LEFT JOIN vehicles v ON v.id=ms.vehicle_id
        WHERE ms.status='Scheduled' AND ms.scheduled_date >= date('now')
        ORDER BY ms.scheduled_date LIMIT 20
    """).fetchall())
    conn.close()
    return jsonify({'success': True, 'data': rows})

# ══════════════════════════════════════════════════════════════════
#  FEATURE 22 – Contract Management
# ══════════════════════════════════════════════════════════════════

@app.route('/api/contracts', methods=['GET'])
def get_contracts():
    conn = get_db()
    rows = rows_to_list(conn.execute("""
        SELECT c.*, cl.company AS client_company
        FROM contracts c
        LEFT JOIN clients cl ON cl.id=c.client_id
        ORDER BY c.end_date
    """).fetchall())
    conn.close()
    return jsonify({'success': True, 'data': rows})

@app.route('/api/contracts', methods=['POST'])
def create_contract():
    data = request.json or {}
    if not data.get('title') and not data.get('contract_type'):
        return jsonify({'success': False, 'error': 'contract_type required'}), 400
    # B-23: Use correct schema columns: id(TEXT PK), client_id, contract_type,
    #        start_date, end_date, capacity_commitment, rate_terms, sla_terms, status
    import uuid as _uuid
    cid = 'CON-' + str(_uuid.uuid4())[:8].upper()
    conn = get_db()
    conn.execute("""
        INSERT INTO contracts (id, client_id, contract_type, start_date, end_date,
            capacity_commitment, rate_terms, sla_terms, status)
        VALUES (?,?,?,?,?,?,?,?,?)
    """, (cid, data.get('client_id'),
          data.get('contract_type', data.get('title', 'Standard')),
          data.get('start_date'), data.get('end_date'),
          data.get('capacity_commitment', data.get('routes_covered')),
          data.get('rate_terms', data.get('payment_terms')),
          data.get('sla_terms'), data.get('status', 'Active')))
    conn.commit(); conn.close()
    return jsonify({'success': True, 'contract_id': cid})

@app.route('/api/contracts/<cid>', methods=['PUT'])
def update_contract(cid):
    data = request.json or {}
    conn = get_db()
    # B-23: Only update columns that exist in the schema
    conn.execute("""
        UPDATE contracts SET status=?, end_date=?, rate_terms=?
        WHERE id=?
    """, (data.get('status'), data.get('end_date'),
          data.get('rate_terms', data.get('payment_terms')), cid))
    conn.commit(); conn.close()
    return jsonify({'success': True})

# ══════════════════════════════════════════════════════════════════
#  FEATURE 23 – Reports & Export
# ══════════════════════════════════════════════════════════════════

@app.route('/api/reports/delivery-performance', methods=['GET'])
def report_delivery_performance():
    conn = get_db()
    data = rows_to_list(conn.execute("""
        SELECT source_city, destination_city,
               COUNT(*) AS total_orders,
               SUM(order_status='Delivered') AS delivered,
               SUM(order_status='In Transit') AS in_transit,
               ROUND(AVG(distance_km),0) AS avg_km,
               ROUND(SUM(COALESCE(transport_cost_inr,0)),0) AS total_revenue,
               ROUND(100.0*SUM(order_status='Delivered')/COUNT(*),1) AS delivery_rate_pct
        FROM orders
        GROUP BY source_city, destination_city
        ORDER BY total_orders DESC LIMIT 30
    """).fetchall())
    conn.close()
    return jsonify({'success': True, 'data': data})

@app.route('/api/reports/vehicle-utilization', methods=['GET'])
def report_vehicle_utilization():
    conn = get_db()
    data = rows_to_list(conn.execute("""
        SELECT v.id, v.vehicle_number, v.vehicle_type, v.driver_name, v.status,
               COUNT(o.id) AS total_orders,
               SUM(COALESCE(o.transport_cost_inr,0)) AS total_revenue,
               ROUND(AVG(o.distance_km),0) AS avg_distance,
               SUM(CASE WHEN o.order_status='In Transit' THEN 1 ELSE 0 END) AS active_orders
        FROM vehicles v
        LEFT JOIN orders o ON o.vehicle_id=v.id
        GROUP BY v.id ORDER BY total_orders DESC
    """).fetchall())
    conn.close()
    return jsonify({'success': True, 'data': data})

@app.route('/api/reports/financial-summary', methods=['GET'])
def report_financial_summary():
    conn = get_db()
    monthly = rows_to_list(conn.execute("""
        SELECT strftime('%Y-%m', dispatch_datetime) AS month,
               COUNT(*) AS orders,
               ROUND(SUM(COALESCE(transport_cost_inr,0)),0) AS revenue,
               ROUND(SUM(COALESCE(fuel_cost_inr,0)+COALESCE(toll_cost_inr,0)+
                   COALESCE(maintenance_cost_inr,0)),0) AS expenses,
               ROUND(SUM(COALESCE(transport_cost_inr,0)) -
                   SUM(COALESCE(fuel_cost_inr,0)+COALESCE(toll_cost_inr,0)+
                   COALESCE(maintenance_cost_inr,0)),0) AS profit
        FROM orders
        WHERE dispatch_datetime IS NOT NULL
        GROUP BY month ORDER BY month DESC LIMIT 12
    """).fetchall())
    conn.close()
    return jsonify({'success': True, 'data': monthly})

@app.route('/api/reports/export/orders', methods=['GET'])
def export_orders_csv():
    """Returns orders as CSV text for browser download."""
    conn = get_db()
    rows = conn.execute("""
        SELECT id, customer_name, customer_company, source_city, destination_city,
               goods_type, quantity, unit, vehicle_id, order_status,
               dispatch_datetime, expected_delivery_datetime, actual_delivery_datetime,
               distance_km, transport_cost_inr
        FROM orders ORDER BY dispatch_datetime DESC
    """).fetchall()
    conn.close()
    import io
    output = io.StringIO()
    headers = ['Order ID','Customer','Company','From','To','Goods','Qty','Unit',
               'Vehicle','Status','Dispatched','Expected Delivery','Actual Delivery',
               'Distance km','Cost INR']
    output.write(','.join(headers) + '\n')
    for r in rows:
        output.write(','.join([f'"{str(v or "")}"' for v in r]) + '\n')
    resp = Response(output.getvalue(), mimetype='text/csv')
    resp.headers['Content-Disposition'] = 'attachment; filename=fleet_orders.csv'
    return resp

# ══════════════════════════════════════════════════════════════════
#  FEATURE 24 – Staff / HR Module
# ══════════════════════════════════════════════════════════════════

@app.route('/api/staff', methods=['GET'])
def get_staff():
    conn = get_db()
    rows = rows_to_list(conn.execute('SELECT * FROM staff ORDER BY name').fetchall())
    conn.close()
    return jsonify({'success': True, 'data': rows})

@app.route('/api/staff', methods=['POST'])
def create_staff():
    data = request.json or {}
    if not data.get('name') or not data.get('role'):
        return jsonify({'success': False, 'error': 'name and role required'}), 400
    conn = get_db()
    cur = conn.execute("""
        INSERT INTO staff (name, role, department, email, phone,
            joined_date, shift, salary_inr, status)
        VALUES (?,?,?,?,?,?,?,?,?)
    """, (data['name'], data['role'], data.get('department','Operations'),
          data.get('email'), data.get('phone'),
          data.get('joined_date', datetime.now().date().isoformat()),
          data.get('shift','Day'), data.get('salary_inr', 0), 'Active'))
    sid = cur.lastrowid
    conn.commit(); conn.close()
    return jsonify({'success': True, 'staff_id': sid})

@app.route('/api/staff/<int:sid>', methods=['PUT'])
def update_staff(sid):
    import traceback as _tb
    try:
        data = request.get_json(force=True, silent=True) or {}
        if data.get('_delete'):
            conn = get_db()
            row = conn.execute('SELECT id FROM staff WHERE id=?', (sid,)).fetchone()
            if not row:
                conn.close()
                return jsonify({'success': False, 'error': 'Staff member not found'}), 404
            conn.execute('DELETE FROM staff WHERE id=?', (sid,))
            conn.commit()
            conn.close()
            return jsonify({'success': True, 'deleted': True})
        conn = get_db()
        conn.execute("""
            UPDATE staff SET role=?, shift=?, status=?, salary_inr=? WHERE id=?
        """, (data.get('role'), data.get('shift'), data.get('status'), data.get('salary_inr'), sid))
        conn.commit()
        conn.close()
        return jsonify({'success': True})
    except Exception as ex:
        _tb.print_exc()
        return jsonify({'success': False, 'error': str(ex)}), 500

@app.route('/api/staff/shifts', methods=['GET'])
def get_shift_summary():
    conn = get_db()
    shifts = rows_to_list(conn.execute("""
        SELECT shift, COUNT(*) AS count,
               ROUND(AVG(salary_inr),0) AS avg_salary
        FROM staff WHERE status='Active'
        GROUP BY shift
    """).fetchall())
    depts = rows_to_list(conn.execute("""
        SELECT department, COUNT(*) AS count FROM staff
        WHERE status='Active' GROUP BY department
    """).fetchall())
    conn.close()
    return jsonify({'success': True, 'shifts': shifts, 'departments': depts})

# ══════════════════════════════════════════════════════════════════
#  FEATURE 25 – Notifications Hub
# ══════════════════════════════════════════════════════════════════

@app.route('/api/notifications', methods=['GET'])
def get_notifications():
    conn = get_db()
    unread_only = request.args.get('unread', '0') == '1'
    q = 'SELECT * FROM notifications WHERE 1=1'
    if unread_only:
        q += ' AND is_read=0'
    q += ' ORDER BY sent_at DESC LIMIT 100'
    rows = rows_to_list(conn.execute(q).fetchall())
    unread = conn.execute('SELECT COUNT(*) as c FROM notifications WHERE is_read=0').fetchone()['c']
    conn.close()
    return jsonify({'success': True, 'data': rows, 'unread_count': unread})

@app.route('/api/notifications', methods=['POST'])
def create_notification():
    data = request.json or {}
    conn = get_db()
    # Bug A fix: use actual schema columns (subject, message, channel, recipient_type, recipient_id)
    # The notifications table has: recipient_type, recipient_id, channel, subject, message,
    # order_id, vehicle_id, is_read, sent_at — NOT title/type/priority/related_*
    conn.execute("""
        INSERT INTO notifications
            (recipient_type, recipient_id, channel, subject, message, order_id, vehicle_id)
        VALUES (?,?,?,?,?,?,?)
    """, (data.get('recipient_type', 'all'), data.get('recipient_id'),
          data.get('channel', 'app'),
          data.get('title', data.get('subject', 'Notification')),
          data.get('message', ''),
          data.get('order_id'), data.get('vehicle_id')))
    conn.commit(); conn.close()
    broadcast(json.dumps({'type': 'notification', 'title': data.get('title', data.get('subject'))}))
    return jsonify({'success': True})

@app.route('/api/notifications/read-all', methods=['POST'])
def mark_all_read():
    conn = get_db()
    conn.execute('UPDATE notifications SET is_read=1')
    conn.commit(); conn.close()
    return jsonify({'success': True})

@app.route('/api/notifications/<int:nid>/read', methods=['POST'])
def mark_notification_read(nid):
    conn = get_db()
    conn.execute('UPDATE notifications SET is_read=1 WHERE id=?', (nid,))
    conn.commit(); conn.close()
    return jsonify({'success': True})

# ── B-27: Periodic vehicle_positions cleanup ──────────────────────────────────
def _cleanup_old_positions():
    """Delete vehicle position records older than 7 days to prevent unbounded growth."""
    try:
        conn = get_db()
        conn.execute("DELETE FROM vehicle_positions WHERE recorded_at < datetime('now', '-7 days')")
        conn.commit()
        conn.close()
    except Exception as e:
        logger.warning('position cleanup error: %s', e)
    # Bug H fix: mark Timer as daemon so it won't prevent clean server shutdown
    t = threading.Timer(6 * 3600, _cleanup_old_positions)
    t.daemon = True
    t.start()


# ── Error handlers ────────────────────────────────────────────────────────────
@app.errorhandler(404)
def not_found(e):
    return jsonify({'success': False, 'error': 'Not found'}), 404

@app.errorhandler(405)
def method_not_allowed(e):
    return jsonify({'success': False, 'error': 'Method not allowed'}), 405

@app.errorhandler(500)
def server_error(e):
    logger.error("Server error: %s", e)
    return jsonify({'success': False, 'error': str(e)}), 500

# ── Main ──────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    os.makedirs(os.path.join(os.path.dirname(__file__), 'data'), exist_ok=True)
    init_db()
    mongo_registry.seed_registry()   # seed MongoDB vehicle details on startup
    seed_maintenance_records()        # seed 6 maintenance records if table empty
    # B-27: Start periodic vehicle_positions cleanup (runs every 6 h)
    # Bug H fix: daemon=True so the timer thread doesn't block shutdown
    _t0 = threading.Timer(300, _cleanup_old_positions)
    _t0.daemon = True
    _t0.start()  # first run after 5 min
    log_event('system', 'Fleet Command server starting', 'system', 'server')
    simulation_engine.start()
    # B-19: Read PORT from environment so Render/Railway can inject their port
    _port = int(os.environ.get('PORT', 1995))
    logger.info("Fleet Command server starting on port %d", _port)
    app.run(host='0.0.0.0', port=_port, debug=False, threaded=True)