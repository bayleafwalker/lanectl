import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from tests.test_attention_record_boundary_acceptance import http

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args): pass
    def do_GET(self):
        status, name, value = {'/lower':(307,'location','/login'),'/title':(307,'Location','/login'),
                               '/missing':(307,None,None),'/wrong':(307,'location','/other'),
                               '/status':(200,'location','/login')}[self.path]
        self.send_response(status)
        if name: self.send_header(name,value)
        self.end_headers()
server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
try:
    for path,expected in [('/lower',True),('/title',True),('/missing',False),('/wrong',False),('/status',False)]:
        status,headers,_=http(f'http://127.0.0.1:{server.server_port}'+path)
        try:
            assert status in (303,307,308) and urllib.parse.urlsplit(headers['Location']).path == '/login'
            accepted=True
        except (AssertionError,TypeError,AttributeError):
            accepted=False
        assert accepted == expected,(path,status,dict(headers))
        print(path, 'accepted' if accepted else 'rejected')
finally:
    server.shutdown();server.server_close();thread.join(timeout=5);assert not thread.is_alive()
