import os
import requests
from tavily import TavilyClient
from dotenv import load_dotenv

load_dotenv()

class SearchEngine:
    def __init__(self):
        self.tavily_key = os.getenv("TAVILY_API_KEY")
        self.serper_key = os.getenv("SERPER_API_KEY")
        self.tavily = TavilyClient(api_key=self.tavily_key) if self.tavily_key else None
        if not self.serper_key and not self.tavily_key:
            raise RuntimeError("TAVILY_API_KEY or SERPER_API_KEY required")

    def search_tavily(self, query):
        try:
            response = self.tavily.search(query=query, search_depth="basic", max_results=5)
            results = []
            for result in response.get('results', []):
                title = result.get('title', 'No Title')
                content = result.get('content', 'No Content')[:500]
                url = result.get('url', '')
                results.append({'title': title, 'content': content, 'url': url})
            return results
        except Exception as e:
            print(f"⚠️ Tavily search failed: {e}")
            return []

    def search_serper(self, query, tbs=None):
        try:
            url = "https://google.serper.dev/search"
            payload = {'q': query, 'num': 5}
            if tbs:
                payload['tbs'] = tbs
            headers = {'X-API-KEY': self.serper_key, 'Content-Type': 'application/json'}
            response = requests.post(url, json=payload, headers=headers)
            data = response.json()
            results = []
            for result in data.get('organic', []):
                title = result.get('title', 'No Title')
                snippet = result.get('snippet', 'No Content')
                link = result.get('link', '')
                results.append({'title': title, 'content': snippet, 'link': link})
            return results
        except Exception as e:
            print(f"⚠️ Serper search failed: {e}")
            return []

    def search(self, query, is_weather=False, is_flight=False):
        """Enhanced search with better handling"""
        try:
            results = []
            
            # Try Tavily first
            if self.tavily:
                results = self.search_tavily(query)
                
            # Fallback to Serper
            if not results and self.serper_key:
                tbs = 'qdr:d' if (is_weather or is_flight) else None
                results = self.search_serper(query, tbs)
            
            if not results:
                return "Search services unavailable at the moment."
            
            # Return structured results for weather/flight
            if is_weather or is_flight:
                return results
            
            # Return formatted result for general queries
            if results:
                first_result = results[0]
                title = first_result.get('title', 'No Title')
                content = first_result.get('content', 'No Content')[:300]
                return f"{title}: {content}"
            
            return "No relevant inzformation found."
            
        except Exception as e:
            print(f"Search error: {e}")
            return "Search functionality is temporarily unavailable."