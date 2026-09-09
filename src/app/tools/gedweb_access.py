from __future__ import annotations

import ctypes
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

import requests
from dotenv import load_dotenv
from langchain.tools import tool

if __package__ in (None, ""):
    # Permite executar este arquivo diretamente a partir da raiz do projeto.
    project_root = Path(__file__).resolve().parents[3]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

from src.app.tools.vpn_acess import OpenVPNManager, VPNConfig

GEDWEB_URL = "https://www.gedweb.com.br/ifg/"
DEFAULT_OPENVPN_EXECUTABLE = r"C:\Program Files\OpenVPN\bin\openvpn.exe"
DEFAULT_OPENVPN_CONFIG_FILE = (
    r"C:\Program Files\OpenVPN\config\ifg-srv-pfs-UDP4-1210-config.ovpn"
)


def is_running_as_admin() -> bool:
    if os.name != "nt":
        return True
    return bool(ctypes.windll.shell32.IsUserAnAdmin())


def ensure_admin_for_cli() -> None:
    """Relanca a ferramenta com UAC antes de abrir a conexao OpenVPN."""
    if is_running_as_admin():
        return

    script_path = str(Path(__file__).resolve())
    parameters = subprocess.list2cmdline([script_path, *sys.argv[1:]])
    result = ctypes.windll.shell32.ShellExecuteW(
        None,
        "runas",
        sys.executable,
        parameters,
        str(Path(__file__).resolve().parent),
        1,
    )

    if result <= 32:
        raise PermissionError(
            "A execucao como Administrador foi cancelada ou falhou."
        )

    raise SystemExit(0)


class VPNManagerProtocol(Protocol):
    def connect(self) -> None: ...

    def wait_until_connected(self, timeout: float = 60.0) -> None: ...

    def disconnect(self) -> None: ...


class HTTPSessionProtocol(Protocol):
    def get(self, url: str, timeout: float) -> requests.Response: ...


@dataclass
class GedwebAccessResult:
    success: bool
    url: str
    attempts: int
    status_codes: list[int] = field(default_factory=list)
    detail: str = ""

    def to_text(self) -> str:
        status_text = ", ".join(str(code) for code in self.status_codes) or "nenhum"
        state = "sucesso" if self.success else "falha"
        return (
            f"GEDWeb via VPN: {state}\n"
            f"URL: {self.url}\n"
            f"Tentativas: {self.attempts}\n"
            f"Status HTTP: {status_text}\n"
            f"Detalhe: {self.detail}"
        )


class GedwebVPNAccessChecker:
    def __init__(
        self,
        vpn_manager: VPNManagerProtocol,
        http_session: HTTPSessionProtocol | None = None,
        url: str = GEDWEB_URL,
        attempts: int = 3,
        request_timeout: float = 10.0,
        vpn_timeout: float = 60.0,
    ) -> None:
        if attempts < 1:
            raise ValueError("attempts deve ser maior ou igual a 1.")

        self.vpn_manager = vpn_manager
        self.http_session = http_session or requests.Session()
        self.url = url
        self.attempts = attempts
        self.request_timeout = request_timeout
        self.vpn_timeout = vpn_timeout

    def check(self) -> GedwebAccessResult:
        status_codes: list[int] = []

        try:
            self.vpn_manager.connect()
            self.vpn_manager.wait_until_connected(timeout=self.vpn_timeout)

            for _ in range(self.attempts):
                response = self.http_session.get(
                    self.url,
                    timeout=self.request_timeout,
                )
                status_codes.append(response.status_code)

                if not 200 <= response.status_code < 400:
                    return GedwebAccessResult(
                        success=False,
                        url=self.url,
                        attempts=self.attempts,
                        status_codes=status_codes,
                        detail=(
                            "status HTTP inesperado ao acessar GEDWeb: "
                            f"{response.status_code}"
                        ),
                    )

            return GedwebAccessResult(
                success=True,
                url=self.url,
                attempts=self.attempts,
                status_codes=status_codes,
                detail="site acessivel de forma estavel pela VPN",
            )

        except requests.RequestException as exc:
            return GedwebAccessResult(
                success=False,
                url=self.url,
                attempts=self.attempts,
                status_codes=status_codes,
                detail=f"erro de conexao HTTP: {exc}",
            )
        except Exception as exc:
            return GedwebAccessResult(
                success=False,
                url=self.url,
                attempts=self.attempts,
                status_codes=status_codes,
                detail=f"erro durante teste via VPN: {exc}",
            )
        finally:
            self.vpn_manager.disconnect()


def build_default_vpn_manager() -> OpenVPNManager:
    load_dotenv()
    config = VPNConfig(
        openvpn_executable=os.getenv(
            "OPENVPN_EXECUTABLE",
            DEFAULT_OPENVPN_EXECUTABLE,
        ),
        ovpn_file=os.getenv(
            "OPENVPN_CONFIG_FILE",
            DEFAULT_OPENVPN_CONFIG_FILE,
        ),
        username=os.getenv("VPN_USERNAME"),
        password=os.getenv("VPN_PASSWORD"),
    )
    return OpenVPNManager(config)


@tool
def gedweb_vpn_access_tool(attempts: int = 3) -> str:
    """
    Connect to the IFG OpenVPN profile and validate stable access to GEDWeb.
    """

    checker = GedwebVPNAccessChecker(
        vpn_manager=build_default_vpn_manager(),
        attempts=attempts,
    )
    return checker.check().to_text()


if __name__ == "__main__":
    ensure_admin_for_cli()
    print(gedweb_vpn_access_tool.invoke({"attempts": 3}))
