"""
Fleet Command — MongoDB Vehicle Registry
Stores rich vehicle details: insurance, capacity, permits, fitness, fuel, etc.
Falls back gracefully if MongoDB is unavailable (uses in-memory cache).
"""
import logging
import os
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# ── Try to import pymongo ──────────────────────────────────────────────────────
try:
    from pymongo import MongoClient, ASCENDING
    from pymongo.errors import ConnectionFailure, ServerSelectionTimeoutError
    _PYMONGO_AVAILABLE = True
except ImportError:
    _PYMONGO_AVAILABLE = False
    logger.warning("pymongo not installed — MongoDB registry will use in-memory fallback")

# ── Config ─────────────────────────────────────────────────────────────────────
MONGO_URI  = os.getenv("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB   = os.getenv("MONGO_DB",  "fleet_command")
COLLECTION = "vehicle_registry"

_client = None
_col    = None
_fallback_store: dict = {}   # in-memory fallback if Mongo unavailable

# ── Pre-seeded vehicle details ─────────────────────────────────────────────────
SEED_DATA = [
    {
        "vehicle_id": "OFE-TRK-001",
        "capacity_tons": 20.0,
        "capacity_cbm": 80.0,
        "fuel_type": "Diesel",
        "insurance_provider": "National Insurance Co.",
        "insurance_policy": "NIC-2024-TRK001",
        "insurance_expiry": "2026-03-15",
        "insurance_coverage_inr": 2500000,
        "permit_expiry": "2026-06-30",
        "fitness_expiry": "2026-09-12",
        "pollution_expiry": "2026-01-20",
        "maintenance_due": "2026-04-10",
        "transport_mode": "road",
        "year_of_manufacture": 2020,
        "chassis_no": "MAT445192KW012345",
        "engine_no": "K4M012345X",
        "notes": "Primary Chennai–Mumbai express vehicle",
    },
    {
        "vehicle_id": "OFE-TRK-002",
        "capacity_tons": 20.0,
        "capacity_cbm": 80.0,
        "fuel_type": "Diesel",
        "insurance_provider": "United India Insurance",
        "insurance_policy": "UII-2024-TRK002",
        "insurance_expiry": "2026-05-22",
        "insurance_coverage_inr": 2200000,
        "permit_expiry": "2026-08-15",
        "fitness_expiry": "2026-11-01",
        "pollution_expiry": "2026-04-05",
        "maintenance_due": "2026-06-20",
        "transport_mode": "road",
        "year_of_manufacture": 2019,
        "chassis_no": "MAT445192KW023456",
        "engine_no": "K4M023456Y",
        "notes": "Chennai–Kolkata northeast corridor",
    },
    {
        "vehicle_id": "OFE-TRK-003",
        "capacity_tons": 15.0,
        "capacity_cbm": 60.0,
        "fuel_type": "Diesel",
        "insurance_provider": "Oriental Insurance",
        "insurance_policy": "OIC-2024-TRK003",
        "insurance_expiry": "2026-02-10",
        "insurance_coverage_inr": 1800000,
        "permit_expiry": "2025-11-30",
        "fitness_expiry": "2026-03-25",
        "pollution_expiry": "2025-12-18",
        "maintenance_due": "2026-03-01",
        "transport_mode": "road",
        "year_of_manufacture": 2021,
        "chassis_no": "MAT445192KW034567",
        "engine_no": "K4M034567Z",
        "notes": "Medium refrigerated — Bengaluru operations",
    },
    {
        "vehicle_id": "OFE-TRK-004",
        "capacity_tons": 15.0,
        "capacity_cbm": 60.0,
        "fuel_type": "Diesel",
        "insurance_provider": "New India Assurance",
        "insurance_policy": "NIA-2024-TRK004",
        "insurance_expiry": "2026-07-08",
        "insurance_coverage_inr": 2000000,
        "permit_expiry": "2026-10-20",
        "fitness_expiry": "2027-01-14",
        "pollution_expiry": "2026-07-01",
        "maintenance_due": "2026-08-30",
        "transport_mode": "sea",
        "year_of_manufacture": 2022,
        "chassis_no": "MAT445192KW045678",
        "engine_no": "K4M045678A",
        "notes": "Multi-modal — sea lane capable",
    },
    {
        "vehicle_id": "OFE-TRK-005",
        "capacity_tons": 15.0,
        "capacity_cbm": 60.0,
        "fuel_type": "CNG",
        "insurance_provider": "HDFC Ergo",
        "insurance_policy": "HDE-2024-TRK005",
        "insurance_expiry": "2026-09-14",
        "insurance_coverage_inr": 1900000,
        "permit_expiry": "2026-12-05",
        "fitness_expiry": "2027-03-08",
        "pollution_expiry": "2026-09-10",
        "maintenance_due": "2026-10-15",
        "transport_mode": "road",
        "year_of_manufacture": 2021,
        "chassis_no": "MAT445192KW056789",
        "engine_no": "K4M056789B",
        "notes": "CNG-powered — Hyderabad–Chennai corridor",
    },
    {
        "vehicle_id": "OFE-TRK-006",
        "capacity_tons": 8.0,
        "capacity_cbm": 35.0,
        "fuel_type": "Diesel",
        "insurance_provider": "Bajaj Allianz",
        "insurance_policy": "BAJ-2024-TRK006",
        "insurance_expiry": "2025-12-28",
        "insurance_coverage_inr": 1200000,
        "permit_expiry": "2025-10-15",
        "fitness_expiry": "2026-01-22",
        "pollution_expiry": "2025-11-30",
        "maintenance_due": "2026-01-05",
        "transport_mode": "road",
        "year_of_manufacture": 2018,
        "chassis_no": "MAT445192KW067890",
        "engine_no": "K4M067890C",
        "notes": "Small unit — last-mile urban delivery",
    },
    {
        "vehicle_id": "OFE-TRK-007",
        "capacity_tons": 8.0,
        "capacity_cbm": 35.0,
        "fuel_type": "Diesel",
        "insurance_provider": "ICICI Lombard",
        "insurance_policy": "ICL-2024-TRK007",
        "insurance_expiry": "2026-04-18",
        "insurance_coverage_inr": 1300000,
        "permit_expiry": "2026-07-22",
        "fitness_expiry": "2026-10-30",
        "pollution_expiry": "2026-04-01",
        "maintenance_due": "2026-05-18",
        "transport_mode": "road",
        "year_of_manufacture": 2020,
        "chassis_no": "MAT445192KW078901",
        "engine_no": "K4M078901D",
        "notes": "Mumbai suburban coverage",
    },
    {
        "vehicle_id": "OFE-TRK-008",
        "capacity_tons": 8.0,
        "capacity_cbm": 35.0,
        "fuel_type": "Electric",
        "insurance_provider": "Tata AIG",
        "insurance_policy": "TAIG-2024-TRK008",
        "insurance_expiry": "2026-11-05",
        "insurance_coverage_inr": 1500000,
        "permit_expiry": "2027-02-18",
        "fitness_expiry": "2027-05-25",
        "pollution_expiry": "2026-11-01",
        "maintenance_due": "2026-12-10",
        "transport_mode": "road",
        "year_of_manufacture": 2023,
        "chassis_no": "MAT445192KW089012",
        "engine_no": "EV089012E",
        "notes": "Electric vehicle — zero-emission city routes",
    },
    {
        "vehicle_id": "OFE-TRK-009",
        "capacity_tons": 22.0,
        "capacity_cbm": 90.0,
        "fuel_type": "Diesel",
        "insurance_provider": "New India Assurance",
        "insurance_policy": "NIA-2024-TRK009",
        "insurance_expiry": "2026-06-12",
        "insurance_coverage_inr": 2800000,
        "permit_expiry": "2026-09-28",
        "fitness_expiry": "2026-12-15",
        "pollution_expiry": "2026-06-08",
        "maintenance_due": "2026-07-25",
        "transport_mode": "road",
        "year_of_manufacture": 2022,
        "chassis_no": "MAT445192KW090123",
        "engine_no": "K4M090123F",
        "notes": "Heavy haul — Chennai Port to Delhi",
    },
    {
        "vehicle_id": "OFE-TRK-010",
        "capacity_tons": 15.0,
        "capacity_cbm": 62.0,
        "fuel_type": "Diesel",
        "insurance_provider": "United India Insurance",
        "insurance_policy": "UII-2024-TRK010",
        "insurance_expiry": "2026-08-20",
        "insurance_coverage_inr": 1900000,
        "permit_expiry": "2026-11-10",
        "fitness_expiry": "2027-02-05",
        "pollution_expiry": "2026-08-15",
        "maintenance_due": "2026-09-28",
        "transport_mode": "road",
        "year_of_manufacture": 2021,
        "chassis_no": "MAT445192KW101234",
        "engine_no": "K4M101234G",
        "notes": "Visakhapatnam operations",
    },
    {
        "vehicle_id": "OFE-TRK-011",
        "capacity_tons": 25.0,
        "capacity_cbm": 100.0,
        "fuel_type": "Diesel",
        "insurance_provider": "National Insurance Co.",
        "insurance_policy": "NIC-2024-TRK011",
        "insurance_expiry": "2026-10-30",
        "insurance_coverage_inr": 3200000,
        "permit_expiry": "2027-01-25",
        "fitness_expiry": "2027-04-18",
        "pollution_expiry": "2026-10-22",
        "maintenance_due": "2026-11-20",
        "transport_mode": "road",
        "year_of_manufacture": 2023,
        "chassis_no": "MAT445192KW112345",
        "engine_no": "K4M112345H",
        "notes": "Super heavy — bulk goods long haul",
    },
    {
        "vehicle_id": "OFE-TRK-012",
        "capacity_tons": 22.0,
        "capacity_cbm": 88.0,
        "fuel_type": "Diesel",
        "insurance_provider": "Oriental Insurance",
        "insurance_policy": "OIC-2024-TRK012",
        "insurance_expiry": "2026-01-15",
        "insurance_coverage_inr": 2600000,
        "permit_expiry": "2026-04-08",
        "fitness_expiry": "2026-07-20",
        "pollution_expiry": "2026-01-10",
        "maintenance_due": "2026-02-28",
        "transport_mode": "sea",
        "year_of_manufacture": 2020,
        "chassis_no": "MAT445192KW123456",
        "engine_no": "K4M123456I",
        "notes": "Sea-lane approved — Kochi–Mumbai route",
    },
]


def _get_collection():
    """Return the pymongo Collection, connecting lazily. Returns None if unavailable."""
    global _client, _col
    if not _PYMONGO_AVAILABLE:
        return None
    if _col is not None:
        return _col
    try:
        _client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=3000)
        _client.admin.command("ping")  # fast connectivity check
        db   = _client[MONGO_DB]
        _col = db[COLLECTION]
        _col.create_index([("vehicle_id", ASCENDING)], unique=True)
        logger.info("MongoDB connected for vehicle registry at %s", MONGO_URI)
        return _col
    except Exception as exc:
        logger.warning("MongoDB unavailable (%s) — using in-memory fallback", exc)
        _client = None
        return None


def seed_registry():
    """Seed MongoDB (or fallback) with pre-defined vehicle details if not already present."""
    col = _get_collection()
    seeded = 0
    if col is not None:
        for rec in SEED_DATA:
            try:
                existing = col.find_one({"vehicle_id": rec["vehicle_id"]})
                if not existing:
                    rec["created_at"] = datetime.now(timezone.utc).isoformat()
                    rec["updated_at"] = rec["created_at"]
                    col.insert_one(rec)
                    seeded += 1
            except Exception as exc:
                logger.warning("Seed error for %s: %s", rec["vehicle_id"], exc)
    else:
        # In-memory fallback
        for rec in SEED_DATA:
            vid = rec["vehicle_id"]
            if vid not in _fallback_store:
                _fallback_store[vid] = dict(rec)
                _fallback_store[vid]["created_at"] = datetime.now(timezone.utc).isoformat()
                seeded += 1
    logger.info("Vehicle registry seeded: %d new records", seeded)


def get_all_registry() -> list:
    """Return all vehicle registry documents as plain dicts."""
    col = _get_collection()
    if col is not None:
        docs = list(col.find({}, {"_id": 0}))
        return docs
    return list(_fallback_store.values())


def get_registry_by_id(vehicle_id: str) -> dict | None:
    """Return one vehicle registry document or None."""
    col = _get_collection()
    if col is not None:
        doc = col.find_one({"vehicle_id": vehicle_id}, {"_id": 0})
        return doc
    return _fallback_store.get(vehicle_id)


def upsert_registry(vehicle_id: str, data: dict) -> bool:
    """Create or update a vehicle registry document. Returns True on success."""
    data = dict(data)
    data.pop("_id", None)                       # strip Mongo _id if echoed back
    data["vehicle_id"]  = vehicle_id
    data["updated_at"]  = datetime.now(timezone.utc).isoformat()

    col = _get_collection()
    if col is not None:
        try:
            col.update_one(
                {"vehicle_id": vehicle_id},
                {"$set": data, "$setOnInsert": {"created_at": data["updated_at"]}},
                upsert=True
            )
            return True
        except Exception as exc:
            logger.error("upsert_registry error: %s", exc)
            return False
    else:
        if vehicle_id not in _fallback_store:
            data["created_at"] = data["updated_at"]
        _fallback_store[vehicle_id] = data
        return True


def delete_registry(vehicle_id: str) -> bool:
    """Delete a vehicle registry document. Returns True if deleted."""
    col = _get_collection()
    if col is not None:
        try:
            result = col.delete_one({"vehicle_id": vehicle_id})
            return result.deleted_count > 0
        except Exception as exc:
            logger.error("delete_registry error: %s", exc)
            return False
    else:
        if vehicle_id in _fallback_store:
            del _fallback_store[vehicle_id]
            return True
        return False
