from pathlib import Path
from config import BASE_OUTPUT_DIR
import sqlite3
import json
from typing import Optional

DB_PATH = Path(BASE_OUTPUT_DIR) / 'terra.db'

# Copying original DB helper functions - trimmed for brevity

def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    try:
        cur = conn.cursor()
        # Create assets table
        cur.execute('''
        CREATE TABLE IF NOT EXISTS assets (
            asset_id TEXT PRIMARY KEY,
            product TEXT,
            sensor TEXT,
            url_s3 TEXT,
            epsg INTEGER,
            resolution_m REAL,
            acquired_ts TEXT,
            ingested_ts TEXT,
            footprint TEXT,
            bbox TEXT,
            min_val REAL,
            max_val REAL,
            mean_val REAL,
            stddev_val REAL,
            cog_ok INTEGER,
            tenant_id TEXT,
            plot_id TEXT
        )''')

        # Create measurements table
        cur.execute('''
        CREATE TABLE IF NOT EXISTS measurements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            metric_id TEXT,
            tenant_id TEXT,
            plot_id TEXT,
            ts TEXT,
            metric_type TEXT,
            value REAL,
            quality TEXT
        )''')

        conn.commit()
    finally:
        conn.close()


def _connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def insert_asset(asset_id: str, product: str = None, sensor: str = None, url_s3: str = None,
                 epsg: int = None, resolution_m: float = None, acquired_ts: str = None,
                 ingested_ts: str = None, footprint: Optional[dict] = None, bbox: Optional[list] = None,
                 min_val: float = None, max_val: float = None, mean_val: float = None, stddev_val: float = None,
                 cog_ok: bool = False, tenant_id: str = None, plot_id: str = None):
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute('''
        INSERT OR REPLACE INTO assets(asset_id, product, sensor, url_s3, epsg, resolution_m, acquired_ts, ingested_ts, footprint, bbox, min_val, max_val, mean_val, stddev_val, cog_ok, tenant_id, plot_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            asset_id, product, sensor, url_s3, epsg, resolution_m, acquired_ts, ingested_ts,
            json.dumps(footprint) if footprint is not None else None,
            json.dumps(bbox) if bbox is not None else None,
            min_val, max_val, mean_val, stddev_val, 1 if cog_ok else 0, tenant_id, plot_id
        ))
        conn.commit()
    finally:
        conn.close()


def get_asset(asset_id: str):
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute('SELECT * FROM assets WHERE asset_id = ?', (asset_id,))
        row = cur.fetchone()
        if not row:
            return None
        d = dict(row)
        # parse JSON fields
        try:
            d['footprint'] = json.loads(d['footprint']) if d.get('footprint') else None
        except Exception:
            d['footprint'] = d.get('footprint')
        try:
            d['bbox'] = json.loads(d['bbox']) if d.get('bbox') else None
        except Exception:
            d['bbox'] = d.get('bbox')
        # cast cog_ok
        try:
            d['cog_ok'] = bool(d.get('cog_ok'))
        except Exception:
            d['cog_ok'] = False
        return d
    finally:
        conn.close()


def list_assets(tenant_id: str = None, plot_id: str = None, limit: int = 100):
    conn = _connect()
    try:
        cur = conn.cursor()
        q = 'SELECT * FROM assets'
        params = []
        clauses = []
        if tenant_id:
            clauses.append('tenant_id = ?')
            params.append(tenant_id)
        if plot_id:
            clauses.append('plot_id = ?')
            params.append(plot_id)
        if clauses:
            q += ' WHERE ' + ' AND '.join(clauses)
        q += ' ORDER BY ingested_ts DESC LIMIT ?'
        params.append(limit)
        cur.execute(q, tuple(params))
        rows = cur.fetchall()
        results = []
        for r in rows:
            d = dict(r)
            try:
                d['footprint'] = json.loads(d['footprint']) if d.get('footprint') else None
            except Exception:
                d['footprint'] = d.get('footprint')
            try:
                d['bbox'] = json.loads(d['bbox']) if d.get('bbox') else None
            except Exception:
                d['bbox'] = d.get('bbox')
            try:
                d['cog_ok'] = bool(d.get('cog_ok'))
            except Exception:
                d['cog_ok'] = False
            results.append(d)
        return results
    finally:
        conn.close()


def insert_measurement(metric_id: str = None, tenant_id: str = None, plot_id: str = None,
                       ts: str = None, metric_type: str = None, value: float = None, quality: str = None):
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute('''
        INSERT INTO measurements(metric_id, tenant_id, plot_id, ts, metric_type, value, quality)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (metric_id, tenant_id, plot_id, ts, metric_type, value, quality))
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def get_measurement(metric_id: str):
    if metric_id is None:
        return None
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute('SELECT * FROM measurements WHERE metric_id = ? LIMIT 1', (metric_id,))
        row = cur.fetchone()
        if not row:
            return None
        d = dict(row)
        # convert types
        try:
            d['value'] = float(d['value']) if d.get('value') is not None else None
        except Exception:
            d['value'] = d.get('value')
        return d
    finally:
        conn.close()


def list_measurements(plot_id: str = None, metric_type: str = None, limit: int = 500):
    conn = _connect()
    try:
        cur = conn.cursor()
        q = 'SELECT * FROM measurements'
        clauses = []
        params = []
        if plot_id:
            clauses.append('plot_id = ?')
            params.append(plot_id)
        if metric_type:
            clauses.append('metric_type = ?')
            params.append(metric_type)
        if clauses:
            q += ' WHERE ' + ' AND '.join(clauses)
        q += ' ORDER BY ts DESC LIMIT ?'
        params.append(limit)
        cur.execute(q, tuple(params))
        rows = cur.fetchall()
        results = []
        for r in rows:
            d = dict(r)
            try:
                d['value'] = float(d['value']) if d.get('value') is not None else None
            except Exception:
                d['value'] = d.get('value')
            results.append(d)
        return results
    finally:
        conn.close()

# insert_asset, get_asset, list_assets, insert_measurement should be copied from original db.py as needed
