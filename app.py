#!/usr/bin/env python3
from http.server import HTTPServer, BaseHTTPRequestHandler

class HelloHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html; charset=utf-8')
        self.end_headers()
        
        html = '''<!DOCTYPE html>
<html>
<head>
    <title>Hello World - Whale Edition</title>
    <style>
        body { font-family: monospace; background: #f0f0f0; text-align: center; padding: 40px; }
        pre { background: white; padding: 20px; border-radius: 5px; display: inline-block; }
    </style>
</head>
<body>
    <h1>Hello World! 🐋</h1>
    <pre>
    `._.,
    (    "\\___
    /         \\_
   /_,  ,_\\n \\__\\
   \\_o_o_/    \\_/
    </pre>
    <p>Running in a Docker container</p>
</body>
</html>'''
        self.wfile.write(html.encode())
    
    def log_message(self, format, *args):
        pass

if __name__ == '__main__':
    server = HTTPServer(('0.0.0.0', 8080), HelloHandler)
    print('🐋 Whale server running on http://0.0.0.0:8080')
    server.serve_forever()
