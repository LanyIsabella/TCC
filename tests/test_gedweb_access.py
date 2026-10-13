from __future__ import annotations

import requests
from src.app.tools.gedweb_access import GEDWEB_URL, GedwebVPNAccessChecker


class FakeVPNManager:
    def __init__(self) -> None:
        self.events: list[str] = []

    def connect(self) -> None:
        self.events.append("connect")

    def wait_until_connected(self, timeout: float = 60.0) -> None:
        self.events.append(f"wait:{timeout}")

    def disconnect(self) -> None:
        self.events.append("disconnect")


class FakeResponse:
    def __init__(self, status_code: int, url: str = GEDWEB_URL) -> None:
        self.status_code = status_code
        self.url = url
        self.text = "ok"


class FakeSession:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, float]] = []

    def get(self, url: str, timeout: float) -> FakeResponse:
        self.calls.append((url, timeout))
        return self.responses.pop(0)


class BrokenSession:
    def __init__(self) -> None:
        self.calls = 0

    def get(self, url: str, timeout: float) -> FakeResponse:
        self.calls += 1
        raise requests.ConnectionError("connection lost")


def test_gedweb_checker_connects_vpn_before_requesting_site() -> None:
    vpn_manager = FakeVPNManager()
    session = FakeSession([FakeResponse(200), FakeResponse(302)])
    checker = GedwebVPNAccessChecker(
        vpn_manager=vpn_manager,
        http_session=session,
        attempts=2,
        request_timeout=5.0,
        vpn_timeout=30.0,
    )

    result = checker.check()

    assert result.success is True
    assert result.url == GEDWEB_URL
    assert result.status_codes == [200, 302]
    assert session.calls == [(GEDWEB_URL, 5.0), (GEDWEB_URL, 5.0)]
    assert vpn_manager.events == ["connect", "wait:30.0", "disconnect"]


def test_gedweb_checker_reports_unstable_http_status_and_disconnects() -> None:
    vpn_manager = FakeVPNManager()
    session = FakeSession([FakeResponse(200), FakeResponse(503)])
    checker = GedwebVPNAccessChecker(
        vpn_manager=vpn_manager,
        http_session=session,
        attempts=2,
    )

    result = checker.check()

    assert result.success is False
    assert result.status_codes == [200, 503]
    assert "status HTTP inesperado" in result.detail
    assert vpn_manager.events[-1] == "disconnect"


def test_gedweb_checker_reports_connection_errors_and_disconnects() -> None:
    vpn_manager = FakeVPNManager()
    checker = GedwebVPNAccessChecker(
        vpn_manager=vpn_manager,
        http_session=BrokenSession(),
        attempts=2,
    )

    result = checker.check()

    assert result.success is False
    assert result.status_codes == []
    assert "connection lost" in result.detail
    assert vpn_manager.events == ["connect", "wait:60.0", "disconnect"]
