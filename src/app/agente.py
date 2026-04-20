from client import Client
from langchain.agents import create_agent


def get_weather(city: str) -> str:
    """Get weather for a given city."""
    return f"It's always sunny in {city}!"


client = Client()

agent = create_agent(
    model=client.return_model(),
    tools=[get_weather],
    system_prompt="You are a helpful assistant",
)

response = agent.invoke(
    {"messages": [{"role": "user", "content": "Qual é o clima em São Paulo?"}]}
)

print(response["messages"][-1].content)
