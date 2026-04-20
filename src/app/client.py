import os

from dotenv import load_dotenv
from langchain_ollama import ChatOllama


class Client:
    def __init__(self):
        load_dotenv()
        self.model_name = os.getenv("OLLAMA_MODEL")
        self.ollama_host = os.getenv("OLLAMA_HOST")
        self.ollama_temperature = float(os.getenv("OLLAMA_TEMPERATURE", "0"))
        self.model = ChatOllama(
            model=self.model_name,
            temperature=self.ollama_temperature,
            base_url=self.ollama_host,
        )

    def return_model(self):
        return self.model

    # def generate_response(self, messages):
    #     return self.model(messages)
