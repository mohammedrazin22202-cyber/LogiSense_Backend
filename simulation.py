"""
Fleet Command - Vehicle Simulation Engine
Simulates real-time vehicle movement along routes with realistic behavior
"""
import math
import random
import threading
import time
import logging
from datetime import datetime, timezone
from database import get_db, log_event

logger = logging.getLogger(__name__)

# City coordinates (India)
CITY_COORDS = {
    'Chennai':         (13.0827, 80.2707),
    'Kochi':           (9.9312, 76.2673),
    'Mumbai':          (19.0760, 72.8777),
    'Goa':             (15.2993, 74.1240),
    'Kolkata':         (22.5726, 88.3639),
    'Guwahati':        (26.1445, 91.7362),
    'Visakhapatnam':   (17.6868, 83.2185),
    'Bhubaneswar':     (20.2961, 85.8245),
    'Tuticorin':       (8.7642, 78.1348),
    'Trivandrum':      (8.5241, 76.9366),
}

def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
    return R * 2 * math.asin(math.sqrt(a))

def bearing(lat1, lon1, lat2, lon2):
    dlng = math.radians(lon2 - lon1)
    lat1, lat2 = math.radians(lat1), math.radians(lat2)
    x = math.sin(dlng) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlng)
    return (math.degrees(math.atan2(x, y)) + 360) % 360

def move_toward(lat, lng, target_lat, target_lng, km_step):
    dist = haversine_km(lat, lng, target_lat, target_lng)
    if dist < 0.1:
        return target_lat, target_lng, 0
    ratio = min(km_step / dist, 1.0)
    new_lat = lat + (target_lat - lat) * ratio
    new_lng = lng + (target_lng - lng) * ratio
    return new_lat, new_lng, dist - km_step

class SimulationEngine:
    def __init__(self, broadcast_fn=None):
        self.broadcast_fn = broadcast_fn
        self.running = False
        self.thread = None
        self.lock = threading.Lock()
        self.update_interval = 5  # seconds
        self.vehicle_states = {}  # local state cache

    def set_broadcast(self, fn):
        self.broadcast_fn = fn

    def start(self):
        self.running = True
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        logger.info("Simulation engine started (interval=%ds)", self.update_interval)

    def stop(self):
        self.running = False

    def _run(self):
        while self.running:
            try:
                self._tick()
            except Exception as e:
                logger.error("Simulation tick error: %s", e)
            time.sleep(self.update_interval)

    def _tick(self):
        conn = get_db()
        now = datetime.now(timezone.utc).isoformat()

        try:
            # Get all active (moving) vehicles with their current order info
            vehicles = conn.execute("""
                SELECT v.*, o.source_city, o.destination_city, o.distance_km, o.id as order_id_ref
                FROM vehicles v
                LEFT JOIN orders o ON v.current_order_id = o.id
                WHERE v.status IN ('moving', 'idle', 'stopped')
            """).fetchall()

            updates = []
            alert_events = []

            for vrow in vehicles:
                v = dict(vrow)
                vid = v['id']
                status = v['status']
                lat = v['current_lat']
                lng = v['current_lng']

                if status == 'moving' and lat and lng and v.get('destination_city'):
                    dst_coords = CITY_COORDS.get(v['destination_city'])
                    if not dst_coords:
                        continue

                    # Speed variation: 35-70 km/h with occasional slowdowns
                    base_speed = v['current_speed'] or 50
                    # Random events
                    rand = random.random()
                    if rand < 0.05:
                        # Traffic jam
                        new_speed = random.uniform(5, 20)
                        new_status = 'stopped'
                        alert_events.append({
                            'vehicle_id': vid,
                            'order_id': v['current_order_id'],
                            'type': 'Traffic Slowdown',
                            'reason': 'Vehicle stopped due to traffic',
                            'severity': 'Medium'
                        })
                    elif rand < 0.08:
                        new_speed = 0
                        new_status = 'idle'
                    else:
                        new_speed = base_speed + random.uniform(-8, 8)
                        new_speed = max(30, min(75, new_speed))
                        new_status = 'moving'

                    # Move vehicle: speed km/h * interval_seconds / 3600 = km moved
                    km_moved = (new_speed * self.update_interval) / 3600.0
                    new_lat, new_lng, dist_remaining = move_toward(lat, lng, dst_coords[0], dst_coords[1], km_moved)
                    head = bearing(lat, lng, dst_coords[0], dst_coords[1])

                    # Check if arrived
                    if dist_remaining <= 0 or haversine_km(new_lat, new_lng, dst_coords[0], dst_coords[1]) < 0.5:
                        new_lat, new_lng = dst_coords
                        new_status = 'idle'
                        new_speed = 0
                        # Mark order delivered
                        conn.execute(
                            "UPDATE orders SET order_status='Delivered', actual_delivery_datetime=? WHERE id=?",
                            (now, v['current_order_id'])
                        )
                        conn.execute(
                            "UPDATE vehicles SET current_order_id=NULL, assigned_route=NULL WHERE id=?",
                            (vid,)
                        )
                        log_event('delivery', f"Vehicle {vid} delivered order {v['current_order_id']}",
                                  'vehicle', vid, {'order_id': v['current_order_id']})
                        alert_events.append({
                            'vehicle_id': vid,
                            'order_id': v['current_order_id'],
                            'type': 'Delivery Complete',
                            'reason': f"Order {v['current_order_id']} delivered at {v['destination_city']}",
                            'severity': 'Low'
                        })

                    updates.append({
                        'id': vid,
                        'current_lat': new_lat,
                        'current_lng': new_lng,
                        'current_speed': round(new_speed, 1),
                        'heading': round(head, 1),
                        'status': new_status,
                        'last_updated': now,
                    })

                    # Record position history (every tick)
                    conn.execute("""
                        INSERT INTO vehicle_positions (vehicle_id, lat, lng, speed, heading, status, order_id, recorded_at)
                        VALUES (?,?,?,?,?,?,?,?)
                    """, (vid, new_lat, new_lng, new_speed, head, new_status, v['current_order_id'], now))

                elif status == 'stopped' and random.random() < 0.3:
                    # Resume after being stopped
                    new_speed = random.uniform(30, 50)
                    updates.append({
                        'id': vid, 'current_lat': lat, 'current_lng': lng,
                        'current_speed': new_speed, 'heading': v['heading'] or 0,
                        'status': 'moving', 'last_updated': now
                    })

            # Batch update vehicles
            for u in updates:
                conn.execute("""
                    UPDATE vehicles SET
                        current_lat=?, current_lng=?, current_speed=?, heading=?,
                        status=?, last_updated=?
                    WHERE id=?
                """, (u['current_lat'], u['current_lng'], u['current_speed'], u['heading'], u['status'], u['last_updated'], u['id']))

            # Insert alerts
            for a in alert_events:
                conn.execute("""
                    INSERT INTO alerts (order_id, vehicle_id, alert_type, alert_reason, severity)
                    VALUES (?,?,?,?,?)
                """, (a['order_id'], a['vehicle_id'], a['type'], a['reason'], a['severity']))

            conn.commit()

            # Broadcast to all SSE clients
            if self.broadcast_fn and updates:
                import json
                payload = {
                    'type': 'vehicle_update',
                    'timestamp': now,
                    'vehicles': updates,
                    'alerts': alert_events
                }
                self.broadcast_fn(json.dumps(payload))

        finally:
            conn.close()

simulation_engine = SimulationEngine()
