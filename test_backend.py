import os
import sys
import io

# Monkeypatch io.TextIOWrapper to prevent closing standard streams on Windows
_orig_TextIOWrapper = io.TextIOWrapper
class SafeTextIOWrapper(_orig_TextIOWrapper):
    def close(self):
        try:
            if hasattr(self, 'buffer') and self.buffer in (sys.__stdout__.buffer, sys.__stderr__.buffer, sys.stdout.buffer, sys.stderr.buffer):
                return
        except Exception:
            pass
        try:
            super().close()
        except Exception:
            pass
io.TextIOWrapper = SafeTextIOWrapper

import unittest
import json
import sqlite3
import random

# Add backend and chatbot directories to path
BACKEND_DIR = r"c:\Users\MegaTron\Videos\Data\LogiSense\fleet-command\LogiSense 360\backend"
CHATBOT_DIR = r"c:\Users\MegaTron\Videos\Data\LogiSense\fleet-command\LogiSense 360\frontend\Customer_ChatBot"

sys.path.insert(0, BACKEND_DIR)
sys.path.insert(0, CHATBOT_DIR)

# Import backend and chatbot modules
from database import init_db, get_db, DB_PATH
import seed
import server
import app as cb_app

class LogiSense360Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        print("Initializing and seeding database for testing...")
        # Run the seeder to ensure a clean known state
        seed.seed()
        cls.app = server.app
        cls.client = cls.app.test_client()

    def test_01_fleet_registry(self):
        print("\n--- Testing Feature 1: Fleet Registry ---")
        # GET /api/vehicles
        res = self.client.get('/api/vehicles')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data['success'])
        self.assertGreater(len(data['data']), 0)
        vid = data['data'][0]['id']
        
        # GET /api/vehicles/<vid>
        res = self.client.get(f'/api/vehicles/{vid}')
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json()['success'])

        # GET /api/fleet/registry
        res = self.client.get('/api/fleet/registry')
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json()['success'])

        # GET /api/fleet/expiry-alerts
        res = self.client.get('/api/fleet/expiry-alerts')
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json()['success'])

        # GET /api/fleet/maintenance
        res = self.client.get('/api/fleet/maintenance')
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json()['success'])

    def test_02_route_optimization(self):
        print("\n--- Testing Feature 2: Route Optimization ---")
        # GET /api/routes
        res = self.client.get('/api/routes')
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json()['success'])

        # POST /api/routes/optimize
        payload = {
            'source_city': 'Chennai',
            'destination_city': 'Bengaluru',
            'priority': 'Economy'
        }
        res = self.client.post('/api/routes/optimize', json=payload)
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json()['success'])

    def test_03_warehouse_management(self):
        print("\n--- Testing Feature 3: Warehouse Management ---")
        # POST /api/warehouses (add a test warehouse)
        payload = {
            'name': 'Test Warehouse',
            'location': 'Industrial Area',
            'city': 'Chennai',
            'lat': 13.0,
            'lng': 80.0,
            'total_capacity_cbm': 500.0,
            'is_hub': 1
        }
        res = self.client.post('/api/warehouses', json=payload)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data['success'])
        wid = data['id']

        # GET /api/warehouses
        res = self.client.get('/api/warehouses')
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json()['success'])

        # POST inbound inventory
        res = self.client.post(f'/api/warehouses/{wid}/inventory/inbound', json={
            'goods_type': 'Electronics',
            'quantity': 100,
            'unit': 'units',
            'cbm': 10.0
        })
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json()['success'])

        # GET inventory
        res = self.client.get(f'/api/warehouses/{wid}/inventory')
        self.assertEqual(res.status_code, 200)
        inv_data = res.get_json()
        self.assertTrue(inv_data['success'])
        self.assertGreater(len(inv_data['data']), 0)
        iid = inv_data['data'][0]['id']

        # GET stock count
        res = self.client.get(f'/api/warehouses/{wid}/stock-count')
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json()['success'])

        # PUT outbound inventory
        res = self.client.put(f'/api/warehouses/{wid}/inventory/{iid}/outbound')
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json()['success'])

        # DELETE inventory
        res = self.client.delete(f'/api/warehouses/{wid}/inventory/{iid}')
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json()['success'])

        # DELETE warehouse
        res = self.client.delete(f'/api/warehouses/{wid}')
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json()['success'])

    def test_04_load_planning(self):
        print("\n--- Testing Feature 4: Load Planning ---")
        # GET orders
        res = self.client.get('/api/orders')
        self.assertEqual(res.status_code, 200)
        orders = res.get_json()['data']
        self.assertGreater(len(orders), 0)
        order_ids = [o['id'] for o in orders[:3]]

        # GET vehicles
        res = self.client.get('/api/vehicles')
        vehicles = res.get_json()['data']
        self.assertGreater(len(vehicles), 0)
        vid = vehicles[0]['id']

        # POST /api/load-plans/optimize
        payload = {
            'vehicle_id': vid,
            'order_ids': order_ids,
            'trip_date': '2026-08-20'
        }
        res = self.client.post('/api/load-plans/optimize', json=payload)
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json()['success'])

        # GET /api/load-plans
        res = self.client.get('/api/load-plans')
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json()['success'])

    def test_05_dispatch_system(self):
        print("\n--- Testing Feature 5: Dispatch System ---")
        # GET pending-orders
        res = self.client.get('/api/dispatch/pending-orders')
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json()['success'])
        
        # GET available-vehicles
        res = self.client.get('/api/dispatch/available-vehicles')
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json()['success'])

        # Create dispatch
        res = self.client.get('/api/orders')
        orders = res.get_json()['data']
        oid = orders[0]['id']

        res = self.client.get('/api/vehicles')
        vehicles = res.get_json()['data']
        vid = vehicles[0]['id']

        res = self.client.post('/api/dispatch', json={
            'order_id': oid,
            'vehicle_id': vid
        })
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json()['success'])

        # GET dispatches
        res = self.client.get('/api/dispatch')
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json()['success'])

    def test_06_driver_management(self):
        print("\n--- Testing Feature 6: Driver Management ---")
        # POST /api/drivers
        payload = {
            'name': 'John Doe',
            'contact': '9876543210',
            'license_number': 'DL-12345',
            'license_expiry': '2030-01-01',
            'license_type': 'HMV'
        }
        res = self.client.post('/api/drivers', json=payload)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data['success'])
        did = data['driver_id']

        # GET /api/drivers
        res = self.client.get('/api/drivers')
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json()['success'])

        # PUT /api/drivers/<did>
        res = self.client.put(f'/api/drivers/{did}', json={
            'availability': 'Busy',
            'rating': 4.5
        })
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json()['success'])

        # POST /api/drivers/<did>/rate
        res = self.client.post(f'/api/drivers/{did}/rate', json={
            'rating': 5
        })
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json()['success'])

    def test_07_proof_of_delivery(self):
        print("\n--- Testing Feature 7: Proof of Delivery (POD) ---")
        # GET /api/pod/pending
        res = self.client.get('/api/pod/pending')
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json()['success'])

        # GET orders
        res = self.client.get('/api/orders')
        orders = res.get_json()['data']
        oid = orders[0]['id']

        # POST /api/pod/<order_id>
        res = self.client.post(f'/api/pod/{oid}', json={
            'pod_type': 'Digital Signature',
            'pod_reference': 'REF-12345'
        })
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json()['success'])

        # GET /api/pod
        res = self.client.get('/api/pod')
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json()['success'])

    def test_08_shipment_lifecycle(self):
        print("\n--- Testing Feature 8: Shipment Lifecycle ---")
        # GET /api/orders
        res = self.client.get('/api/orders')
        oid = res.get_json()['data'][0]['id']

        # GET /api/lifecycle/<order_id>
        res = self.client.get(f'/api/lifecycle/{oid}')
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json()['success'])

        # PUT /api/lifecycle/<order_id>
        res = self.client.put(f'/api/lifecycle/{oid}', json={
            'stage': 'In Transit'
        })
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json()['success'])

        # GET /api/lifecycle
        res = self.client.get('/api/lifecycle')
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json()['success'])

    def test_09_exception_handling(self):
        print("\n--- Testing Feature 9: Exception Handling ---")
        # GET /api/orders and vehicles
        res1 = self.client.get('/api/orders')
        oid = res1.get_json()['data'][0]['id']
        res2 = self.client.get('/api/vehicles')
        vid = res2.get_json()['data'][0]['id']

        # POST /api/incidents
        payload = {
            'order_id': oid,
            'vehicle_id': vid,
            'incident_type': 'Breakdown',
            'description': 'Engine heating issue near Nellore',
            'location': 'Nellore Highway',
            'severity': 'High',
            'damage_value_inr': 15000,
            'is_insured': True,
            'claim_status': 'Filed'
        }
        res = self.client.post('/api/incidents', json=payload)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data['success'])
        iid = data['incident_id']

        # GET /api/incidents
        res = self.client.get('/api/incidents')
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json()['success'])

        # POST /api/incidents/<iid>/resolve
        res = self.client.post(f'/api/incidents/{iid}/resolve', json={
            'claim_status': 'Settled'
        })
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json()['success'])

    def test_10_cost_tracking(self):
        print("\n--- Testing Feature 10: Cost Tracking ---")
        # GET /api/orders
        res = self.client.get('/api/orders')
        oid = res.get_json()['data'][0]['id']

        # PUT /api/costs/<order_id>
        res = self.client.put(f'/api/costs/{oid}', json={
            'fuel_cost_inr': 5000,
            'toll_cost_inr': 1200,
            'maintenance_cost_inr': 0,
            'other_cost_inr': 300
        })
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json()['success'])

        # GET /api/costs
        res = self.client.get('/api/costs')
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json()['success'])

        # GET /api/costs/summary
        res = self.client.get('/api/costs/summary')
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json()['success'])

    def test_11_vehicle_telemetry(self):
        print("\n--- Testing Feature 11: Vehicle Telemetry ---")
        # GET vehicles
        res = self.client.get('/api/vehicles')
        vid = res.get_json()['data'][0]['id']

        # PUT /api/telemetry/<vid>
        res = self.client.put(f'/api/telemetry/{vid}', json={
            'fuel_level_pct': 85.0,
            'engine_temp_c': 90.0,
            'engine_health': 'Good',
            'odometer_km': 150230.5,
            'fuel_consumed_liters': 45.0,
            'fuel_cost_inr': 4300,
            'fuel_efficiency_kmpl': 5.2
        })
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json()['success'])

        # GET /api/telemetry
        res = self.client.get('/api/telemetry')
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json()['success'])

        # GET /api/telemetry/<vid>
        res = self.client.get(f'/api/telemetry/{vid}')
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json()['success'])

    def test_12_multi_hub_logistics(self):
        print("\n--- Testing Feature 12: Multi-Hub Logistics ---")
        # Add two hubs
        res1 = self.client.post('/api/warehouses', json={'name': 'Hub A', 'is_hub': 1})
        self.assertEqual(res1.status_code, 200)
        hub_a = res1.get_json()['id']

        res2 = self.client.post('/api/warehouses', json={'name': 'Hub B', 'is_hub': 1})
        self.assertEqual(res2.status_code, 200)
        hub_b = res2.get_json()['id']

        # Get orders
        res = self.client.get('/api/orders')
        oid = res.get_json()['data'][0]['id']

        # POST /api/hubs/transfers
        res = self.client.post('/api/hubs/transfers', json={
            'order_id': oid,
            'from_hub_id': hub_a,
            'to_hub_id': hub_b,
            'sort_lane': 'Lane 3'
        })
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data['success'])
        tid = data['transfer_id']

        # GET /api/hubs
        res = self.client.get('/api/hubs')
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json()['success'])

        # GET /api/hubs/transfers
        res = self.client.get('/api/hubs/transfers')
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json()['success'])

        # PUT /api/hubs/transfers/<tid>
        res = self.client.put(f'/api/hubs/transfers/{tid}', json={
            'status': 'Arrived'
        })
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json()['success'])

        # Cleanup hubs
        self.client.delete(f'/api/warehouses/{hub_a}')
        self.client.delete(f'/api/warehouses/{hub_b}')

    def test_13_reverse_logistics(self):
        print("\n--- Testing Feature 13: Reverse Logistics ---")
        # GET orders
        res = self.client.get('/api/orders')
        oid = res.get_json()['data'][0]['id']

        # POST /api/returns
        res = self.client.post('/api/returns', json={
            'parent_order_id': oid,
            'priority_tier': 'Economy'
        })
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json()['success'])

        # GET /api/returns
        res = self.client.get('/api/returns')
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json()['success'])

    def test_14_sla_monitoring(self):
        print("\n--- Testing Feature 14: SLA Monitoring ---")
        # GET /api/sla
        res = self.client.get('/api/sla')
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json()['success'])

        # GET orders
        res = self.client.get('/api/orders')
        oid = res.get_json()['data'][0]['id']

        # PUT /api/sla/<order_id>
        res = self.client.put(f'/api/sla/{oid}', json={
            'sla_deadline': '2026-08-25T12:00:00',
            'sla_breached': True
        })
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json()['success'])

    def test_15_performance_kpis(self):
        print("\n--- Testing Feature 15: Performance Analytics / KPIs ---")
        # GET /api/kpis
        res = self.client.get('/api/kpis')
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json()['success'])

    def test_16_customer_management(self):
        print("\n--- Testing Feature 16: Customer Management ---")
        # POST /api/customers
        payload = {
            'name': 'Test Client',
            'company': 'Test Industries',
            'email': 'client@test.com',
            'phone': '9988776655',
            'city': 'Mumbai'
        }
        res = self.client.post('/api/customers', json=payload)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data['success'])
        cid = data['client_id']

        # GET /api/customers
        res = self.client.get('/api/customers')
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json()['success'])

        # GET /api/customers/<cid>/orders
        res = self.client.get(f'/api/customers/{cid}/orders')
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json()['success'])

        # PUT /api/customers/<cid> (to delete)
        res = self.client.put(f'/api/customers/{cid}', json={'_delete': True})
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json()['success'])

    def test_17_billing_invoicing(self):
        print("\n--- Testing Feature 17: Billing & Invoicing ---")
        # GET orders
        res = self.client.get('/api/orders')
        oid = res.get_json()['data'][0]['id']

        # POST /api/invoices
        res = self.client.post('/api/invoices', json={
            'order_id': oid,
            'due_date': '2026-09-01'
        })
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data['success'])
        iid = data['invoice_id']

        # GET /api/invoices
        res = self.client.get('/api/invoices')
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json()['success'])

        # GET /api/invoices/summary
        res = self.client.get('/api/invoices/summary')
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json()['success'])

        # POST /api/invoices/<iid>/pay
        res = self.client.post(f'/api/invoices/{iid}/pay')
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json()['success'])

    def test_18_fuel_management(self):
        print("\n--- Testing Feature 18: Fuel Management ---")
        # GET vehicles
        res = self.client.get('/api/vehicles')
        vid = res.get_json()['data'][0]['id']

        # POST /api/fuel
        res = self.client.post('/api/fuel', json={
            'vehicle_id': vid,
            'liters_consumed': 50.0,
            'cost_inr': 4800,
            'odometer_km': 150000.0,
            'fuel_efficiency_kmpl': 5.5,
            'fuel_level_pct': 90.0
        })
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json()['success'])

        # GET /api/fuel
        res = self.client.get('/api/fuel')
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json()['success'])

        # GET /api/fuel/analytics
        res = self.client.get('/api/fuel/analytics')
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json()['success'])

    def test_19_compliance_documents(self):
        print("\n--- Testing Feature 19: Compliance & Documents ---")
        # GET vehicles
        res = self.client.get('/api/vehicles')
        vid = res.get_json()['data'][0]['id']

        # PUT /api/compliance/<vid>
        res = self.client.put(f'/api/compliance/{vid}', json={
            'insurance_expiry': '2027-01-01',
            'permit_expiry': '2027-01-01',
            'fitness_expiry': '2027-01-01',
            'pollution_expiry': '2027-01-01'
        })
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json()['success'])

        # GET /api/compliance
        res = self.client.get('/api/compliance')
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json()['success'])

        # GET /api/compliance/expiring
        res = self.client.get('/api/compliance/expiring?days=90')
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json()['success'])

    def test_20_gps_geofencing(self):
        print("\n--- Testing Feature 20: GPS Geofencing ---")
        # POST /api/geofences
        res = self.client.post('/api/geofences', json={
            'name': 'Chennai Port',
            'zone_type': 'Port Area',
            'lat': 13.0827,
            'lng': 80.2707,
            'radius_km': 10.0
        })
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data['success'])
        gid = data['geofence_id']

        # GET /api/geofences
        res = self.client.get('/api/geofences')
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json()['success'])

        # GET /api/geofences/check
        res = self.client.get('/api/geofences/check')
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json()['success'])

        # DELETE /api/geofences/<gid>
        res = self.client.delete(f'/api/geofences/{gid}')
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json()['success'])

    def test_21_maintenance_scheduling(self):
        print("\n--- Testing Feature 21: Maintenance Scheduling ---")
        # GET vehicles
        res = self.client.get('/api/vehicles')
        vid = res.get_json()['data'][0]['id']

        # POST /api/maintenance/schedule
        res = self.client.post('/api/maintenance/schedule', json={
            'vehicle_id': vid,
            'scheduled_date': '2026-09-15',
            'maintenance_type': 'Routine Service',
            'estimated_cost_inr': 5000,
            'vendor': 'TVS Service',
            'notes': 'Checking brakes'
        })
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data['success'])
        sid = data['schedule_id']

        # GET /api/maintenance/schedule
        res = self.client.get('/api/maintenance/schedule')
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json()['success'])

        # GET /api/maintenance/upcoming
        res = self.client.get('/api/maintenance/upcoming')
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json()['success'])

        # PUT /api/maintenance/schedule/<sid>
        res = self.client.put(f'/api/maintenance/schedule/{sid}', json={
            'status': 'Completed',
            'actual_cost_inr': 4800
        })
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json()['success'])

    def test_22_contract_management(self):
        print("\n--- Testing Feature 22: Contract Management ---")
        # POST /api/contracts
        res = self.client.post('/api/contracts', json={
            'client_id': '1',
            'contract_type': 'Annual Logistics Contract',
            'start_date': '2026-01-01',
            'end_date': '2026-12-31',
            'capacity_commitment': '10 trucks daily',
            'rate_terms': '50 INR / km',
            'sla_terms': '98% on-time delivery'
        })
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data['success'])
        cid = data['contract_id']

        # GET /api/contracts
        res = self.client.get('/api/contracts')
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json()['success'])

        # PUT /api/contracts/<cid>
        res = self.client.put(f'/api/contracts/{cid}', json={
            'status': 'Suspended',
            'end_date': '2026-11-30'
        })
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json()['success'])

    def test_23_reports_export(self):
        print("\n--- Testing Feature 23: Reports & Export ---")
        # GET reports
        for report in ('delivery-performance', 'vehicle-utilization', 'financial-summary'):
            res = self.client.get(f'/api/reports/{report}')
            self.assertEqual(res.status_code, 200)
            self.assertTrue(res.get_json()['success'])

        # GET export
        res = self.client.get('/api/reports/export/orders')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.mimetype, 'text/csv')

    def test_24_staff_hr(self):
        print("\n--- Testing Feature 24: Staff / HR Module ---")
        # POST /api/staff
        res = self.client.post('/api/staff', json={
            'name': 'Alice Smith',
            'role': 'Dispatcher',
            'department': 'Operations',
            'shift': 'Night',
            'salary_inr': 45000
        })
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data['success'])
        sid = data['staff_id']

        # GET /api/staff
        res = self.client.get('/api/staff')
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json()['success'])

        # GET /api/staff/shifts
        res = self.client.get('/api/staff/shifts')
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json()['success'])

        # PUT /api/staff/<sid> (to delete)
        res = self.client.put(f'/api/staff/{sid}', json={'_delete': True})
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json()['success'])

    def test_25_notifications_hub(self):
        print("\n--- Testing Feature 25: Notifications Hub ---")
        # GET vehicles and orders
        res1 = self.client.get('/api/vehicles')
        vid = res1.get_json()['data'][0]['id']
        res2 = self.client.get('/api/orders')
        oid = res2.get_json()['data'][0]['id']

        # POST /api/notifications
        res = self.client.post('/api/notifications', json={
            'recipient_type': 'driver',
            'recipient_id': vid,
            'channel': 'sms',
            'subject': 'Shift Alert',
            'message': 'Your shift starts in 1 hour.',
            'order_id': oid,
            'vehicle_id': vid
        })
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json()['success'])

        # GET /api/notifications
        res = self.client.get('/api/notifications')
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json()['success'])
        notifs = res.get_json()['data']
        self.assertGreater(len(notifs), 0)
        nid = notifs[0]['id']

        # POST /api/notifications/<nid>/read
        res = self.client.post(f'/api/notifications/{nid}/read')
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json()['success'])

        # POST /api/notifications/read-all
        res = self.client.post('/api/notifications/read-all')
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json()['success'])

    def test_extra_auths_and_logs(self):
        print("\n--- Testing Drivers/Customer/Admin Auth & System Logs ---")
        # GET /api/logs
        res = self.client.get('/api/logs')
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json()['success'])

        # Admin Auth
        res = self.client.post('/api/admin/auth', json={
            'user': 'MegaTron',
            'method': 'password',
            'pass': 'MG@88307'
        })
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json()['success'])

        # Driver Login (query actual contact from DB)
        conn = get_db()
        v_row = conn.execute("SELECT driver_contact FROM vehicles WHERE id='OFE-TRK-001'").fetchone()
        conn.close()
        contact_val = v_row['driver_contact'] if (v_row and v_row['driver_contact']) else '9840112233'

        res = self.client.post('/api/driver/login', json={
            'vehicle_id': 'OFE-TRK-001',
            'auth_mode': 'contact',
            'contact': contact_val
        })
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json()['success'])
        
        # Customer Signup/Auth (use unique email to avoid 409 Conflict)
        test_email = f"new_cust_{random.randint(1000, 9999)}@example.com"
        res = self.client.post('/api/customer/signup', json={
            'name': 'New Customer',
            'email': test_email,
            'password': 'password123'
        })
        self.assertEqual(res.status_code, 200)
        
        res = self.client.post('/api/customer/auth', json={
            'email': test_email,
            'password': 'password123'
        })
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json()['success'])


class ChatBotTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cb_app = cb_app.app
        cls.client = cls.cb_app.test_client()

    def test_chatbot_endpoints(self):
        print("\n--- Testing Customer Chatbot ---")
        # GET /api/health
        res = self.client.get('/api/health')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data['status'], 'healthy')
        self.assertEqual(data['backend'], 'ready')

        # POST /api/chat
        res = self.client.post('/api/chat', json={
            'message': 'Where is my order AHE0719?'
        })
        self.assertEqual(res.status_code, 200)
        print("Chat response for 'Where is my order AHE0719?':")
        print(res.get_json().get('response'))

if __name__ == '__main__':
    unittest.main()
