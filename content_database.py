import json
import sqlite3
from datetime import datetime


DB_NAME = "flipradar.db"


# ==================================================
# CONNECTION
# ==================================================

def connect():

    return sqlite3.connect(
        DB_NAME
    )


# ==================================================
# INITIALIZE
# ==================================================

def initialize_content_database():

    conn = connect()
    cursor = conn.cursor()


    cursor.execute("""
        CREATE TABLE IF NOT EXISTS content_scans (
            product_id TEXT PRIMARY KEY,
            product_name TEXT,
            videos_json TEXT NOT NULL,
            fetched_at TEXT NOT NULL
        )
    """)


    conn.commit()
    conn.close()


# ==================================================
# SAVE CONTENT SCAN
# ==================================================

def save_content_scan(
    product_id,
    product_name,
    videos
):

    conn = connect()
    cursor = conn.cursor()


    fetched_at = datetime.now().isoformat(
        timespec="seconds"
    )


    cursor.execute("""
        INSERT OR REPLACE INTO content_scans (
            product_id,
            product_name,
            videos_json,
            fetched_at
        )
        VALUES (?, ?, ?, ?)
    """, (

        str(
            product_id
        ),

        product_name,

        json.dumps(
            videos
        ),

        fetched_at
    ))


    conn.commit()
    conn.close()


# ==================================================
# LOAD CONTENT SCAN
# ==================================================

def load_content_scan(
    product_id
):

    conn = connect()
    cursor = conn.cursor()


    cursor.execute("""
        SELECT
            videos_json,
            fetched_at

        FROM content_scans

        WHERE product_id = ?
    """, (

        str(
            product_id
        ),

    ))


    row = cursor.fetchone()

    conn.close()


    if not row:

        return [], None


    videos_json, fetched_at = row


    try:

        videos = json.loads(
            videos_json
        )

    except json.JSONDecodeError:

        videos = []


    return videos, fetched_at