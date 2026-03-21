#!/usr/bin/env python3
from http.server import HTTPServer, BaseHTTPRequestHandler
import subprocess

class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path == '/rebuild':
            subprocess.Popen(['/home/selman/kingshot/rebuild.sh'])
            self._ok()
        elif self.path == '/kill-zombies':
            # Sadece defunct (zombie) Chromium process'leri öldür
            subprocess.run(
                "ps aux | grep chromium | grep '<defunct>' | awk '{print $2}' | xargs -r kill -9",
                shell=True, capture_output=True
            )
            self._ok()
        elif self.path == '/start':
            subprocess.run(['docker', 'update', '--restart=unless-stopped', 'kingshot-daemon'], capture_output=True)
            subprocess.run(['docker', 'start', 'kingshot-daemon'], capture_output=True)
            self._ok()
        elif self.path == '/stop':
            subprocess.run(['docker', 'update', '--restart=no', 'kingshot-daemon'], capture_output=True)
            subprocess.run(['docker', 'stop', 'kingshot-daemon'], capture_output=True)
            self._ok()
        elif self.path == '/restart':
            subprocess.run(['docker', 'restart', 'kingshot-daemon'], capture_output=True)
            self._ok()
        else:
            self.send_response(404)
            self.end_headers()

    def _ok(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'OK')

    def log_message(self, *args):
        pass

HTTPServer(('0.0.0.0', 9999), Handler).serve_forever()
