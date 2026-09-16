import importlib.util
from pathlib import Path
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
import pytest

spec=importlib.util.spec_from_file_location('scenario_runner',Path(__file__).resolve().parents[1]/'scripts/scenario_runner.py')
runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner)

def test_lab_boundary_and_redirect_no_follow(monkeypatch):
    class Handler(BaseHTTPRequestHandler):
        hits=0
        def do_GET(self):
            Handler.hits+=1;self.send_response(302);self.send_header('Location','https://example.com/');self.end_headers()
        def log_message(self,*args):pass
    server=HTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        parsed,ips=runner.target(f'http://127.0.0.1:{server.server_port}',True)
        result=runner.request(parsed,ips[0],'GET','/',None,None)
        assert result['status']==302 and Handler.hits==1
    finally:server.shutdown();server.server_close();thread.join()
    monkeypatch.setattr(runner.socket,'getaddrinfo',lambda *a,**k:[(0,0,0,'',('203.0.113.5',443))])
    with pytest.raises(ValueError,match='outside'):runner.target('https://outside.example')
    with pytest.raises(ValueError,match='loopback'):runner.target('https://outside.example',True)

def test_bounded_requests_and_no_unsupported_chain():
    assert len(runner.actions('S2'))==12
    assert all('ea-nonexistent-user' in body for _,_,body in runner.actions('S2'))
    with pytest.raises(ValueError):runner.actions('S4')
