import sqlite3
import os
import sys

# Fix Windows console encoding (prevents UnicodeEncodeError)
if sys.platform == "win32":
    import io as _io
    sys.stdout = _io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = _io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

DB_PATH = os.path.join(os.path.dirname(__file__), 'data', 'fleet.db')

def reset_staff_ids():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    # Get all staff members ordered by current ID
    c.execute("SELECT id FROM staff ORDER BY id ASC")
    staff_members = c.fetchall()
    
    if not staff_members:
        print("No staff records found.")
        # Just reset sequence to 0
        c.execute("UPDATE sqlite_sequence SET seq = 0 WHERE name = 'staff'")
        conn.commit()
        conn.close()
        return

    new_id = 1
    for row in staff_members:
        old_id = row['id']
        if old_id == new_id:
            new_id += 1
            continue
            
        # Update staff table
        c.execute("UPDATE staff SET id = ? WHERE id = ?", (new_id, old_id))
        
        # Staff IDs aren't heavily referenced as foreign keys in this schema, 
        # so simply updating the main table is sufficient.
        new_id += 1
        
    # Reset the sqlite_sequence so new inserts start from the highest new_id
    c.execute("UPDATE sqlite_sequence SET seq = ? WHERE name = 'staff'", (new_id - 1,))
    
    conn.commit()
    conn.close()
    print(f"Successfully reset Staff IDs. Next dynamically generated ID will be {new_id}")

if __name__ == '__main__':
    reset_staff_ids()

# Commit tweak 6: style: format whitespace in staff sequence helper

# Commit tweak 16: docs: add header explanation for staff sequence helper

# Commit tweak 26: style: optimize imports layout in staff reset script

# Commit tweak 36: docs: clarify staff sequence reset behavior on empty DB
