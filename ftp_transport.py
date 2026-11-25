#!/usr/bin/env python3
"""
Transporte FTP unificado para o media-pipeline.

Suporta conexão direta (LAN doméstica ou túnel OpenVPN via tun0) e túnel
Tailscale via proxy SOCKS5 (ex.: socks5h://100.97.222.39:1080), tanto para o
canal de controle quanto para canais de dados PASV (--ftp-skip-pasv-ip), com
fallback automático entre Tailscale e OpenVPN/direto.
"""

from __future__ import annotations

import ftplib
import ipaddress
import os
import socket
import struct
import sys
import urllib.parse

DEFAULT_FTP_HOST = "192.168.0.1"
DEFAULT_FTP_PORT = 21
DEFAULT_TAILSCALE_SOCKS5 = "socks5h://100.97.222.39:1080"

VALID_FTP_MODES = ("auto", "lan", "direct", "vpn", "tailscale")


def _effective_timeout(timeout: object, fallback: float = 15.0) -> float:
    if isinstance(timeout, (int, float)) and not isinstance(timeout, bool) and timeout > 0:
        return float(timeout)
    global_default = socket.getdefaulttimeout()
    if isinstance(global_default, (int, float)) and global_default > 0:
        return float(global_default)
    return fallback


def parse_socks5_url(proxy_url: str) -> tuple[str, int] | None:
    """Extrai `(host, port)` de uma URL SOCKS5 (`socks5://` ou `socks5h://`)."""
    raw = (proxy_url or "").strip().rstrip("/")
    if not raw:
        return None

    if "://" not in raw:
        if ":" not in raw:
            return None
        raw = f"socks5h://{raw}"

    parsed = urllib.parse.urlparse(raw)
    if parsed.scheme.lower() not in ("socks5", "socks5h"):
        return None

    host = (parsed.hostname or "").strip()
    if not host:
        return None

    try:
        port = parsed.port if parsed.port is not None else 1080
    except ValueError:
        return None

    if not (1 <= port <= 65535):
        return None

    return host, port


def _recv_exact(sock: socket.socket, size: int) -> bytes:
    chunks: list[bytes] = []
    remaining = size
    while remaining > 0:
        chunk = sock.recv(remaining)
        if not chunk:
            raise OSError("Conexão SOCKS5 encerrada prematuramente")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def open_socks5_socket(
    proxy_host: str,
    proxy_port: int,
    target_host: str,
    target_port: int,
    timeout: float = 15.0,
) -> socket.socket:
    """Abre um socket TCP atravessando um proxy SOCKS5 sem autenticação (RFC 1928)."""
    conn_timeout = _effective_timeout(timeout, fallback=15.0)
    sock = socket.create_connection((proxy_host, proxy_port), timeout=conn_timeout)
    try:
        sock.settimeout(conn_timeout)
        sock.sendall(b"\x05\x01\x00")
        greeting = _recv_exact(sock, 2)
        if greeting[0] != 5 or greeting[1] != 0:
            raise OSError(
                f"Proxy SOCKS5 {proxy_host}:{proxy_port} recusou método sem autenticação "
                f"(resposta={greeting!r})"
            )

        try:
            ip_obj = ipaddress.ip_address(target_host)
        except ValueError:
            host_bytes = target_host.encode("utf-8")
            if not host_bytes or len(host_bytes) > 255:
                raise ValueError(f"Host alvo inválido para SOCKS5: {target_host!r}")
            atyp = 3
            addr_bytes = bytes([len(host_bytes)]) + host_bytes
        else:
            if ip_obj.version == 4:
                atyp = 1
                addr_bytes = ip_obj.packed
            else:
                atyp = 4
                addr_bytes = ip_obj.packed

        request = b"\x05\x01\x00" + bytes([atyp]) + addr_bytes + struct.pack("!H", target_port)
        sock.sendall(request)

        ver, rep, _rsv, reply_atyp = _recv_exact(sock, 4)
        if ver != 5:
            raise OSError(f"Versão SOCKS5 inesperada na resposta: {ver}")

        if reply_atyp == 1:
            _recv_exact(sock, 4)
        elif reply_atyp == 3:
            addr_len = _recv_exact(sock, 1)[0]
            if addr_len:
                _recv_exact(sock, addr_len)
        elif reply_atyp == 4:
            _recv_exact(sock, 16)
        else:
            raise OSError(f"ATYP SOCKS5 desconhecido na resposta: {reply_atyp}")
        _recv_exact(sock, 2)

        if rep != 0:
            raise OSError(
                f"Falha no túnel SOCKS5 {proxy_host}:{proxy_port} -> "
                f"{target_host}:{target_port} (REP={rep})"
            )

        return sock
    except Exception:
        try:
            sock.close()
        except Exception:
            pass
        raise


class Socks5FTP(ftplib.FTP):
    """Cliente `ftplib.FTP` que roteia controle e dados PASV via proxy SOCKS5."""

    def __init__(
        self,
        proxy_host: str,
        proxy_port: int,
        skip_pasv_ip: bool = True,
        **kwargs,
    ) -> None:
        self.proxy_host = proxy_host
        self.proxy_port = int(proxy_port)
        self.skip_pasv_ip = skip_pasv_ip
        super().__init__(**kwargs)

    def connect(
        self,
        host: str = "",
        port: int = 0,
        timeout: float = -999,
        source_address=None,
    ) -> str:
        """Abre a conexão de controle FTP através do proxy SOCKS5."""
        if host:
            self.host = host
        if port > 0:
            self.port = port
        if timeout != -999:
            self.timeout = timeout
        if source_address:
            self.source_address = source_address

        conn_timeout = _effective_timeout(self.timeout, fallback=15.0)
        self.sock = open_socks5_socket(
            self.proxy_host,
            self.proxy_port,
            self.host,
            self.port,
            timeout=conn_timeout,
        )
        self.af = self.sock.family
        self.file = self.sock.makefile("r", encoding=self.encoding)
        self.welcome = self.getresp()
        return self.welcome

    def ntransfercmd(self, cmd: str, rest: int | None = None):
        """Abre o canal de dados PASV pelo proxy SOCKS5 preservando `--ftp-skip-pasv-ip`."""
        if not self.passiveserver:
            return super().ntransfercmd(cmd, rest)

        pasv_host, pasv_port = self.makepasv()
        data_host = self.host if (self.skip_pasv_ip and self.host) else pasv_host
        conn_timeout = _effective_timeout(self.timeout, fallback=15.0)
        conn = open_socks5_socket(
            self.proxy_host,
            self.proxy_port,
            data_host,
            pasv_port,
            timeout=conn_timeout,
        )
        size = None
        try:
            if rest is not None:
                self.sendcmd(f"REST {rest}")
            resp = self.sendcmd(cmd)
            if resp[0] == "2":
                resp = self.getresp()
            if resp[0] != "1":
                raise ftplib.error_reply(resp)
            if resp[:3] == "150":
                size = ftplib.parse150(resp)
        except Exception:
            conn.close()
            raise
        return conn, size


def get_configured_proxy(proxy_url: str = "") -> str:
    """Retorna a URL SOCKS5 explícita ou configurada via variáveis de ambiente."""
    for candidate in (
        proxy_url,
        os.environ.get("TAILSCALE_FTP_PROXY", ""),
        os.environ.get("FTP_PROXY", ""),
        os.environ.get("ftp_proxy", ""),
    ):
        value = (candidate or "").strip()
        if value:
            return value
    return ""


def _normalize_mode(mode: str | None) -> str:
    raw = (mode or os.environ.get("FTP_NETWORK_MODE", "") or "auto").strip().lower()
    if raw not in VALID_FTP_MODES:
        raise ValueError(
            f"Modo FTP inválido: {raw!r}. Use um de: {', '.join(VALID_FTP_MODES)}"
        )
    if raw in ("direct", "vpn"):
        return "lan"
    return raw


def _tcp_reachable(host: str, port: int, timeout: float = 2.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def resolve_curl_proxy(
    mode: str = "auto",
    proxy_url: str = "",
    host: str = DEFAULT_FTP_HOST,
    port: int = DEFAULT_FTP_PORT,
    lan_probe_timeout: float = 2.0,
    probe: bool = True,
) -> str | None:
    """Resolve a URL SOCKS5 para `curl --proxy` respeitando modo e fallback automático."""
    eff_mode = _normalize_mode(mode)
    if eff_mode == "lan":
        return None

    configured = get_configured_proxy(proxy_url)
    if eff_mode == "tailscale":
        return configured or DEFAULT_TAILSCALE_SOCKS5

    # eff_mode == "auto"
    if configured:
        parsed = parse_socks5_url(configured)
        if not probe or not parsed:
            return configured
        if _tcp_reachable(parsed[0], parsed[1], timeout=lan_probe_timeout):
            return configured
        return None

    if not probe:
        return None

    if _tcp_reachable(host, port, timeout=lan_probe_timeout):
        return None

    default_parsed = parse_socks5_url(DEFAULT_TAILSCALE_SOCKS5)
    if default_parsed and _tcp_reachable(
        default_parsed[0], default_parsed[1], timeout=lan_probe_timeout
    ):
        return DEFAULT_TAILSCALE_SOCKS5

    return None


def _login_binary(ftp: ftplib.FTP, user: str, password: str) -> None:
    if user:
        ftp.login(user, password)
    else:
        ftp.login()
    # Servidores FTP como o do roteador TP-Link recusam SIZE em modo ASCII padrão.
    ftp.voidcmd("TYPE I")


def _connect_direct(
    host: str,
    port: int,
    user: str,
    password: str,
    connect_timeout: float,
    session_timeout: float,
) -> tuple[ftplib.FTP, str]:
    ftp = ftplib.FTP()
    try:
        ftp.connect(host, port, timeout=connect_timeout)
        _login_binary(ftp, user, password)
        ftp.timeout = session_timeout
        return ftp, "direct"
    except Exception:
        try:
            ftp.close()
        except Exception:
            pass
        raise


def _connect_tailscale(
    host: str,
    port: int,
    user: str,
    password: str,
    proxy_url: str,
    timeout: float,
) -> tuple[ftplib.FTP, str]:
    parsed = parse_socks5_url(proxy_url)
    if not parsed:
        raise ValueError(f"URL de proxy SOCKS5 inválida: {proxy_url!r}")
    p_host, p_port = parsed
    ftp = Socks5FTP(p_host, p_port, skip_pasv_ip=True)
    try:
        ftp.connect(host, port, timeout=timeout)
        _login_binary(ftp, user, password)
        return ftp, f"tailscale({p_host}:{p_port})"
    except Exception:
        try:
            ftp.close()
        except Exception:
            pass
        raise


def connect_ftp(
    host: str | None = None,
    port: int | None = None,
    user: str | None = None,
    password: str | None = None,
    mode: str | None = None,
    proxy_url: str = "",
    timeout: float = 15.0,
    lan_probe_timeout: float = 3.0,
    allow_fallback: bool = True,
) -> tuple[ftplib.FTP, str]:
    """
    Conecta e autentica ao servidor FTP retornando `(ftp, route_label)`.

    Regras de roteamento:
    - `mode="lan"` (ou `"vpn"`/`"direct"`): conecta diretamente (LAN ou OpenVPN `tun0`).
    - `mode="tailscale"`: tenta SOCKS5 (`proxy_url`, `FTP_PROXY`, ou padrão
      `socks5h://100.97.222.39:1080`) e, se `allow_fallback=True`, cai para conexão
      direta/OpenVPN automaticamente em caso de falha.
    - `mode="auto"` (padrão): se houver proxy configurado via `proxy_url`/`FTP_PROXY`,
      tenta Tailscale primeiro com fallback para direto/OpenVPN; caso contrário tenta
      LAN/OpenVPN direto primeiro (`lan_probe_timeout`) com fallback automático para
      Tailscale SOCKS5.
    """
    ftp_host = (host or os.environ.get("FTP_HOST", "") or DEFAULT_FTP_HOST).strip()
    if port is not None:
        ftp_port = int(port)
    else:
        ftp_port = int(os.environ.get("FTP_PORT", "") or DEFAULT_FTP_PORT)
    ftp_user = os.environ.get("FTP_USER", "") if user is None else user
    ftp_password = os.environ.get("FTP_PASSWORD", "") if password is None else password

    eff_mode = _normalize_mode(mode)
    configured_proxy = get_configured_proxy(proxy_url)

    if eff_mode == "lan":
        return _connect_direct(ftp_host, ftp_port, ftp_user, ftp_password, timeout, timeout)

    if eff_mode == "tailscale":
        target_proxy = configured_proxy or DEFAULT_TAILSCALE_SOCKS5
        try:
            return _connect_tailscale(
                ftp_host, ftp_port, ftp_user, ftp_password, target_proxy, timeout
            )
        except Exception as ts_exc:
            if not allow_fallback:
                raise
            print(
                f"[FTP] Aviso: Tailscale SOCKS5 ({target_proxy}) falhou ({ts_exc}); "
                "usando fallback direto/OpenVPN...",
                file=sys.stderr,
            )
            try:
                return _connect_direct(
                    ftp_host, ftp_port, ftp_user, ftp_password, timeout, timeout
                )
            except Exception as direct_exc:
                raise OSError(
                    f"Falha no FTP via Tailscale ({ts_exc}) e no fallback direto/OpenVPN ({direct_exc})"
                ) from direct_exc

    # eff_mode == "auto"
    if configured_proxy:
        try:
            return _connect_tailscale(
                ftp_host, ftp_port, ftp_user, ftp_password, configured_proxy, timeout
            )
        except Exception as ts_exc:
            if not allow_fallback:
                raise
            print(
                f"[FTP] Aviso: Tailscale SOCKS5 ({configured_proxy}) falhou ({ts_exc}); "
                "usando fallback direto/OpenVPN...",
                file=sys.stderr,
            )
            try:
                return _connect_direct(
                    ftp_host, ftp_port, ftp_user, ftp_password, timeout, timeout
                )
            except Exception as direct_exc:
                raise OSError(
                    f"Falha no FTP via Tailscale ({ts_exc}) e no fallback direto/OpenVPN ({direct_exc})"
                ) from direct_exc

    probe_timeout = min(float(timeout), float(lan_probe_timeout))
    try:
        return _connect_direct(
            ftp_host, ftp_port, ftp_user, ftp_password, probe_timeout, timeout
        )
    except Exception as direct_exc:
        if not allow_fallback:
            raise
        print(
            f"[FTP] Aviso: conexão direta ({ftp_host}:{ftp_port}) indisponível ({direct_exc}); "
            f"tentando fallback Tailscale SOCKS5 ({DEFAULT_TAILSCALE_SOCKS5})...",
            file=sys.stderr,
        )
        try:
            return _connect_tailscale(
                ftp_host,
                ftp_port,
                ftp_user,
                ftp_password,
                DEFAULT_TAILSCALE_SOCKS5,
                timeout,
            )
        except Exception as ts_exc:
            raise OSError(
                f"Falha na conexão direta ({direct_exc}) e no fallback Tailscale ({ts_exc})"
            ) from ts_exc
