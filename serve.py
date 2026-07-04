"""Static-only file server for the viewer (no processing backend).

This is a lightweight fallback that serves the raw ``viewer/`` files over
``http.server`` on port 8080 — handy for eyeballing the front-end without
starting the full app. It does NOT provide any of the ``/render`` or ``/scan``
endpoints, so uploads and processing will not work here.

For real use run ``python app.py`` (Flask, port 5001), which serves the same
viewer *and* the backend endpoints. This module is kept only as a convenience
and can be removed once nobody relies on it.
"""

import http.server
import os
import socketserver
import webbrowser

PORT = 8080
os.chdir(os.path.dirname(os.path.abspath(__file__)))

url = f"http://localhost:{PORT}/viewer/index.html"
print(f"Viewer: {url}")
print("Stop with Ctrl+C")
webbrowser.open(url)

with socketserver.TCPServer(("", PORT), http.server.SimpleHTTPRequestHandler) as httpd:
    httpd.serve_forever()
