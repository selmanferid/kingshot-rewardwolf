#!/usr/bin/env python3
from http.server import HTTPServer, BaseHTTPRequestHandler
import subprocess

class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path == '/rebuild':
            subprocess.Popen(['/home/selman/kingshot/rebuild.sh'])
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'OK')
    def log_message(self, *args): pass

HTTPServer(('0.0.0.0', 9999), Handler).serve_forever()
