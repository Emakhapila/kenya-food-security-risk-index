import os
import psycopg
from dotenv import load_dotenv

load_dotenv()
with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
    print(conn.execute("SELECT version();").fetchone()[0])