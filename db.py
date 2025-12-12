import os
import json
import psycopg2
from datetime import datetime

DB_NAME = "railway"                       # PGDATABASE
DB_USER = "postgres"                      # PGUSER
DB_PASSWORD = "KabjEWZlzLUmdxXWUTBSiQgQkcJUvNFC"  # PGPASSWORD (Updated)
DB_HOST = "postgres.railway.internal"     # PGHOST
DB_PORT = "5432"                          # PGPORT

def get_db_connection():
    import psycopg2
    return psycopg2.connect(
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

