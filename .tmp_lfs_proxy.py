import select
import socket
import socketserver


TARGET_IP = "20.207.73.82"
ALLOWED_HOSTS = {"github.com", "lfs.github.com", "github-cloud.s3.amazonaws.com"}


class ConnectProxy(socketserver.BaseRequestHandler):
    def handle(self):
        request = self.request.recv(8192)
        first_line = request.split(b"\r\n", 1)[0]
        try:
            target = first_line.split()[1].decode("ascii")
            host, port = target.rsplit(":", 1)
        except (IndexError, ValueError, UnicodeDecodeError):
            host, port = "", ""
        if host not in ALLOWED_HOSTS or port != "443":
            self.request.sendall(b"HTTP/1.1 403 Forbidden\r\n\r\n")
            return

        upstream_host = TARGET_IP if host in {"github.com", "lfs.github.com"} else host
        upstream = socket.create_connection((upstream_host, 443), timeout=20)
        try:
            self.request.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            sockets = [self.request, upstream]
            while True:
                readable, _, _ = select.select(sockets, [], [], 60)
                if not readable:
                    continue
                for source in readable:
                    data = source.recv(65536)
                    if not data:
                        return
                    destination = upstream if source is self.request else self.request
                    destination.sendall(data)
        finally:
            upstream.close()


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


Server(("127.0.0.1", 18080), ConnectProxy).serve_forever()
