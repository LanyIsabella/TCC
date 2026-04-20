from client import Client
from langchain.agents import create_agent
from prompt import load_prompt_sys
from tools import web_search

client = Client()
system_prompt = load_prompt_sys()

agent = create_agent(
    model=client.return_model(),
    tools=[web_search.langsearch_websearch_tool],  # Pass the tool function directly
    system_prompt=system_prompt,
)

response = agent.invoke(
    {"messages": [{"role": "user", "content": "Qual é o clima em São Paulo?"}]}
)

print(response["messages"][-1].content)
