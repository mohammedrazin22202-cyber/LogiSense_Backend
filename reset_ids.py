import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'fleet.db')

def reset_client_ids():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    # Get all clients ordered by current ID
    c.execute("SELECT id FROM clients ORDER BY id ASC")
    clients = c.fetchall()
    
    if not clients:
        print("No clients found.")
        # Just reset sequence to 0
        c.execute("UPDATE sqlite_sequence SET seq = 0 WHERE name = 'clients'")
        conn.commit()
        conn.close()
        return

    new_id = 1
    for row in clients:
        old_id = row['id']
        if old_id == new_id:
            new_id += 1
            continue
            
        # Update clients table
        c.execute("UPDATE clients SET id = ? WHERE id = ?", (new_id, old_id))
        
        # Update all foreign key references (client_id is mostly stored as TEXT or INTEGER)
        # Orders
        c.execute("UPDATE orders SET client_id = ? WHERE client_id = ?", (str(new_id), str(old_id)))
        # Invoices
        c.execute("UPDATE invoices SET client_id = ? WHERE client_id = ?", (str(new_id), str(old_id)))
        # Contracts
        c.execute("UPDATE contracts SET client_id = ? WHERE client_id = ?", (str(new_id), str(old_id)))
        # Freight rate cards
        c.execute("UPDATE freight_rate_cards SET client_id = ? WHERE client_id = ?", (str(new_id), str(old_id)))
        
        new_id += 1
        
    # Reset the sqlite_sequence so new inserts start from the highest new_id
    c.execute("UPDATE sqlite_sequence SET seq = ? WHERE name = 'clients'", (new_id - 1,))
    
    conn.commit()
    conn.close()
    print(f"Successfully reset client IDs. Next ID will be {new_id}")

if __name__ == '__main__':
    reset_client_ids()
