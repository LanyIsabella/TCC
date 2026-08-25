from __future__ import annotations

import os
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


class VPNConnectionError(RuntimeError):
    """Erro ao estabelecer a conexao OpenVPN."""


class VPNConnectionTimeoutError(TimeoutError):
    """Timeout aguardando a conexao OpenVPN ficar pronta."""


@dataclass
class VPNConfig:
    """
    Configuracoes da VPN.
    """

    openvpn_executable: str
    ovpn_file: str
    username: str | None
    password: str | None


class OpenVPNManager:
    """
    Gerenciador de conexao OpenVPN para Windows.

    Responsabilidades:
    - Criar arquivo temporario de credenciais.
    - Iniciar o OpenVPN.
    - Exibir logs em tempo real.
    - Encerrar a conexao de forma controlada.
    """

    def __init__(self, config: VPNConfig):
        self.config = config
        self.process: subprocess.Popen | None = None
        self.auth_file: str | None = None

    def validate(self) -> None:
        """
        Valida a existencia dos arquivos necessarios.
        """

        if not Path(self.config.openvpn_executable).exists():
            raise FileNotFoundError(
                f"OpenVPN nao encontrado: {self.config.openvpn_executable}"
            )

        if not Path(self.config.ovpn_file).exists():
            raise FileNotFoundError(
                f"Arquivo OVPN nao encontrado: {self.config.ovpn_file}"
            )

        missing_credentials = [
            field_name
            for field_name, value in {
                "VPN_USERNAME": self.config.username,
                "VPN_PASSWORD": self.config.password,
            }.items()
            if not value
        ]
        if missing_credentials:
            raise ValueError(
                "Credenciais da VPN nao configuradas: "
                + ", ".join(missing_credentials)
            )

    def create_auth_file(self) -> str:
        """
        Cria arquivo temporario contendo usuario e senha.

        Formato esperado pelo OpenVPN:
            linha 1 -> usuario
            linha 2 -> senha
        """

        temp = tempfile.NamedTemporaryFile(
            mode="w",
            delete=False,
            suffix=".txt",
            encoding="utf-8",
        )

        temp.write(f"{self.config.username}\n")
        temp.write(f"{self.config.password}\n")
        temp.close()

        self.auth_file = temp.name
        return self.auth_file

    def connect(self) -> None:
        """
        Inicia a conexao VPN.
        """

        self.validate()

        auth_file = self.create_auth_file()

        command = [
            self.config.openvpn_executable,
            "--config",
            self.config.ovpn_file,
            "--auth-user-pass",
            auth_file,
        ]

        print("=" * 60)
        print("Iniciando conexao OpenVPN...")
        print("=" * 60)

        self.process = subprocess.Popen(
            command,
            cwd=str(Path(self.config.ovpn_file).parent),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            universal_newlines=True,
        )

    def wait_until_connected(self, timeout: float = 60.0) -> None:
        """
        Aguarda o OpenVPN confirmar que a conexao foi estabelecida.
        """

        if not self.process or not self.process.stdout:
            raise RuntimeError("A VPN ainda nao foi iniciada.")

        deadline = time.monotonic() + timeout
        while True:
            if time.monotonic() > deadline:
                raise VPNConnectionTimeoutError(
                    "Timeout aguardando a VPN conectar."
                )

            if self.process.poll() is not None:
                raise VPNConnectionError(
                    "Processo OpenVPN encerrou antes de completar a conexao."
                )

            line = self.process.stdout.readline()
            if not line:
                continue

            line = line.strip()
            if line:
                print(line)

            if "Initialization Sequence Completed" in line:
                print("\nVPN conectada com sucesso.\n")
                return

            if "AUTH_FAILED" in line:
                raise VPNConnectionError("Autenticacao da VPN falhou.")

            if "Exiting due to fatal error" in line:
                raise VPNConnectionError("OpenVPN encerrou por erro fatal.")

    def monitor(self) -> None:
        """
        Monitora os logs do OpenVPN.
        """

        if not self.process or not self.process.stdout:
            raise RuntimeError("A VPN ainda nao foi iniciada.")

        try:
            for line in self.process.stdout:
                line = line.strip()

                if line:
                    print(line)

                    if "Initialization Sequence Completed" in line:
                        print("\nVPN conectada com sucesso.\n")

        except KeyboardInterrupt:
            print("\nEncerrando VPN...")
            self.disconnect()

    def disconnect(self) -> None:
        """
        Finaliza a conexao e remove arquivos temporarios.
        """

        if self.process and self.process.poll() is None:
            self.process.terminate()

        if self.auth_file and Path(self.auth_file).exists():
            os.remove(self.auth_file)

        print("VPN encerrada.")

    def run(self) -> None:
        """
        Fluxo principal.
        """

        try:
            self.connect()
            self.monitor()

        finally:
            self.disconnect()


def main():
    load_dotenv()
    vpn = VPNConfig(
        openvpn_executable=os.getenv(
            "OPENVPN_EXECUTABLE",
            r"C:\Program Files\OpenVPN\bin\openvpn.exe",
        ),
        ovpn_file=os.getenv(
            "OPENVPN_CONFIG_FILE",
            r"C:\Program Files\OpenVPN\config\ifg-srv-pfs-UDP4-1210-config.ovpn",
        ),
        username=os.getenv("VPN_USERNAME"),
        password=os.getenv("VPN_PASSWORD"),
    )

    manager = OpenVPNManager(vpn)
    manager.run()


if __name__ == "__main__":
    main()
