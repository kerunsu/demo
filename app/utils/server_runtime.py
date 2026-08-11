"""Flask-SocketIO 启动选项；重型分析器环境默认禁止 Werkzeug 热重载。"""
from __future__ import annotations

import os
import socket
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# app/utils/server_runtime.py → 项目根
_BASE_DIR = Path(__file__).resolve().parents[2]
_DEFAULT_CERT = _BASE_DIR / ".runtime" / "certs" / "cert.pem"
_DEFAULT_KEY = _BASE_DIR / ".runtime" / "certs" / "key.pem"


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def resolve_server_run_options() -> Dict[str, bool]:
    """
    debug 日志和源码热重载分离。

    FunASR/torch/torchaudio 会在首次分析时延迟导入大量 site-packages；Windows
    Werkzeug reloader 可能把这些导入误判为源码变化并重启服务。因此 reloader
    默认关闭，确有需要时才显式设置 FLASK_USE_RELOADER=1。
    """
    debug = _env_flag("FLASK_DEBUG", False)
    use_reloader = debug and _env_flag("FLASK_USE_RELOADER", False)
    return {"debug": debug, "use_reloader": use_reloader}


def resolve_ssl_context() -> Tuple[Optional[Tuple[str, str]], Dict[str, Any]]:
    """
    解析 HTTPS 证书路径，供 socketio.run(..., ssl_context=...).

    启用方式（任一即可）：
      - ENABLE_HTTPS=true（使用默认 .runtime/certs/cert.pem + key.pem）
      - SSL_CERTFILE + SSL_KEYFILE（显式路径；可与 ENABLE_HTTPS 并用）

    返回 (ssl_context_or_None, meta)。meta 含 enabled / certfile / keyfile / scheme。
    """
    cert_env = (os.environ.get("SSL_CERTFILE") or "").strip()
    key_env = (os.environ.get("SSL_KEYFILE") or "").strip()
    enable = _env_flag("ENABLE_HTTPS", False) or bool(cert_env or key_env)

    meta: Dict[str, Any] = {
        "enabled": False,
        "scheme": "http",
        "certfile": None,
        "keyfile": None,
    }
    if not enable:
        return None, meta

    cert = Path(cert_env) if cert_env else _DEFAULT_CERT
    key = Path(key_env) if key_env else _DEFAULT_KEY
    if not cert.is_file() or not key.is_file():
        raise FileNotFoundError(
            "HTTPS 已启用，但证书文件不存在。\n"
            f"  cert: {cert}\n"
            f"  key:  {key}\n"
            "请先运行: .\\scripts\\generate_lan_cert.ps1\n"
            "或设置 SSL_CERTFILE / SSL_KEYFILE 指向有效 PEM。"
        )

    meta.update(
        {
            "enabled": True,
            "scheme": "https",
            "certfile": str(cert.resolve()),
            "keyfile": str(key.resolve()),
        }
    )
    return (meta["certfile"], meta["keyfile"]), meta


def list_lan_ipv4() -> List[str]:
    """
    本机可用于局域网访问的 IPv4（排除回环与常见虚拟/APIPA）。
    优先把 192.168/10/172.16-31 排在前面，便于课堂选对地址。
    """
    found: List[str] = []
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            ip = info[4][0]
            if ip and ip not in found:
                found.append(ip)
    except Exception:
        pass

    # UDP 探测：不发包，只借路由表拿「出网」网卡 IP（通常是 WLAN/以太网）
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        primary = s.getsockname()[0]
        s.close()
        if primary and primary not in found:
            found.insert(0, primary)
        elif primary in found:
            found.remove(primary)
            found.insert(0, primary)
    except Exception:
        pass

    def _score(ip: str) -> tuple:
        if ip.startswith("192.168."):
            return (0, ip)
        if ip.startswith("10."):
            return (1, ip)
        parts = ip.split(".")
        if len(parts) == 4 and parts[0] == "172":
            try:
                second = int(parts[1])
                if 16 <= second <= 31:
                    return (2, ip)
            except ValueError:
                pass
        if ip.startswith("169.254."):
            return (9, ip)
        return (5, ip)

    filtered = [
        ip for ip in found
        if not ip.startswith("127.") and ip != "0.0.0.0"
    ]
    return sorted(set(filtered), key=_score)


def log_lan_access_hints(
    logger=None,
    *,
    flask_port: int = 8080,
    vite_port: int = 5173,
    scheme: str = "http",
) -> None:
    """启动时打印局域网访问地址，避免 DHCP 换 IP 后仍用旧地址。"""
    scheme = (scheme or "http").lower()
    if scheme not in ("http", "https"):
        scheme = "http"
    ips = list_lan_ipv4()
    child_hint = f"{scheme}://<IP>:{flask_port}/child"
    lines = [
        "局域网访问（IP 可能因 DHCP 变化，请以本次启动打印为准）:",
        f"  后端 Flask / 儿童端:  {child_hint}   （绑定 0.0.0.0）",
        f"  教师端:               {scheme}://<IP>:{flask_port}/teacher/  （Server 同源）",
        f"  Server 监控台:        {scheme}://<IP>:{flask_port}/server",
    ]
    if scheme == "https":
        lines.append(
            "  HTTPS 自签名：浏览器会告警，需点「高级 → 继续前往」一次；"
            "麦克风 getUserMedia 需要安全上下文。"
        )
        lines.append(
            "  证书刷新: .\\scripts\\generate_lan_cert.ps1 "
            "（DHCP 换 IP 后请重生成并重启）"
        )
    if ips:
        lines.append("  本机当前候选 IP:")
        for ip in ips[:6]:
            lines.append(f"    - {ip}  →  :{flask_port}")
        best = ips[0]
        lines.append(
            f"  建议优先试: {scheme}://{best}:{flask_port}/child  与  {scheme}://{best}:{flask_port}/teacher/"
        )
        if scheme == "https":
            lines.append(f"  本机回环: {scheme}://127.0.0.1:{flask_port}/child")
    else:
        lines.append("  （未能自动探测 LAN IP，请在本机 ipconfig 查看 WLAN/以太网地址）")

    msg = "\n".join(lines)
    if logger is not None:
        logger.info(msg)
    else:
        print(msg)
