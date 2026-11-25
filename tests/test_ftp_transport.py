import argparse
import os
import socket
import struct
import threading
import unittest
from pathlib import Path
from unittest import mock

import baixar_torrent_ftp
import ftp_transport
import verificar_episodio_ftp
from workflows import uzak_cli


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class _MockSocks5Server:
    """Servidor SOCKS5 (RFC 1928 sem auth) em loopback para testes."""

    def __init__(self, target_override_port: int | None = None) -> None:
        self.target_override_port = target_override_port
        self.requested_targets: list[tuple[str, int]] = []
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(16)
        self.port = self._sock.getsockname()[1]
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)

    def start(self) -> int:
        self._thread.start()
        return self.port

    def stop(self) -> None:
        self._stop.set()
        try:
            self._sock.close()
        except OSError:
            pass

    def _serve(self) -> None:
        while not self._stop.is_set():
            try:
                client, _ = self._sock.accept()
            except OSError:
                break
            threading.Thread(target=self._handle, args=(client,), daemon=True).start()

    @staticmethod
    def _pipe(src: socket.socket, dst: socket.socket) -> None:
        try:
            while True:
                data = src.recv(4096)
                if not data:
                    break
                dst.sendall(data)
        except OSError:
            pass
        finally:
            try:
                dst.shutdown(socket.SHUT_WR)
            except OSError:
                pass

    def _handle(self, client: socket.socket) -> None:
        upstream = None
        try:
            greeting = client.recv(260)
            if len(greeting) < 2 or greeting[0] != 5:
                return
            client.sendall(b"\x05\x00")

            hdr = client.recv(4)
            if len(hdr) < 4 or hdr[0] != 5 or hdr[1] != 1:
                client.sendall(b"\x05\x07\x00\x01\x00\x00\x00\x00\x00\x00")
                return
            atyp = hdr[3]
            if atyp == 1:
                addr = socket.inet_ntoa(client.recv(4))
            elif atyp == 3:
                ln = client.recv(1)[0]
                addr = client.recv(ln).decode("utf-8")
            else:
                client.sendall(b"\x05\x08\x00\x01\x00\x00\x00\x00\x00\x00")
                return
            req_port = struct.unpack("!H", client.recv(2))[0]
            self.requested_targets.append((addr, req_port))

            dst_port = self.target_override_port or req_port
            upstream = socket.create_connection(("127.0.0.1", dst_port), timeout=5.0)
            client.sendall(b"\x05\x00\x00\x01\x7f\x00\x00\x01\x00\x00")

            t1 = threading.Thread(target=self._pipe, args=(client, upstream), daemon=True)
            t2 = threading.Thread(target=self._pipe, args=(upstream, client), daemon=True)
            t1.start()
            t2.start()
            t1.join(timeout=5)
            t2.join(timeout=5)
        except OSError:
            pass
        finally:
            for s in (upstream, client):
                if s:
                    try:
                        s.close()
                    except OSError:
                        pass


class _MockPasvFtpServer:
    """Servidor FTP mínimo com PASV retornando IP falso para validar skip-pasv-ip."""

    def __init__(self, files: dict[str, bytes] | None = None, advertised_pasv_ip: str = "10.255.255.1") -> None:
        self.files = dict(files or {})
        self.advertised_pasv_ip = advertised_pasv_ip
        self.current_dir = "/"
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(8)
        self.port = self._sock.getsockname()[1]
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)

    def start(self) -> int:
        self._thread.start()
        return self.port

    def stop(self) -> None:
        self._stop.set()
        try:
            self._sock.close()
        except OSError:
            pass

    def _serve(self) -> None:
        while not self._stop.is_set():
            try:
                conn, _ = self._sock.accept()
            except OSError:
                break
            threading.Thread(target=self._handle_client, args=(conn,), daemon=True).start()

    def _handle_client(self, conn: socket.socket) -> None:
        data_listener = None
        try:
            f = conn.makefile("r", encoding="utf-8", errors="replace")
            conn.sendall(b"220 Mock FTP ready\r\n")
            while True:
                line = f.readline()
                if not line:
                    break
                cmd_line = line.strip()
                upper = cmd_line.upper()
                if upper.startswith("USER "):
                    conn.sendall(b"331 OK\r\n")
                elif upper.startswith("PASS "):
                    conn.sendall(b"230 Logged in\r\n")
                elif upper.startswith("TYPE "):
                    conn.sendall(b"200 Type set\r\n")
                elif upper == "PWD":
                    conn.sendall(f'257 "{self.current_dir}"\r\n'.encode())
                elif upper.startswith("CWD "):
                    self.current_dir = cmd_line[4:].strip()
                    conn.sendall(b"250 CWD command successful\r\n")
                elif upper.startswith("SIZE "):
                    name = cmd_line[5:].strip()
                    if name in self.files:
                        conn.sendall(f"213 {len(self.files[name])}\r\n".encode())
                    else:
                        conn.sendall(b"550 File not found\r\n")
                elif upper == "PASV":
                    if data_listener:
                        data_listener.close()
                    data_listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    data_listener.bind(("127.0.0.1", 0))
                    data_listener.listen(1)
                    p = data_listener.getsockname()[1]
                    ip_parts = self.advertised_pasv_ip.split(".")
                    conn.sendall(
                        f"227 Entering Passive Mode ({','.join(ip_parts)},{p >> 8},{p & 255}).\r\n".encode()
                    )
                elif upper.startswith("NLST"):
                    assert data_listener is not None
                    data_conn, _ = data_listener.accept()
                    payload = ("\r\n".join(sorted(self.files.keys())) + "\r\n").encode()
                    conn.sendall(b"150 Opening data connection\r\n")
                    data_conn.sendall(payload)
                    data_conn.close()
                    data_listener.close()
                    data_listener = None
                    conn.sendall(b"226 Transfer complete\r\n")
                elif upper.startswith("RETR "):
                    name = cmd_line[5:].strip()
                    assert data_listener is not None
                    data_conn, _ = data_listener.accept()
                    if name in self.files:
                        conn.sendall(f"150 Opening BINARY mode ({len(self.files[name])} bytes)\r\n".encode())
                        data_conn.sendall(self.files[name])
                        data_conn.close()
                        conn.sendall(b"226 Transfer complete\r\n")
                    else:
                        data_conn.close()
                        conn.sendall(b"550 Not found\r\n")
                    data_listener.close()
                    data_listener = None
                elif upper.startswith("STOR "):
                    name = cmd_line[5:].strip()
                    assert data_listener is not None
                    data_conn, _ = data_listener.accept()
                    conn.sendall(b"150 Ready for STOR\r\n")
                    chunks = []
                    while True:
                        buf = data_conn.recv(4096)
                        if not buf:
                            break
                        chunks.append(buf)
                    self.files[name] = b"".join(chunks)
                    data_conn.close()
                    data_listener.close()
                    data_listener = None
                    conn.sendall(b"226 Transfer complete\r\n")
                elif upper == "QUIT":
                    conn.sendall(b"221 Bye\r\n")
                    break
                else:
                    conn.sendall(b"502 Command not implemented\r\n")
        except OSError:
            pass
        finally:
            if data_listener:
                try:
                    data_listener.close()
                except OSError:
                    pass
            try:
                conn.close()
            except OSError:
                pass


class FtpTransportTests(unittest.TestCase):
    def test_parse_socks5_url(self) -> None:
        self.assertEqual(ftp_transport.parse_socks5_url("socks5h://100.97.222.39:1080"), ("100.97.222.39", 1080))
        self.assertEqual(ftp_transport.parse_socks5_url("socks5://127.0.0.1:1081/"), ("127.0.0.1", 1081))
        self.assertEqual(ftp_transport.parse_socks5_url("100.97.222.39:1080"), ("100.97.222.39", 1080))
        self.assertEqual(ftp_transport.parse_socks5_url("socks5h://[fd7a:115c::1]:1080"), ("fd7a:115c::1", 1080))
        self.assertIsNone(ftp_transport.parse_socks5_url(""))
        self.assertIsNone(ftp_transport.parse_socks5_url("http://127.0.0.1:8080"))
        self.assertIsNone(ftp_transport.parse_socks5_url("socks5h://127.0.0.1:99999"))
        self.assertIsNone(ftp_transport.parse_socks5_url("invalido"))

    def test_socks5_ftp_control_and_pasv_skip_ip(self) -> None:
        ftp_srv = _MockPasvFtpServer(files={"demo.srt": b"1\n00:00:01,000 --> 00:00:02,000\nOi\n"})
        ftp_port = ftp_srv.start()
        socks_srv = _MockSocks5Server()
        socks_port = socks_srv.start()
        try:
            with mock.patch.dict(os.environ, {"FTP_PROXY": f"socks5h://127.0.0.1:{socks_port}"}, clear=False):
                ftp, route = ftp_transport.connect_ftp(
                    host="127.0.0.1",
                    port=ftp_port,
                    user="u",
                    password="p",
                    mode="auto",
                    timeout=5.0,
                )
                try:
                    self.assertEqual(route, f"tailscale(127.0.0.1:{socks_port})")
                    entries = ftp.nlst()
                    self.assertEqual(entries, ["demo.srt"])
                    out = bytearray()
                    ftp.retrbinary("RETR demo.srt", out.extend)
                    self.assertIn(b"Oi", bytes(out))
                finally:
                    ftp.quit()
            # Controle + NLST PASV + RETR PASV passaram pelo SOCKS5 com skip_pasv_ip=True (IP 127.0.0.1, não 10.255.255.1)
            self.assertGreaterEqual(len(socks_srv.requested_targets), 3)
            self.assertTrue(all(host == "127.0.0.1" for host, _ in socks_srv.requested_targets))
        finally:
            socks_srv.stop()
            ftp_srv.stop()

    def test_connect_ftp_tailscale_fallback_to_direct(self) -> None:
        ftp_srv = _MockPasvFtpServer(files={"ep.mp4": b"x" * 16})
        ftp_port = ftp_srv.start()
        dead_socks_port = _free_port()
        try:
            ftp, route = ftp_transport.connect_ftp(
                host="127.0.0.1",
                port=ftp_port,
                user="u",
                password="p",
                mode="tailscale",
                proxy_url=f"socks5h://127.0.0.1:{dead_socks_port}",
                timeout=3.0,
                allow_fallback=True,
            )
            try:
                self.assertEqual(route, "direct")
                self.assertEqual(ftp.size("ep.mp4"), 16)
            finally:
                ftp.quit()

            with self.assertRaises(OSError):
                ftp_transport.connect_ftp(
                    host="127.0.0.1",
                    port=ftp_port,
                    user="u",
                    password="p",
                    mode="tailscale",
                    proxy_url=f"socks5h://127.0.0.1:{dead_socks_port}",
                    timeout=2.0,
                    allow_fallback=False,
                )
        finally:
            ftp_srv.stop()

    def test_connect_ftp_auto_local_fallback_to_tailscale(self) -> None:
        ftp_srv = _MockPasvFtpServer(files={"ok.txt": b"123"})
        ftp_port = ftp_srv.start()
        socks_srv = _MockSocks5Server(target_override_port=ftp_port)
        socks_port = socks_srv.start()
        dead_lan_port = _free_port()
        try:
            with (
                mock.patch.dict(os.environ, {"FTP_PROXY": "", "ftp_proxy": "", "TAILSCALE_FTP_PROXY": ""}, clear=False),
                mock.patch.object(ftp_transport, "DEFAULT_TAILSCALE_SOCKS5", f"socks5h://127.0.0.1:{socks_port}"),
            ):
                ftp, route = ftp_transport.connect_ftp(
                    host="127.0.0.1",
                    port=dead_lan_port,
                    user="u",
                    password="p",
                    mode="auto",
                    timeout=3.0,
                    lan_probe_timeout=0.5,
                    allow_fallback=True,
                )
                try:
                    self.assertEqual(route, f"tailscale(127.0.0.1:{socks_port})")
                    self.assertEqual(ftp.size("ok.txt"), 3)
                finally:
                    ftp.quit()
        finally:
            socks_srv.stop()
            ftp_srv.stop()

    def test_resolve_curl_proxy(self) -> None:
        dead_port = _free_port()
        with mock.patch.dict(os.environ, {"FTP_PROXY": f"socks5h://127.0.0.1:{dead_port}"}, clear=False):
            self.assertIsNone(ftp_transport.resolve_curl_proxy(mode="lan"))
            self.assertIsNone(ftp_transport.resolve_curl_proxy(mode="vpn"))
            self.assertEqual(
                ftp_transport.resolve_curl_proxy(mode="tailscale"),
                f"socks5h://127.0.0.1:{dead_port}",
            )
            # Proxy inacessível em modo auto cai para direto/OpenVPN (None)
            self.assertIsNone(
                ftp_transport.resolve_curl_proxy(mode="auto", lan_probe_timeout=0.2)
            )

    def test_verificar_episodio_ftp_via_connect_ftp_fallback(self) -> None:
        ftp_srv = _MockPasvFtpServer(files={"Ep01.mp4": b"0" * (2 * 1024 * 1024)})
        ftp_port = ftp_srv.start()
        dead_port = _free_port()
        try:
            env = {
                "FTP_HOST": "127.0.0.1",
                "FTP_PORT": str(ftp_port),
                "FTP_USER": "tester",
                "FTP_PASSWORD": "secret",
            }
            with mock.patch.dict(os.environ, env, clear=False):
                self.assertTrue(
                    verificar_episodio_ftp.verificar_arquivo_ftp(
                        "/G/Series",
                        "Ep01.mp4",
                        min_size_mb=1,
                        ftp_mode="tailscale",
                        tailscale_proxy=f"socks5h://127.0.0.1:{dead_port}",
                    )
                )
                self.assertFalse(
                    verificar_episodio_ftp.verificar_arquivo_ftp(
                        "/G/Series",
                        "Ep01.mp4",
                        min_size_mb=5,
                        ftp_mode="tailscale",
                        tailscale_proxy=f"socks5h://127.0.0.1:{dead_port}",
                    )
                )
        finally:
            ftp_srv.stop()

    def test_baixar_torrent_ftp_proxy_and_fallback(self) -> None:
        cmds: list[list[str]] = []

        def fake_run(cmd, check=False):
            cmds.append(list(cmd))
            return mock.Mock(returncode=0)

        with mock.patch.object(baixar_torrent_ftp.subprocess, "run", side_effect=fake_run):
            baixar_torrent_ftp.enviar_arquivo_ftp_curl(
                Path(__file__),
                "192.168.0.1",
                21,
                "u",
                "p",
                "/G/Filmes",
                "filme.mkv",
                proxy_url="socks5h://100.97.222.39:1080",
            )
        self.assertEqual(len(cmds), 1)
        self.assertIn("--ftp-skip-pasv-ip", cmds[0])
        self.assertIn("--proxy", cmds[0])
        self.assertIn("socks5h://100.97.222.39:1080", cmds[0])

    def test_uzak_cli_parses_ftp_flags(self) -> None:
        with mock.patch("sys.argv", ["uzak_cli.py", "prepare", "47", "--ftp-mode", "tailscale", "--tailscale-proxy", "socks5h://127.0.0.1:1080"]):
            p = argparse.ArgumentParser()
            sub = p.add_subparsers(dest="cmd", required=True)
            p1 = sub.add_parser("prepare")
            p1.add_argument("episode", type=int)
            uzak_cli._add_ftp_args(p1)
            parsed = p.parse_args(["prepare", "47", "--ftp-mode", "tailscale", "--tailscale-proxy", "socks5h://127.0.0.1:1080"])
            self.assertEqual(parsed.ftp_mode, "tailscale")
            self.assertEqual(parsed.tailscale_proxy, "socks5h://127.0.0.1:1080")


if __name__ == "__main__":
    unittest.main()
