# LogiSense 360 — Backend API Server

Flask REST API + SQLite database + MongoDB registry + real-time SSE stream for the LogiSense 360 fleet management platform.

---

## Requirements

- **Python 3.9+**
- **Node.js** is NOT required for the backend
- MySQL running locally (or configure a remote connection in `config.py`)
- MongoDB running locally (optional — registry features degrade gracefully if unavailable)

---

## Folder Structure

```
backend/
├── server.py          # Main Flask app — all REST API + SSE endpoints
├── database.py        # SQLite helpers (init_db, get_db, log_event)
├── config.py          # MySQL connection settings ← edit this
├── mongo_registry.py  # MongoDB vehicle registry
├── simulation.py      # Background vehicle simulation engine
├── seed.py            # Seeds MySQL + SQLite from orders_master.xlsx
├── requirements.txt   # Python dependencies
├── start.bat          # Windows startup script
└── data/              # Runtime data (auto-created)
    ├── fleet.db       # SQLite database
    └── fleet.log      # Application log
```

---

## Setup & Running

### 1. Configure the database

Edit `config.py` and set your MySQL credentials:

```python
DB_CONFIG = {
    'host':     'localhost',
    'port':     3306,
    'user':     'root',       # ← your MySQL username
    'password': '',           # ← your MySQL password
    'database': 'fleet_command',
}
```

### 2. Run the server (Windows)

Double-click **`start.bat`** — it will:
- Install all Python dependencies automatically
- Seed the database from `orders_master.xlsx` (place it in `backend/` or `backend/data/`)
- Start the API server at **http://localhost:1995**

### 3. Manual startup

```bash
pip install -r requirements.txt
python seed.py
python server.py
```

---

## API Overview

| Base URL | `http://localhost:1995/api/` |
|---|---|
| Vehicles | `GET/POST /api/vehicles` |
| Orders | `GET /api/orders` |
| Alerts | `GET /api/alerts` |
| Routes | `GET/POST /api/routes` |
| Warehouses | `GET/POST /api/warehouses` |
| Drivers | `GET/POST /api/drivers` |
| Live stream | `GET /api/stream` (SSE) |

All endpoints return JSON. CORS is enabled for all `/api/*` routes so the frontend can be hosted separately.

---

## Deployment (Render)

1. Push the `backend/` folder to a GitHub repo
2. Create a new **Web Service** on [render.com](https://render.com)
3. Set **Build Command**: `pip install -r requirements.txt`
4. Set **Start Command**: `python server.py`
5. Add environment variables for `MONGO_URI` if using MongoDB Atlas
6. Copy the Render URL and paste it into `frontend/config.js`
