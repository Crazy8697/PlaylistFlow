"""Import first in a test: from then on, any connection to anything but this PC
(127.0.0.1 / ::1) fails at once with ConnectionRefusedError, so a test can never
reach Spotify, FreqBlog, GetSongBPM or GitHub by accident. Every real call a test
needs is mocked anyway; this is the safety net.

    import nonet  # noqa: F401
"""

import socket

_LOCAL = ("127.0.0.1", "::1", "localhost")
BLOCKED = []          # (host, port) of every connection that was refused


def _host(address):
    return address[0] if isinstance(address, tuple) else address


_real_connect = socket.socket.connect
_real_connect_ex = socket.socket.connect_ex
_real_create = socket.create_connection
_real_getaddrinfo = socket.getaddrinfo


def _check(address):
    host = _host(address)
    if host not in _LOCAL:
        BLOCKED.append(address)
        raise ConnectionRefusedError(f"tests/nonet.py: no network in tests ({host})")


def _connect(self, address):
    _check(address)
    return _real_connect(self, address)


def _connect_ex(self, address):
    _check(address)
    return _real_connect_ex(self, address)


def _create_connection(address, *a, **kw):
    _check(address)
    return _real_create(address, *a, **kw)


def _getaddrinfo(host, *a, **kw):
    if host not in _LOCAL and host is not None:
        BLOCKED.append((host, a[0] if a else None))
        raise socket.gaierror(f"tests/nonet.py: no network in tests ({host})")
    return _real_getaddrinfo(host, *a, **kw)


socket.socket.connect = _connect
socket.socket.connect_ex = _connect_ex
socket.create_connection = _create_connection
socket.getaddrinfo = _getaddrinfo


def _report():
    if BLOCKED:
        print(f"nonet: blocked {len(BLOCKED)} connection attempt(s): "
              + ", ".join(sorted({str(_host(a)) for a in BLOCKED})))


import atexit  # noqa: E402

atexit.register(_report)
