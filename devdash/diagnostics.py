"""Safe diagnostics: metadata and timings, never environment values or tool output."""
import platform
import sys
from dataclasses import dataclass
from devdash import __version__


@dataclass
class Diagnostic:
    detector: str
    duration_ms: float
    ok: bool = True
    error_type: str = ''


def diagnostic_report(info, commands) -> str:
    lines = [f'DevWatch / DevDash {__version__}', f'Python: {sys.version.split()[0]}',
             f'Platform: {platform.system()} {platform.machine()}', f'Project root: {info.root}',
             f'Package manager: {info.package_manager or "not detected"}',
             f'Project environment: {info.venv or "inherited interpreter"}', 'Detectors:']
    for item in info.diagnostics:
        lines.append(f'  {item.detector}: {item.duration_ms:.2f}ms {"ok" if item.ok else item.error_type}')
    lines.append('Commands (arguments omitted from debug diagnostics):')
    for command in commands.values():
        lines.append(f'  {command.name}: source={command.provenance}, scope={command.scope}, runner={command.runner}')
        if command.preflight:
            lines.append(f'    preflight: {"runnable" if command.preflight.runnable else command.preflight.reason.value}')
            lines.extend(f'    warning: {warning}' for warning in command.preflight.warnings)
    lines.append(f'Warnings: {len(info.warnings)} (see doctor/status for project details)')
    return '\n'.join(lines)
