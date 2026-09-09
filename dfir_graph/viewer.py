"""Read-only loopback viewer. No arbitrary filesystem paths or Cypher accepted."""

import json
import os
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .store import Store
from .timeline import TimelineCache
from .analysis import build_brief, markdown_report, local_ai_status, generate_hypotheses


def serve(database, port=8765, ai_model=None):
    database = Path(database).resolve()
    if not database.is_file():
        raise ValueError("Import evidence before starting the viewer")
    assets = Path(__file__).parent / "static"
    timeline = TimelineCache(database)
    ai_lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def send(self, status, data, content_type="application/json; charset=utf-8"):
            body = data if isinstance(data, bytes) else json.dumps(data, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            allowed = {f"127.0.0.1:{port}", f"localhost:{port}"}
            if self.headers.get("Host", "") not in allowed:
                self.send(403, {"error": "Loopback host required"})
                return
            parsed = urlparse(self.path)
            static = {"/": ("index.html", "text/html; charset=utf-8"),
                      "/app.js": ("timeline.js", "application/javascript; charset=utf-8"),
                      "/style.css": ("style.css", "text/css; charset=utf-8"),
                      "/graph.js": ("graph.js", "application/javascript; charset=utf-8"),
                      "/graph.css": ("graph.css", "text/css; charset=utf-8"),
                      "/vendor/cytoscape.min.js": ("vendor/cytoscape.min.js", "application/javascript; charset=utf-8")}
            if parsed.path in static:
                name, mime = static[parsed.path]
                self.send(200, (assets / name).read_bytes(), mime)
                return
            query = parse_qs(parsed.query)
            arg = lambda name, default="": query.get(name, [default])[0]
            store = Store(database, readonly=True)
            try:
                if parsed.path == "/api/stats":
                    result = store.stats()
                elif parsed.path == "/api/timeline/meta":
                    result = timeline.get().meta()
                elif parsed.path == "/api/timeline/map":
                    result = timeline.get().view(start=arg("start"), end=arg("end"), bins=arg("bins", "60"),
                        offset=arg("offset", "0"), limit=arg("limit", "50"),
                        **{key: arg(key) for key in ("case", "host", "scope", "lanes", "q")})
                elif parsed.path == "/api/timeline/related":
                    result = timeline.get().related(arg("id"), arg("offset", "0"), arg("limit", "30"))
                elif parsed.path == "/api/timeline/item":
                    result = timeline.get().by_id.get(arg("id"))
                elif parsed.path == "/api/analysis":
                    result = build_brief(timeline.get(), arg("id"))
                elif parsed.path == "/api/analysis/report":
                    brief = build_brief(timeline.get(), arg("id"))
                    self.send(200, markdown_report(brief).encode('utf-8'), 'text/markdown; charset=utf-8')
                    return
                elif parsed.path == "/api/analysis/status":
                    result = local_ai_status(ai_model)
                elif parsed.path == "/api/search":
                    result = store.search(arg("q"), arg("label") or None, int(arg("limit", "30")))
                elif parsed.path == "/api/graph/neighbors":
                    result = store.graph_neighbors(arg("id"), depth=arg("depth", "1"),
                        node_limit=arg("nodes", "100"), edge_limit=arg("edges", "180"),
                        include_structure=arg("structure", "0") == "1",
                        scope=arg("scope"), case_id=arg("case") or None)
                elif parsed.path == "/api/graph":
                    result = store.neighborhood(arg("id"), int(arg("limit", "30")))
                elif parsed.path == "/api/evidence":
                    result = store.evidence(arg("id"))
                elif parsed.path == "/api/filesystem/sources":
                    from .filesystem import FileIndex, available
                    if available(store.db):
                        fi = FileIndex(store.db)
                        result = fi.sources(arg("case"))
                    else:
                        result = []
                elif parsed.path == "/api/filesystem/search":
                    from .filesystem import FileIndex, available
                    if not available(store.db):
                        result = {"items": [], "total": 0, "offset": 0, "limit": 50}
                    else:
                        fi = FileIndex(store.db)
                        result = fi.search(case=arg("case"), q=arg("q"), path=arg("path"),
                                           slot=arg("slot", "created"),
                                           offset=arg("offset", "0"), limit=arg("limit", "50"))
                elif parsed.path == "/api/filesystem/evidence":
                    from .filesystem import FileIndex, available
                    if not available(store.db):
                        result = None
                    else:
                        fi = FileIndex(store.db)
                        result = fi.evidence(arg("id"))
                elif parsed.path == "/api/detections":
                    from .sigma_engine import list_detections
                    result = list_detections(database, case_id=arg("case") or None,
                        level=arg("level") or None, rule_id=arg("rule") or None,
                        limit=int(arg("limit", "50")))
                elif parsed.path == "/api/detections/stats":
                    from .sigma_engine import detection_stats
                    result = detection_stats(database, case_id=arg("case") or None)
                elif parsed.path == "/api/issues":
                    result = [dict(r) for r in store.db.execute("SELECT code,message,record_id FROM issues ORDER BY code,id LIMIT 200")]
                elif parsed.path == "/api/timeline":
                    result = [dict(r) for r in store.db.execute("""SELECT id,kind,host,scope,time_raw,time_utc
                        FROM records WHERE kind<>'evtx_other' AND time_utc IS NOT NULL
                        ORDER BY time_utc DESC,id LIMIT 100""")]
                else:
                    self.send(404, {"error": "Not found"})
                    return
                self.send(200 if result is not None else 404, result)
            except ValueError as exc:
                self.send(400, {"error": str(exc)})
            finally:
                store.close()

        def do_POST(self):
            # Only a same-origin, JSON request can spend local model resources.
            host = self.headers.get('Host', '')
            if host not in {f'127.0.0.1:{port}', f'localhost:{port}'} or self.headers.get('Origin') != 'http://' + host:
                self.send(403, {'error':'Same-origin request required'})
                return
            if self.path != '/api/analysis/ai':
                self.send(404, {'error':'Not found'})
                return
            if self.headers.get('Content-Type') != 'application/json':
                self.send(415, {'error':'JSON required'})
                return
            acquired = False
            try:
                length = int(self.headers.get('Content-Length','0'))
                if not 0 < length <= 2048:
                    raise ValueError('Invalid request size')
                request = json.loads(self.rfile.read(length))
                if not isinstance(request,dict) or not isinstance(request.get('id'),str):
                    raise ValueError('Record identifier required')
                acquired = ai_lock.acquire(blocking=False)
                if not acquired:
                    self.send(409, {'error':'다른 로컬 AI 분석이 진행 중입니다.'})
                    return
                brief = build_brief(timeline.get(), request['id'])
                self.send(200, generate_hypotheses(brief, ai_model))
            except (ValueError, UnicodeError) as exc:
                self.send(400, {'error':str(exc)})
            finally:
                if acquired:
                    ai_lock.release()

        def log_message(self, format, *args):
            # Do not write evidence searches or identifiers into HTTP access logs.
            pass

    class LocalServer(ThreadingHTTPServer):
        # Windows SO_REUSEADDR can let two viewers bind the same port, leaving
        # the browser attached to stale code. Fail clearly instead.
        allow_reuse_address = os.name != "nt"

        def server_bind(self):
            if os.name == "nt":
                self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            super().server_bind()

    server = LocalServer(("127.0.0.1", port), Handler)
    print(f"DFIR evidence viewer: http://127.0.0.1:{port}", flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()
