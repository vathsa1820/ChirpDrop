"""
ChirpDrop - Web Receiver Local Development Server
-------------------------------------------------
Serves the web-receiver directory using Python's built-in http.server.
Supports both standard HTTP and local HTTPS (when SSL certs are present).

Usage:
    python serve.py                 # Serves on http://0.0.0.0:8000
    python serve.py --port 8443     # Custom port
    python serve.py --ssl           # Enables SSL if cert.pem/key.pem exist
"""

import argparse
from http.server import HTTPServer, SimpleHTTPRequestHandler
import os
from pathlib import Path
import socket
import ssl
import sys

def get_lan_ip() -> str:
    """Detect the local machine's primary LAN IP address."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # Connecting to a public UDP address doesn't send packets, but routes to active interface
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    except Exception:
        ip = "127.0.0.1"
    finally:
        s.close()
    return ip

class ChirpDropRequestHandler(SimpleHTTPRequestHandler):
    """Custom request handler with clean MIME types and caching headers."""

    def end_headers(self):
        # Enable Service Worker and WebAssembly headers
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-cache, must-revalidate")
        super().end_headers()

    def guess_type(self, path):
        # Ensure correct MIME type for WebAssembly and PWA manifest
        if str(path).endswith(".wasm"):
            return "application/wasm"
        if str(path).endswith(".json") or str(path).endswith(".webmanifest"):
            return "application/manifest+json"
        if str(path).endswith(".js"):
            return "application/javascript"
        return super().guess_type(path)

def run_server(port: int = 8000, use_ssl: bool = False) -> None:
    web_dir = Path(__file__).resolve().parent
    os.chdir(web_dir)

    server_address = ("0.0.0.0", port)
    httpd = HTTPServer(server_address, ChirpDropRequestHandler)

    protocol = "http"
    lan_ip = get_lan_ip()

    if use_ssl:
        cert_file = web_dir / "cert.pem"
        key_file = web_dir / "key.pem"
        if cert_file.exists() and key_file.exists():
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(certfile=str(cert_file), keyfile=str(key_file))
            httpd.socket = context.wrap_socket(httpd.socket, server_side=True)
            protocol = "https"
            print("[INFO] SSL enabled using cert.pem and key.pem")
        else:
            print("[WARNING] --ssl requested but cert.pem/key.pem not found. Falling back to HTTP.")
            print("[TIP] For iOS Safari HTTPS testing without local certs, deploy to GitHub Pages.")

    print("\n" + "=" * 65)
    print("  ChirpDrop Web Receiver Server")
    print("=" * 65)
    print(f"  • Local:   {protocol}://localhost:{port}/")
    print(f"  • iPhone:  {protocol}://{lan_ip}:{port}/")
    print("=" * 65)
    print("  Press Ctrl+C to stop the server.\n")

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[INFO] Server stopped.")
        httpd.server_close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ChirpDrop Web Receiver Static Server")
    parser.add_argument("--port", type=int, default=8000, help="Port to listen on (default: 8000)")
    parser.add_argument("--ssl", action="store_true", help="Enable SSL if cert.pem/key.pem are present")
    args = parser.parse_args()

    run_server(port=args.port, use_ssl=args.ssl)
