import http.server
import socketserver
import os
import webbrowser

PORT = 8080
os.chdir(os.path.dirname(os.path.abspath(__file__)))

url = f"http://localhost:{PORT}/viewer/index.html"
print(f"Viewer: {url}")
print("Stop with Ctrl+C")
webbrowser.open(url)

with socketserver.TCPServer(("", PORT), http.server.SimpleHTTPRequestHandler) as httpd:
    httpd.serve_forever()
