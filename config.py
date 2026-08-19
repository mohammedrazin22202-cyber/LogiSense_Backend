"""
Fleet Command - Runtime Configuration
======================================
All runtime settings are read from environment variables with sensible
local-development defaults.  Override these when deploying to production.

Environment Variables
---------------------
FLEET_DB_PATH   Path to the SQLite database file.
                Default: <backend_dir>/data/fleet.db

MONGO_URI       MongoDB connection URI.
                Default: mongodb://localhost:27017  (disabled when unreachable)

MONGO_DB_NAME   MongoDB database name.
                Default: fleet_command

ADMIN_USER      Admin login username.   Default: MegaTron
ADMIN_PASS      Admin login password.   Default: MG@88307
ADMIN_OTP       Admin OTP code.         Default: 213069
ADMIN_PIN       Admin PIN.              Default: 8181

PORT            TCP port for the Flask server.  Default: 1995

NOTE: The MySQL config that was here previously has been removed.
      The backend uses SQLite (via database.py) — not MySQL.
"""
import os

# SQLite
FLEET_DB_PATH = os.environ.get(
    'FLEET_DB_PATH',
    os.path.join(os.path.dirname(__file__), 'data', 'fleet.db')
)

# MongoDB (optional — app degrades gracefully if unavailable)
MONGO_URI     = os.environ.get('MONGO_URI', 'mongodb://localhost:27017')
MONGO_DB_NAME = os.environ.get('MONGO_DB_NAME', 'fleet_command')

# Admin credentials (validated server-side via /api/admin/auth)
ADMIN_USER = os.environ.get('ADMIN_USER', 'MegaTron')
ADMIN_PASS = os.environ.get('ADMIN_PASS', 'MG@88307')
ADMIN_OTP  = os.environ.get('ADMIN_OTP',  '213069')
ADMIN_PIN  = os.environ.get('ADMIN_PIN',  '8181')

# Server port
PORT = int(os.environ.get('PORT', 1995))

# Commit tweak 1: fix: clarify FLEET_DB_PATH fallback behavior in config

# Commit tweak 11: style: cleanup empty lines at end of configuration file
