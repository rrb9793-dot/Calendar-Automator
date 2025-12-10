import os
import json
import psycopg2
from datetime import datetime

# --- CONFIGURATION ---
DB_NAME = os.environ.get("PGDATABASE", "railway")
DB_USER = os.environ.get("PGUSER", "postgres")
DB_PASSWORD = os.environ.get("PGPASSWORD", "mOUfapERMofXipKrrolKOZYGpKgzuokF")
DB_HOST = os.environ.get("PGHOST", "postgres.railway.internal")
DB_PORT = os.environ.get("PGPORT", "5432")

def get_db_connection():
    try:
        conn = psycopg2.connect(
            dbname=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD,
            host=DB_HOST,
            port=DB_PORT
        )
        return conn
    except Exception as e:
        print(f"❌ Database Connection Error: {e}")
        return None

