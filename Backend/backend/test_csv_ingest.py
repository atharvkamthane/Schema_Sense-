import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

import pandas as pd
import ingest_handler

# Create a test CSV
test_csv_path = os.path.join(BASE_DIR, "test_data.csv")
test_data = pd.DataFrame({
    "customer_id": ["cust001", "cust002", "cust003"],
    "name": ["Alice", "Bob", "Charlie"],
    "amount": [100.00, 250.50, 75.25]
})
test_data.to_csv(test_csv_path, index=False)
print(f"✓ Created test CSV at {test_csv_path}")

# Test CSV ingestion
print("\n--- Testing CSV Ingestion ---")
result = ingest_handler.create_table_from_csv(test_csv_path)
print(f"Result: {result}")

if result['success']:
    print(f"✓ CSV parsed successfully")
    print(f"  Table: {result['table_name']}")
    print(f"  Rows: {result['row_count']}")
    print(f"  Columns: {result['columns']}")
    
    # Verify database.sqlite now has the new table
    import sqlite3
    conn = sqlite3.connect("database.sqlite")
    cursor = conn.cursor()
    cursor.execute(f"SELECT * FROM {result['table_name']} LIMIT 2")
    rows = cursor.fetchall()
    conn.close()
    print(f"✓ Data loaded in database.sqlite: {len(rows)} rows verified")
else:
    print(f"✗ CSV ingestion failed: {result['error']}")

# Clean up test file
os.remove(test_csv_path)
print("\n✓ Test complete")
