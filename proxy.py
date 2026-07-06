"""Tiny proxy so the managed preview server can reach Flask on 5003."""
import http.server
import urllib.request
import sys

class Proxy(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        try:
            url = 'http://127.0.0.1:5003' + self.path
            resp = urllib.request.urlopen(url, timeout=30)
            body = resp.read()
            self.send_response(resp.status)
            for k, v in resp.getheaders():
                if k.lower() not in ('transfer-encoding', 'connection', 'date', 'server'):
                    self.send_header(k, v)
            self.send_header('Content-Length', len(body))
            self.end_headers()
            self.wfile.write(body)
        except Exception as e:
            self.send_error(502, str(e))

if __name__ == '__main__':
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 5003
    http.server.HTTPServer(('127.0.0.1', port), Proxy).serve_forever()
