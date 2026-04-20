import os

from dotenv import load_dotenv
from langchain_ollama import ChatOllama


class Client:
    def __init__(self) -> None:
        load_dotenv()
        self.model_name = os.getenv("OLLAMA_MODEL")
        self.ollama_host = os.getenv("OLLAMA_HOST")
        self.ollama_temperature = float(os.getenv("OLLAMA_TEMPERATURE", "0"))
        missing_values = [
            variable_name
            for variable_name, value in {
                "OLLAMA_MODEL": self.model_name,
                "OLLAMA_HOST": self.ollama_host,
            }.items()
            if not value
        ]
        if missing_values:
            msg = "Variaveis de ambiente obrigatorias nao configuradas: " + ", ".join(
                missing_values
            )
            raise ValueError(msg)

        self.model = ChatOllama(
            model=self.model_name,
            temperature=self.ollama_temperature,
            base_url=self.ollama_host,
        )

    def return_model(self) -> ChatOllama:
        return self.model
