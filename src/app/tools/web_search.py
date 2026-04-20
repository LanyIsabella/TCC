import os

import requests
from dotenv import load_dotenv
from langchain.tools import tool

load_dotenv()
LANGSEARCH_API_KEY = os.getenv("LANGSEARCH_API_KEY")


@tool
def langsearch_websearch_tool(query: str, count: int = 10) -> str:
    """
    Perform web search using LangSearch Web Search API.

    Parameters:
    - query: Search keywords
    - count: Number of search results to return

    Returns:
    - Detailed information of search results, including web page title, web page URL,
    web page content, web page publication time, etc.
    """
    url = os.getenv("LANGSEARCH_HOST")
    if not LANGSEARCH_API_KEY or not url:
        return "LangSearch nao esta configurado no ambiente."

    headers = {
        "Authorization": f"Bearer {LANGSEARCH_API_KEY}",
        "Content-Type": "application/json",
    }
    data = {
        "query": query,
        "freshness": "noLimit",
        "summary": True,
        "count": count,
    }

    try:
        response = requests.post(url, headers=headers, json=data, timeout=30)
    except requests.RequestException as exc:
        return f"Search API request failed, reason: {exc}"

    if response.status_code == 200:
        json_response = response.json()
        try:
            if json_response["code"] != 200 or not json_response["data"]:
                return "Search API request failed, reason: Unknown error"

            webpages = json_response["data"]["webPages"]["value"]
            if not webpages:
                return "No relevant results found."
            formatted_results = ""
            for idx, page in enumerate(webpages, start=1):
                formatted_results += (
                    f"Citation: {idx}\n"
                    f"Title: {page['name']}\n"
                    f"URL: {page['url']}\n"
                    f"Content: {page['summary']}\n"
                )
            return formatted_results.strip()
        except Exception as exc:
            return (
                "Search API request failed, reason: "
                f"Failed to parse search results {exc}"
            )

    return (
        "Search API request failed, status code: "
        f"{response.status_code}, error message: {response.text}"
    )
