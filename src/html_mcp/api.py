"""JSON API endpoints used by the management page in the browser.

Four endpoints (design §7.3 / §8):

  - ``GET /api/files``                Bearer; list docroot
  - ``DELETE /api/files/<name>``      Bearer; delete
  - ``GET /api/nginx-config``         Bearer; rendered server block
  - ``GET /api/health``               NO AUTH; liveness probe

Each handler is a closure over ``cfg`` (built by ``register_routes``).
Storage exceptions map to HTTP status codes per design §7.3.
"""
import json
from pathlib import Path
from typing import Any, Dict, Tuple

from html_mcp import nginx_config as nginx_mod
from html_mcp import server as srv
from html_mcp import storage
from html_mcp.auth import check_bearer
from html_mcp.config import Config

from ._version import VERSION


JSON = {"Content-Type": "application/json"}
TEXT = {"Content-Type": "text/plain; charset=utf-8"}


# --- helpers -----------------------------------------------------------------

def _unauthorized() -> Tuple[int, bytes, Dict[str, str]]:
    return (
        401,
        b'{"error":"unauthorized"}',
        JSON,
    )


def _require_bearer(req, cfg: Config):
    """Return None on success, or an error response tuple."""
    if not check_bearer(req.headers.get("Authorization"), cfg.token):
        return _unauthorized()
    return None


def _storage_error(exc: storage.StorageError):
    """Map a storage exception to an HTTP response."""
    if isinstance(exc, storage.InvalidName):
        return (400, _err("invalid_name", str(exc)), JSON)
    if isinstance(exc, storage.Conflict):
        return (409, _err("conflict", str(exc)), JSON)
    if isinstance(exc, storage.TooLarge):
        return (413, _err("too_large", str(exc)), JSON)
    if isinstance(exc, storage.NotFound):
        return (404, _err("not_found", str(exc)), JSON)
    if isinstance(exc, storage.DocrootUnwritable):
        return (500, _err("docroot_unwritable", str(exc)), JSON)
    # Unknown storage error → 500.
    return (500, _err("storage_error", str(exc)), JSON)


def _err(code: str, msg: str) -> bytes:
    return json.dumps({"error": code, "message": msg}).encode("utf-8")


def _file_info_payload(f: storage.FileInfo, public_base_url: str) -> Dict[str, Any]:
    return {
        "name": f.name,
        "size": f.size,
        "mtime": f.mtime,
        "url": public_base_url.rstrip("/") + "/" + f.name,
        "title": f.title,
    }


# --- handlers ----------------------------------------------------------------

def _make_list_files(cfg: Config):
    def handler(req, params, body):
        # No auth: list_html returns public metadata (name/size/mtime/title/url)
        # of files in a docroot that nginx already serves unauthenticated at
        # /files/*. Single-user trust model + nginx reverse proxy in front.
        # Write paths (DELETE /api/files/<name>, POST /mcp) still require
        # Bearer — the management page does not expose those.
        docroot = Path(cfg.docroot)
        try:
            files = storage.list_files(docroot)
        except storage.StorageError as exc:
            return _storage_error(exc)
        payload = {
            "files": [_file_info_payload(f, cfg.public_base_url) for f in files]
        }
        return (200, json.dumps(payload).encode("utf-8"), JSON)
    return handler


def _make_delete_file(cfg: Config):
    def handler(req, params, body):
        err = _require_bearer(req, cfg)
        if err:
            return err
        name = params.get("name", "")
        docroot = Path(cfg.docroot)
        try:
            deleted = storage.delete(docroot, name)
        except storage.StorageError as exc:
            return _storage_error(exc)
        if not deleted:
            return (404, _err("not_found", "file does not exist: {}".format(name)), JSON)
        return (200, json.dumps({"deleted": True}).encode("utf-8"), JSON)
    return handler


def _make_nginx_config(cfg: Config):
    def handler(req, params, body):
        err = _require_bearer(req, cfg)
        if err:
            return err
        text = nginx_mod.render(
            docroot=cfg.docroot,
            port=cfg.port,
            public_base_url=cfg.public_base_url,
        )
        return (200, text.encode("utf-8"), TEXT)
    return handler


def _health_handler(req, params, body):
    """No auth — health probes must be reachable without a token."""
    payload = {"status": "ok", "version": VERSION}
    return (200, json.dumps(payload).encode("utf-8"), JSON)


# --- registration ------------------------------------------------------------

def register_routes(cfg: Config) -> None:
    """Register all /api/* and /health routes on the server registry."""
    srv.register("GET", r"^/api/files$", _make_list_files(cfg))
    srv.register("DELETE", r"^/api/files/(?P<name>[^/]+)$", _make_delete_file(cfg))
    srv.register("GET", r"^/api/nginx-config$", _make_nginx_config(cfg))
    srv.register("GET", r"^/api/health$", _health_handler)