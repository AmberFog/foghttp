__all__ = ("start_tls_server",)

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ssl
import threading
from typing import Any
from urllib.parse import urlsplit

from foghttp.status_codes.client_error import NOT_FOUND
from foghttp.status_codes.success import OK

from .certificates import TLSCertificateBundle
from .constants import TLS_OK_BODY, TLS_PATH
from .models import TLSServer


SERVER_HOST = "127.0.0.1"


def start_tls_server(certificates: TLSCertificateBundle) -> TLSServer:
    server = ThreadingHTTPServer((SERVER_HOST, 0), TLSHTTPHandler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(
        certfile=certificates.certificate_path,
        keyfile=certificates.key_path,
    )
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return TLSServer(server=server, thread=thread)


class TLSHTTPHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:
        if urlsplit(self.path).path != TLS_PATH:
            self.send_response(NOT_FOUND)
            self.send_header("content-length", "0")
            self.send_header("connection", "close")
            self.end_headers()
            return

        self.send_response(OK)
        self.send_header("content-type", "text/plain")
        self.send_header("content-length", str(len(TLS_OK_BODY)))
        self.send_header("connection", "close")
        self.end_headers()
        self.wfile.write(TLS_OK_BODY)

    def log_message(self, _format: str, *_args: Any) -> None:
        return
