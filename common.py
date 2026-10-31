import json

class Conn:
    """Newline-delimited JSON messages over a TCP socket (application-level protocol)."""
    def __init__(self, sock):
        self.sock = sock
        self.buf = b""

    def send(self, obj):
        self.sock.sendall((json.dumps(obj) + "\n").encode())

    def recv(self):
        while b"\n" not in self.buf:
            d = self.sock.recv(4096)
            if not d:
                raise ConnectionError("peer closed")
            self.buf += d
        line, self.buf = self.buf.split(b"\n", 1)
        return json.loads(line)
