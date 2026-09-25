"""Fixture writer for OpenCode's catalog cache (its SQLite database).

Mirrors the real v2.0 shape: table ``kv``, row ``models-dev:catalog`` whose
value is a JSON envelope carrying the provider map as a JSON string in
``body``.
"""
import json
import sqlite3

CATALOG_KV_KEY = "models-dev:catalog"


def write_catalog_db(path, providers, updated_ms=1790181352116):
    path.parent.mkdir(parents=True, exist_ok=True)
    envelope = json.dumps({"updatedAt": updated_ms, "digest": "fixture",
                           "body": json.dumps(providers)})
    con = sqlite3.connect(str(path))
    con.execute("CREATE TABLE kv (key TEXT PRIMARY KEY, value TEXT)")
    con.execute("INSERT INTO kv (key, value) VALUES (?, ?)",
                (CATALOG_KV_KEY, envelope))
    con.commit()
    con.close()
    return path
