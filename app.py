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
    <title>Hello World</title>
    </head>
    <body>
    <pre>
Hello World


                                       ##         .
                                 ## ## ##        ==
                              ## ## ## ## ##    ===
                           /""""""""""""""""\___/ ===
                      ~~~ {~~ ~~~~ ~~~ ~~~~ ~~ ~ /  ===- ~~~
                           \______ o          _,/
                            \      \       _,'
                             `'--.._\..--''
    </pre>
    </body>
    </html>'''
        self.wfile.write(html.encode())
    
    def log_message(self, format, *args):
        pass

if __name__ == '__main__':
    server = HTTPServer(('0.0.0.0', 8080), HelloHandler)
    print('🐋 Whale server running on http://0.0.0.0:8080')
    server.serve_forever()
