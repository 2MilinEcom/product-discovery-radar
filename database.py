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
# INITIALIZE DATABASE
# ==================================================

def initialize_database():

    conn = connect()
    cursor = conn.cursor()


    # --------------------------------------------------
    # HISTORICAL SCAN SNAPSHOTS
    # --------------------------------------------------

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id TEXT,
            name TEXT,
            price REAL,
            daily_sales INTEGER,
            seven_day_sales INTEGER,
            creators INTEGER,
            growth REAL,
            score REAL,
            timestamp TEXT
        )
    """)


    # --------------------------------------------------
    # WATCHLIST
    # --------------------------------------------------

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS watchlist (
            product_id TEXT PRIMARY KEY,
            name TEXT
        )
    """)


    # --------------------------------------------------
    # LATEST MARKET SCAN
    #
    # This is what gives FlipRadar persistence.
    # Each product is stored as JSON.
    # --------------------------------------------------

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS latest_products (
            product_id TEXT PRIMARY KEY,
            product_json TEXT NOT NULL,
            scanned_at TEXT NOT NULL
        )
    """)


    conn.commit()
    conn.close()


# ==================================================
# SAVE INDIVIDUAL HISTORICAL SNAPSHOT
# ==================================================

def save_snapshot(product):

    conn = connect()
    cursor = conn.cursor()


    cursor.execute("""
        INSERT INTO snapshots (
            product_id,
            name,
            price,
            daily_sales,
            seven_day_sales,
            creators,
            growth,
            score,
            timestamp
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (

        str(
            product["id"]
        ),

        product["name"],

        float(
            product.get(
                "price",
                0
            )
            or 0
        ),

        int(
            product.get(
                "daily_sales",
                0
            )
            or 0
        ),

        int(
            product.get(
                "seven_day_sales",
                0
            )
            or 0
        ),

        int(
            product.get(
                "creators",
                0
            )
            or 0
        ),

        float(
            product.get(
                "growth",
                0
            )
            or 0
        ),

        float(
            product.get(
                "score",
                0
            )
            or 0
        ),

        datetime.now().isoformat(
            timespec="seconds"
        )
    ))


    conn.commit()
    conn.close()


# ==================================================
# SAVE ENTIRE LATEST SCAN
# ==================================================

def save_latest_scan(products):

    conn = connect()
    cursor = conn.cursor()


    scanned_at = datetime.now().isoformat(
        timespec="seconds"
    )


    # --------------------------------------------------
    # Remove previous cached market scan.
    #
    # Historical information is still preserved in
    # the snapshots table.
    # --------------------------------------------------

    cursor.execute(
        "DELETE FROM latest_products"
    )


    # --------------------------------------------------
    # Save the newest product list.
    # --------------------------------------------------

    for product in products:

        cursor.execute("""
            INSERT INTO latest_products (
                product_id,
                product_json,
                scanned_at
            )
            VALUES (?, ?, ?)
        """, (

            str(
                product["id"]
            ),

            json.dumps(
                product
            ),

            scanned_at
        ))


    conn.commit()
    conn.close()


# ==================================================
# LOAD LATEST SAVED SCAN
# ==================================================

def load_latest_scan():

    conn = connect()
    cursor = conn.cursor()


    cursor.execute("""
        SELECT
            product_json,
            scanned_at

        FROM latest_products

        ORDER BY product_id
    """)


    rows = cursor.fetchall()

    conn.close()


    products = []

    scanned_at = None


    for product_json, timestamp in rows:

        try:

            product = json.loads(
                product_json
            )

            products.append(
                product
            )

            scanned_at = timestamp

        except json.JSONDecodeError:

            continue


    return products, scanned_at


# ==================================================
# PRODUCT HISTORY
# ==================================================

def get_product_history(
    product_id
):

    conn = connect()
    cursor = conn.cursor()


    cursor.execute("""
        SELECT
            timestamp,
            price,
            daily_sales,
            seven_day_sales,
            creators,
            growth,
            score

        FROM snapshots

        WHERE product_id = ?

        ORDER BY timestamp ASC
    """, (

        str(
            product_id
        ),

    ))


    rows = cursor.fetchall()

    conn.close()


    return rows


# ==================================================
# ADD TO WATCHLIST
# ==================================================

def add_to_watchlist(
    product
):

    conn = connect()
    cursor = conn.cursor()


    cursor.execute("""
        INSERT OR REPLACE INTO watchlist (
            product_id,
            name
        )
        VALUES (?, ?)
    """, (

        str(
            product["id"]
        ),

        product["name"]
    ))


    conn.commit()
    conn.close()


# ==================================================
# GET WATCHLIST
# ==================================================

def get_watchlist():

    conn = connect()
    cursor = conn.cursor()


    cursor.execute("""
        SELECT
            product_id,
            name

        FROM watchlist

        ORDER BY name ASC
    """)


    rows = cursor.fetchall()

    conn.close()


    return rows