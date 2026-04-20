from importlib.resources import files

import yaml


def load_prompt_sys() -> str:
    prompt_file = files(__name__).joinpath("prompt_sys.yaml")

    with prompt_file.open("r", encoding="utf-8") as file:
        prompt_data = yaml.safe_load(file)

    if not isinstance(prompt_data, dict) or not prompt_data:
        msg = "prompt_sys.yaml precisa ter um objeto YAML na raiz."
        raise ValueError(msg)

    _, messages = next(iter(prompt_data.items()))
    if not isinstance(messages, list) or not messages:
        msg = "prompt_sys.yaml precisa ter ao menos uma mensagem."
        raise ValueError(msg)

    content = messages[0].get("content")
    if not isinstance(content, str):
        msg = "A primeira mensagem de prompt_sys.yaml precisa ter um campo 'content'."
        raise ValueError(msg)

    return content


prompt_sys = load_prompt_sys()

__all__ = ["load_prompt_sys", "prompt_sys"]
