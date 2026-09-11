"""Port and process detection — uses psutil for listening ports."""

from __future__ import annotations

from pathlib import Path
import re

from devdash.models import PortInfo

# Well-known port labels for nicer display
_PORT_LABELS: dict[int, str] = {
    80: "HTTP", 443: "HTTPS", 3000: "Dev", 3001: "Dev",
    4200: "Angular", 5000: "Flask", 5173: "Vite", 5174: "Vite",
    5432: "PostgreSQL", 5433: "PostgreSQL", 6379: "Redis",
    8000: "API", 8080: "API", 8443: "API", 8888: "Jupyter",
    9000: "Service", 9090: "Prometheus", 9200: "Elasticsearch",
    27017: "MongoDB", 3306: "MySQL", 1433: "MSSQL",
}


def detect_ports(root: Path) -> list[PortInfo]:
    """Detect listening ports using psutil, with ss fallback."""
    ports = _detect_with_psutil()
    if not ports:
        ports = _detect_with_ss()

    # Sort: well-known/dev ports first, then by number
    ports.sort(key=lambda p: (p.port not in _PORT_LABELS, p.port))
    return ports


def _detect_with_psutil() -> list[PortInfo]:
    """Detect ports using psutil."""
    try:
        import psutil
    except ImportError:
        return []

    ports: list[PortInfo] = []
    seen: set[tuple[str, int, int]] = set()

    try:
        connections = psutil.net_connections(kind="inet")
    except (psutil.Error, OSError, NotImplementedError):
        return []

    for conn in connections:
        if conn.status != "LISTEN":
            continue
        if not conn.laddr:
            continue
        key = (conn.laddr.ip, conn.laddr.port, conn.pid or 0)
        if key in seen:
            continue

        port = conn.laddr.port
        seen.add(key)
        proc_name = ""
        pid = conn.pid or 0
        if pid:
            try:
                proc = psutil.Process(pid)
                proc_name = proc.name()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                proc_name = "unknown"

        ports.append(PortInfo(
            port=port,
            pid=pid,
            process=proc_name,
            protocol="TCP",
            address=conn.laddr.ip,
        ))

    return ports


def _detect_with_ss() -> list[PortInfo]:
    """Fallback: detect ports using ss command."""
    from devdash.runner import run_sync

    out, _, rc = run_sync(["ss", "-tlnp"], timeout=5.0)
    if rc != 0:
        return []

    ports: list[PortInfo] = []
    seen: set[tuple[str, int]] = set()

    for line in out.splitlines()[1:]:  # Skip header
        parts = line.split()
        if len(parts) < 5:
            continue
        try:
            addr = parts[3]
            port = int(addr.rsplit(":", 1)[-1])
            address = addr.rsplit(":", 1)[0].strip("[]")
            key = (address, port)
            if key in seen:
                continue
            seen.add(key)

            # Try to extract process info
            proc_name = ""
            pid = 0
            for p in parts:
                if "pid=" in p:
                    m = re.search(r"pid=(\d+)", p)
                    if m:
                        pid = int(m.group(1))
                if 'users:' in p:
                    m2 = re.search(r'"([^"]+)"', p)
                    if m2:
                        proc_name = m2.group(1)

            ports.append(PortInfo(port=port, pid=pid, process=proc_name, protocol="TCP", address=address))
        except (ValueError, IndexError):
            continue

    return ports


def port_label(port: int) -> str:
    """Return a human-friendly label for a well-known port."""
    return _PORT_LABELS.get(port, "")
