from src.app import client as client_module


class FakeChatOllama:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


def test_client_uses_zero_temperature_from_environment(monkeypatch):
    monkeypatch.setenv("OLLAMA_MODEL", "gemma4:e2b")
    monkeypatch.setenv("OLLAMA_HOST", "http://localhost:11434")
    monkeypatch.setenv("OLLAMA_TEMPERATURE", "0")
    monkeypatch.setattr(client_module, "ChatOllama", FakeChatOllama)

    client = client_module.Client()

    assert client.ollama_temperature == 0
    assert client.return_model().kwargs["temperature"] == 0
