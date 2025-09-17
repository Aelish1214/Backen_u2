import os
import re
import json
import asyncio
from datetime import datetime
from typing import Dict, List, Optional, Tuple
import aiohttp
from bs4 import BeautifulSoup
import cohere
from dotenv import load_dotenv
import urllib.parse
import random
from langdetect import detect
from langdetect.lang_detect_exception import LangDetectException
from .Characteristics import AssistantCharacteristics

load_dotenv()

# ---- module-scope optional import for key_manager token counter ----
try:
    # If your project already has key_manager.count_tokens, reuse it
    from app.key_manager import count_tokens as _KM_COUNT_TOKENS
except Exception:
    _KM_COUNT_TOKENS = None


class QueryProcessor:
    def __init__(self, groq_key: Optional[str] = None, cohere_key: Optional[str] = None):
        self.assistant = AssistantCharacteristics()
        self.groq_api_key = groq_key or os.getenv("GROQ_API_KEY")
        self.cohere_api_key = cohere_key or os.getenv("COHERE_API_KEY")
        self.tavily_api_key = os.getenv("TAVILY_API_KEY")
        self.serper_api_key = os.getenv("SERPER_API_KEY")

        if not self.groq_api_key:
            raise ValueError("Missing GROQ_API_KEY")
        if not self.cohere_api_key:
            raise ValueError("Missing COHERE_API_KEY")

        self.cohere_client = cohere.Client(self.cohere_api_key)

        # Enhanced patterns - prioritize breaking news keywords for real-time
        self.realtime_patterns = [
            r'\b(breaking|urgent|alert|emergency)\b',
            r'\b(latest|recent|today|current|now|news|update|todays.*news)\b',
            r'\b(what.*happening|current.*status|live.*updates)\b',
            r'\b(prime minister|president|ceo|stock.*price|weather.*today)\b',
            r'\b(cricket.*score|match.*result|election.*result)\b',
            r'\b(trending|viral|popular.*today)\b',
            r'\b(corona|covid|vaccine)\b',
            r'\b(price.*of|cost.*of|rate.*of)\b'
        ]
        
        # Specific news patterns
        self.news_patterns = [
            r'\b(breaking|urgent|alert|emergency)\b',
            r'\b(latest.*news|recent.*news|news.*today|news.*update)\b',
            r'\b(current.*news|todays.*news)\b'
        ]
        
        # Specific Spotify patterns
        self.spotify_patterns = [
            r'\bplay\b.*\bon\s+spotify\b',
            r'\bopen\s+spotify\b',
            r'\bspotify\b.*\b(play|song|music|track)\b'
        ]
        
        self.datetime_patterns = [
            r'\b(date|time|current date|current time|what.*date|what.*time)\b',
            r'\b(day|month|year|hour|minute|clock)\b'
        ]
        
        self.url_patterns = {
            'open': [
                r'\bopen\b.*\b(spotify|netflix|amazon|facebook|instagram|whatsapp|gmail|youtube|google)\b',
                r'\b(go to|visit)\b.*\.(com|org|net|in)\b'
            ],
            'youtube': [
                r'\b(play|watch|youtube)\b.*\b(video|song|music)\b(?!.*spotify)',
                r'\b(show me|find)\b.*\b(video|song|music)\b(?!.*spotify)',
                r'\b(listen to|watch)\b.*\b(song|video)\b(?!.*spotify)'
            ],
            'maps': [

                r'\b(navigate|directions|route|map|maps|distance|tell distance)\b',
                r'\b(go to|how to reach|way to|path to)\b.*\b(place|location|city|station|airport|mall|hospital)\b',
                r'\b(location of|where is|find place|distance.*between|distance.*from|tell.*distance)\b',
                r'\b(nearest|near me|around me|close to)\b',
                r'\b(from.*to|between.*and)\b'
            ]
        }

        self.user_agents = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        ]

        # Language translations for common terms
        self.lang_translations = {
            'bn': {
                'খোল': 'open', 'চালা': 'play', 'সংবাদ': 'news', 'আজ': 'today', 'সময়': 'time',
                'কোথায়': 'where', 'কিভাবে': 'how', 'যাওয়া': 'go', 'রাস্তা': 'route', 'দিক': 'direction'
            }
        }
        self.hinglish_words = {}

    # ---------- utilities ----------
    @staticmethod
    def _count_tokens_text(text: str) -> int:
        """Token count (cl100k_base). Falls back safely if tiktoken not available or key_manager missing."""
        if _KM_COUNT_TOKENS is not None:
            # second arg is just a label in your impl; not used by encoder there
            try:
                return _KM_COUNT_TOKENS(text or "", "tavily")
            except Exception:
                pass
        try:
            import tiktoken
            enc = tiktoken.get_encoding("cl100k_base")
            return len(enc.encode(text or ""))
        except Exception:
            # last-resort fallback (rough word count)
            return len((text or "").split())

    def detect_and_correct_query(self, query: str) -> Tuple[str, str, bool]:
        """Detect language, correct spelling/grammar and normalize query"""
        try:
            # Detect language
            lang = detect(query)
            query_lower = query.lower()
            try:
                lang = detect(query)
            except LangDetectException:
                lang = 'en'
            # Basic translation for common terms
            query_lower = query.lower()
            if lang in self.lang_translations:
                for native, english in self.lang_translations[lang].items():
                    query_lower = query_lower.replace(native.lower(), english)
            
            # Grammar corrections
            corrections = {
               r'\bwhat\s+is\s+the\s+time\b': 'what time is it',
                r'\bwhat\s+is\s+todays?\s+date\b': 'what is the date today',
                r'\bopen\s+the\s+': 'open ',
                r'\bplay\s+the\s+': 'play ',
                r'\bshow\s+me\s+the\s+': 'show me ',
                r'\btell\s+me\s+about\s+': 'about ',
                r'\blatest\s+news\s+about\s+': 'latest news ',
                r'\bhow\s+to\s+go\s+to\s+': 'navigate to ',
                r'\bway\s+to\s+go\s+to\s+': 'navigate to ',
                r'\bshow\s+route\s+to\s+': 'navigate to ',
                r'\bdirection\s+to\s+': 'navigate to ',
                r'\bmap\s+to\s+': 'navigate to ',
                r'\bwhere\s+is\s+': 'location of ',
                r'\bdistance\s+from\s+(.+?)\s+to\s+(.+)': r'distance between \1 and \2',
                r'\btell\s+distance\s+from\s+(.+?)\s+to\s+(.+)': r'distance between \1 and \2',
                r'\bopen\s+and\s+tell\s+in\s+(.+?)\s+(.+)\s+distance\b': r'distance between \1 and \2',
                r'\bopen\s+youtube\s+and\s+play\s+': 'play ',
                r'\b(.+?)\s+to\s+(.+?)(?:\s+distance|$)' : r'distance between \1 and \2'  

            }
            
            for pattern, replacement in corrections.items():
                query_lower = re.sub(pattern, replacement, query_lower, flags=re.IGNORECASE)
            
            return query_lower.strip(), lang, False
            
        except Exception as e:
            print(f"   ❌ Language detection error: {e}")
            return query.lower().strip(), 'en', False
        
    def get_headers(self):
        """Get randomized headers for web scraping"""
        return {
            'User-Agent': random.choice(self.user_agents),
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Connection': 'keep-alive',
        }

    def is_news_query(self, query: str) -> bool:
        """Check if query is specifically about news"""
        for pattern in self.news_patterns:
            if re.search(pattern, query, re.IGNORECASE):
                return True
        return False

    def is_spotify_query(self, query: str) -> bool:
        """Check if query is specifically about Spotify"""
        for pattern in self.spotify_patterns:
            if re.search(pattern, query, re.IGNORECASE):
                return True
        return False

    def classify_query(self, query: str) -> Tuple[str, str, bool]:
        """Enhanced query classification with language detection"""
        corrected_query, detected_lang, is_hinglish= self.detect_and_correct_query(query)
        
        print(f"🔍 QUERY CLASSIFICATION:")
        print(f"   Original: {query}")
        print(f"   Corrected: {corrected_query}")
        print(f"   Language: {detected_lang}")
        
        # DateTime first - but exclude news patterns
        for pattern in self.datetime_patterns:
            if re.search(pattern, corrected_query, re.IGNORECASE):
                if not any(re.search(news_pattern, corrected_query, re.IGNORECASE) for news_pattern in self.realtime_patterns):
                    print(f"   ✅ Type: DATETIME")
                    return f"datetime {corrected_query}", detected_lang, "datetime", is_hinglish
        
        # Check for Spotify specifically
        if self.is_spotify_query(corrected_query):
            print(f"   ✅ Type: SPOTIFY")
            return f"open {corrected_query}", detected_lang, "open" , is_hinglish
        
        # URL patterns (higher priority)
        for category, patterns in self.url_patterns.items():
            for pattern in patterns:
                if re.search(pattern, corrected_query, re.IGNORECASE):
                    print(f"   ✅ Type: {category.upper()}")
                    return f"{category} {corrected_query}", detected_lang, category, is_hinglish
        
        # Realtime patterns
        for pattern in self.realtime_patterns:
            if re.search(pattern, corrected_query, re.IGNORECASE):
                print(f"   ✅ Type: REAL-TIME")
                return f"realtime {corrected_query}", detected_lang, "realtime",  is_hinglish
        
        print(f"   ✅ Type: GENERAL")
        return f"general {corrected_query}", detected_lang, "general", is_hinglish

    async def process_query(self, user_query: str, chat_history: Optional[List[Dict]] = None)-> Dict:
        """Main processing logic with enhanced debugging"""
        classification, detected_lang, query_type, is_hinglish = self.classify_query(user_query)
        actual_query = classification.split(' ', 1)[1]
        if self.assistant.should_use_quick_response(user_query):
            response = self.assistant.get_quick_response(user_query)
            if response:
                return {
                    "type": "greeting",
                    "text": self.assistant.truncate_response(response),
                    "url": None
                }
        
        if self.assistant.is_greeting(user_query):
            response = self.assistant.get_greeting(user_query, chat_history)
            return {
                "type": "greeting",
                "text": self.assistant.truncate_response(response),
                "url": None
            }
        
        print(f"\n🚀 PROCESSING QUERY:")
        print(f"   Type: {query_type}")
        print(f"   Language: {detected_lang}")
        print(f"   Query: {actual_query}")
        
        handlers = {
            "datetime": self.handle_datetime_query,
            "general": self.handle_general_query,
            "realtime": self.handle_realtime_query,
            "youtube": self.handle_youtube_query,
            "maps": self.handle_maps_query,
            "open": self.handle_open_query
        }
        
        handler = handlers.get(query_type, self.handle_general_query)
        
        if asyncio.iscoroutinefunction(handler):
            if query_type in ["general", "maps"]:
                result = await handler(actual_query, detected_lang, is_hinglish)
            else:
                result = await handler(actual_query)
        else:
            result = handler(actual_query, detected_lang, is_hinglish)
    
        result["text"] = self.assistant.apply_tone(
            self.assistant.truncate_response(result["text"]),
            query_type
        )
        
        return result

    def handle_datetime_query(self, query: str, detected_lang: str = 'en', is_hinglish: bool = False) -> Dict:
        """Handle datetime queries"""
        print(f"📅 DATETIME HANDLER:")
        now = datetime.now()
        
        if 'time' in query:
            response = f"Current time: {now.strftime('%I:%M:%S %p')}"
        elif 'date' in query:
            response = f"Today's date: {now.strftime('%B %d, %Y')}"
        else:
            response = f"Current date and time: {now.strftime('%B %d, %Y at %I:%M:%S %p')}"
        
        print(f"   ✅ Response: {response}")
        return {"type": "datetime", "text": response, "url": None}

    async def handle_general_query(self, query: str, detected_lang: str ='en', is_hinglish: bool = False) -> Dict:
        """Handle general queries with language-aware responses"""
        print(f"💬 GENERAL HANDLER:")
        
        # Check if it might benefit from a web search for current info
        current_info_patterns = [
            r'\b(who is.*prime minister|who is.*president|who is.*ceo)\b',
            r'\b(current.*prime minister|current.*president)\b',
            r'\b(prime minister.*of.*uk|president.*of.*usa)\b'
        ]
        
        might_need_search = any(re.search(pattern, query, re.IGNORECASE) 
                               for pattern in current_info_patterns)
        
        if might_need_search:
            print(f"   🔍 Might need web search - trying Google first...")
            
            # Try Google search for URL first
            google_result = await self._google_search(query)
            if google_result and google_result.get('url'):
                print(f"   ✅ Found Google URL - returning web result")
                google_result['type'] = 'general'  # Change type to general
                return google_result
            
            # If no Google URL, just use GROQ (no Tavily for general queries)
            print(f"   ⚠️  No Google URL found - using GROQ for general knowledge")
        
        print(f"   🔄 Using GROQ API for general response")
        print(f"   Source: GROQ API")
        print(f"   Language: {detected_lang}")
        
        try:
            async with aiohttp.ClientSession() as session:
                headers = {
                    "Authorization": f"Bearer {self.groq_api_key}",
                    "Content-Type": "application/json"
                }
                
                # Only respond in same language if user is clearly using that language
                if detected_lang in ['hi', 'gu', 'bn'] and len([c for c in query if ord(c) > 127]) > 3:
                    prompt = f"Answer in the same language as the question. Keep response 1-2 sentences: {query}"
                else:
                    prompt = f"Answer in English. Keep response 1-2 sentences: {query}"
                
                payload = {
                    "messages": [{"role": "user", "content": prompt}],
                    "model": "llama-3.3-70b-versatile",
                    "temperature": 0.7,
                    "max_tokens": 150
                }
                
                async with session.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers=headers,
                    json=payload
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        content = data.get('choices', [{}])[0].get('message', {}).get('content', 'No response')
                        print(f"   ✅ Response generated successfully")
                        return {"type": "general", "text": content, "url": None}
                    else:
                        print(f"   ❌ API error: {response.status}")
                        return {"type": "error", "text": f"API error: {response.status}", "url": None}

        except Exception as e:
            print(f"   ❌ Error: {str(e)}")
            return {"type": "error", "text": f"Error: {str(e)}", "url": None}

    def classify_realtime_type(self, query: str) -> str:
        """Classify realtime query as 'factual' or 'contextual'"""
        prompt = f"""
        Classify this user query as either 'factual' or 'contextual' real-time.
        Definitions:
        - factual: asks for one specific current fact (price, weather, score, time, value)
        - contextual: asks for multiple options, events, activities, or things happening now
        Return only one word: 'factual' or 'contextual'.
        Query: "{query}"
        Answer:
        """
        try:
            resp = self.cohere_client.generate(
                model="command-light",
                prompt=prompt.strip(),
                max_tokens=5,
                temperature=0
            )
            label = resp.generations[0].text.strip().lower()
            if "contextual" in label:
                return "contextual"
            return "factual"
        except Exception as e:
            print(f"   ❌ Cohere error: {e}")
            return "factual"

    async def handle_realtime_query(self, query: str) -> Dict:
        """Enhanced realtime search - News/Spotify get Tavily, Factual gets Google URL, Contextual gets APIs"""
        print(f"📡 REAL-TIME HANDLER:")
        
        # Check specific types first
        is_news = self.is_news_query(query)
        is_spotify = self.is_spotify_query(query)
        
        if is_news:
            print(f"   📰 NEWS query - using Tavily API")
            if self.tavily_api_key:
                result = await self._tavily_search(query)
                if result:
                    print(f"   ✅ Response from: TAVILY API")
                    return result
        
        if is_spotify:
            print(f"   🎵 SPOTIFY query - using Tavily API")
            if self.tavily_api_key:
                result = await self._tavily_search(query)
                if result:
                    print(f"   ✅ Response from: TAVILY API")
                    return result
        
        # Classify other realtime queries
        realtime_type = self.classify_realtime_type(query)
        print(f"   🔍 Realtime type: {realtime_type}")
        
        if realtime_type == "factual":
            # Factual = Google URL
            print(f"   📊 FACTUAL query - returning Google URL")
            search_url = f"https://www.google.com/search?q={urllib.parse.quote_plus(query)}"
            return {
                "type": "realtime",
                "text": f"Here are search results for '{query}'. Click to view latest information.",
                "url": search_url,
                "metadata": {"search_method": "google_url", "realtime_type": "factual"}
            }
        
        else:  # contextual
            print(f"   🌐 CONTEXTUAL query - using APIs")
            
            # Try Tavily first
            if self.tavily_api_key:
                print(f"   🔄 Trying Tavily API...")
                result = await self._tavily_search(query)
                if result:
                    print(f"   ✅ Response from: TAVILY API")
                    return result
            
            # Fallback to Serper
            if self.serper_api_key:
                print(f"   🔄 Trying Serper API...")
                result = await self._serper_search(query)
                if result:
                    print(f"   ✅ Response from: SERPER API")
                    return result
        
        # Final fallback
        search_url = f"https://www.google.com/search?q={urllib.parse.quote_plus(query)}"
        return {
            "type": "realtime",
            "text": f"Here are search results for '{query}'. Click to view latest information.",
            "url": search_url,
            "metadata": {"search_method": "fallback"}
        }

    async def _google_search(self, query: str) -> Optional[Dict]:
        """Google search with priority news sources"""
        priority_sites = ["gujaratsamachar.com", "divyabhaskar.co.in", "aajtak.in", "ndtv.com", "timesofindia.indiatimes.com"]
        
        for site in priority_sites:
            try:
                search_url = f"https://www.google.com/search?q=site:{site}+{urllib.parse.quote_plus(query)}"
                
                async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=8)) as session:
                    async with session.get(search_url, headers=self.get_headers()) as response:
                        if response.status == 200:
                            html = await response.text()
                            soup = BeautifulSoup(html, 'html.parser')
                            
                            results = soup.select('div.g, div.tF2Cxc, .rc')
                            for result in results[:2]:
                                links = result.find_all('a', href=True)
                                for link in links:
                                    href = link.get('href', '')
                                    if href.startswith('/url?q='):
                                        href = href.split('?q=')[1].split('&')[0]
                                        href = urllib.parse.unquote(href)
                                    
                                    if href.startswith('http') and site in href:
                                        h3 = result.find('h3')
                                        title = h3.get_text(strip=True) if h3 else "Latest News"
                                        
                                        return {
                                            "type": "realtime",
                                            "text": f"Latest news about '{query}':\n{title}",
                                            "url": href,
                                            "metadata": {"source": site, "title": title, "search_method": "google"}
                                        }
            except:
                continue
        
        return None

    async def _tavily_search(self, query: str) -> Optional[Dict]:
        """Tavily API search — now returns token counts for input & output."""
        input_tokens = self._count_tokens_text(query)
        try:
            async with aiohttp.ClientSession() as session:
                payload = {
                    "api_key": self.tavily_api_key,
                    "query": query,
                    "search_depth": "basic",
                    "include_answer": True,
                    "max_results": 3
                }
                async with session.post("https://api.tavily.com/search", json=payload) as response:
                    if response.status == 200:
                        data = await response.json()

                        # 1) Direct answer path
                        if data.get('answer'):
                            clean_answer = str(data['answer']).strip()
                            # sanitize weird JSONy answers (optional)
                            if clean_answer.startswith('{') or clean_answer.startswith('['):
                                clean_answer = "Weather information available - check the search results for details."
                            output_tokens = self._count_tokens_text(clean_answer)

                            return {
                                "type": "realtime",
                                "text": clean_answer,
                                "url": None,
                                "metadata": {"source": "tavily", "search_method": "tavily_answer"},
                                "token_usage": {
                                    "provider": "tavily",
                                    "input_tokens": input_tokens,
                                    "output_tokens": output_tokens,
                                    "total_tokens": input_tokens + output_tokens
                                }
                            }

                        # 2) Fallback to first result content
                        if data.get('results'):
                            first_result = data['results'][0]
                            content = first_result.get('content', '')
                            # optional cleanup for weather-like JSON blobs
                            if content.startswith('{') or content.startswith('[') or 'location' in content.lower():
                               if any(word in query.lower() for word in ['weather', 'temperature', 'climate']):
                                    content = f"Current weather information for {query}. Check weather apps for detailed forecast."
                            # Keep the same truncation policy as before
                            display_text = content[:300] if len(content) > 300 else content

                            output_tokens = self._count_tokens_text(display_text)
                            return {
                                "type": "realtime",
                                "text": f"Latest information: {display_text}",
                                "url": None,
                                "metadata": {"source": "tavily", "title": first_result.get('title'), "search_method": "tavily"},
                                "token_usage": {
                                    "provider": "tavily",
                                    "input_tokens": input_tokens,
                                    "output_tokens": output_tokens,
                                    "total_tokens": input_tokens + output_tokens
                                }
                            }

                    # Non-200 or empty results
                    return {
                        "type": "realtime",
                        "text": "No direct answer found.",
                        "url": None,
                        "metadata": {"source": "tavily", "search_method": "tavily_error", "status": response.status},
                        "token_usage": {
                            "provider": "tavily",
                            "input_tokens": input_tokens,
                            "output_tokens": 0,
                            "total_tokens": input_tokens
                        }
                    }
        except Exception as e:
            # On exception, still return counts for input
            return {
                "type": "realtime",
                "text": f"Tavily error: {e}",
                "url": None,
                "metadata": {"source": "tavily", "search_method": "tavily_exception"},
                "token_usage": {
                    "provider": "tavily",
                    "input_tokens": input_tokens,
                    "output_tokens": 0,
                    "total_tokens": input_tokens
                }
            }

    async def _serper_search(self, query: str) -> Optional[Dict]:
        """Serper API search"""
        try:
            async with aiohttp.ClientSession() as session:
                headers = {"X-API-KEY": self.serper_api_key, "Content-Type": "application/json"}
                payload = {"q": query, "num": 3}
                
                async with session.post("https://google.serper.dev/search", headers=headers, json=payload) as response:
                    if response.status == 200:
                        data = await response.json()
                        if data.get('organic'):
                            first_result = data['organic'][0]
                            return {
                                "type": "realtime",
                                "text": f"Search result: {first_result.get('snippet', '')[:200]}...",
                                "url": first_result.get('link'),
                                "metadata": {"source": "serper", "title": first_result.get('title'), "search_method": "serper"}
                            }
        except Exception as e:
            print(f"   ❌ Serper search error: {e}")
        
        return None

    async def handle_youtube_query(self, query: str) -> Dict:
        """Handle YouTube queries"""
        print(f"🎥 YOUTUBE HANDLER:")
        
        search_terms = re.sub(r'\b(play|watch|youtube|video|song|music|show me|find|listen to|open youtube and)\b', '', query, flags=re.IGNORECASE).strip()
        
        if not search_terms:
            search_terms = "popular music"
        
        youtube_url = f"https://www.youtube.com/results?search_query={urllib.parse.quote_plus(search_terms)}"
        
        print(f"   ✅ Generated YouTube URL for: {search_terms}")
        return {
            "type": "youtube",
            "text":  self.assistant.format_response("play_music", song=search_terms),
            "url": youtube_url,
            "metadata": {"search_terms": search_terms}
        }

    async def handle_maps_query(self, query: str, detected_lang: str = 'en', is_hinglish: bool = False)  -> Dict:
        """Handle maps queries"""
        print(f"🗺️  MAPS HANDLER:")
        
        direction_patterns = [
            r'(?:navigate|directions|route|go|way)\s+(?:to|from)?\s*(.+?)(?:\s*[.,]|$)',
            r'(?:how to reach|path to)\s+(.+?)(?:\s*[.,]|$)',
            r'(?:take me to)\s+(.+?)(?:\s*[.,]|$)',
        ]
        
        location_patterns = [
            r'(?:location of|where is|find)\s+(.+?)(?:\s*[.,]|$)',
            r'(?:address of|position of)\s+(.+?)(?:\s*[.,]|$)',
        ]
        
        distance_patterns = [
            r'(?:distance|tell distance)\s+(?:between|from)\s+(.+?)\s+(?:to|and)\s+(.+?)(?:\s*[.,]|$)',
            r'(?:how far)\s+(?:is)?\s*(.+?)(?:\s*[.,]|$)',
            r'(.+?)\s+to\s+(.+?)(?:\s+distance|$)'  # New pattern for "sarthana to althan distance"
        ]
        
        near_me_patterns = [
            r'(?:near me|around me|close to me)',
            r'(?:nearest|closest)',
        ]
        
        current_location_patterns = [
            r'\b(current location|current|my location)\b'
        ]
        is_near_me = any(re.search(pattern, query, re.IGNORECASE) for pattern in near_me_patterns)
        is_current_location = any(re.search(pattern, query, re.IGNORECASE) for pattern in current_location_patterns) or not re.search(r'\bfrom\b', query, re.IGNORECASE)
        for pattern in distance_patterns:
            match = re.search(pattern, query, re.IGNORECASE)
            if match:
                if len(match.groups()) == 2:
                    origin = match.group(1).strip()
                    destination = match.group(2).strip()
                    if 'current location' in origin.lower():
                        origin = 'Current+Location'
                    print(f"   📏 Distance query: {origin} → {destination}")
                    
                    maps_url = f"https://www.google.com/maps/dir/{urllib.parse.quote_plus(origin)}/{urllib.parse.quote_plus(destination)}"
                    response_text = f"Route and distance from {origin.title()} to {destination.title()}. Click to view directions on Google Maps."

                    return {
                        "type": "maps",
                        "text": response_text,
                        "url": maps_url,
                        "metadata": {"origin": origin, "destination": destination, "query_type": "distance"}
                    }
                else:
                    destination = match.group(1).strip()
                    origin = 'Current+Location' if is_current_location else destination
                    print(f"   📏 Distance to: {destination} from {origin}")
                    maps_url = f"https://www.google.com/maps/dir/{urllib.parse.quote_plus(origin)}/{urllib.parse.quote_plus(destination)}"
                    response_text = f"Distance and route to {destination.title()} from {origin.replace('+', ' ')}. Click to view directions on Google Maps."
                    return {
                        "type": "maps",
                        "text": response_text,
                        "url": maps_url,
                        "metadata": {"destination": destination, "query_type": "distance_from_current"}
                    }
        for pattern in location_patterns:
            match = re.search(pattern, query, re.IGNORECASE)
            if match:
                location = match.group(1).strip()
                print(f"   📍 Location search: {location}")
                if is_near_me:
                    maps_url = f"https://www.google.com/maps/search/{urllib.parse.quote_plus(location)}+near+me"
                    response_text = f"Finding {location.title()} locations near you. Click to view on Google Maps."
                else:
                    maps_url = f"https://www.google.com/maps/search/{urllib.parse.quote_plus(location)}"
                    response_text = f"Showing location of {location.title()} on Google Maps."
                return {
                    "type": "maps",
                    "text": response_text,
                    "url": maps_url,
                    "metadata": {"location": location, "query_type": "location_search", "near_me": is_near_me}
                }
        
    async def handle_open_query(self, query: str) -> Dict:
        """Enhanced website opening with Spotify support"""
        print(f"🌐 OPEN HANDLER:")
        
        website_mappings = {
            'spotify': 'https://open.spotify.com',
            'netflix': 'https://www.netflix.com',
            'amazon': 'https://www.amazon.com',
            'flipkart': 'https://www.flipkart.com',
            'facebook': 'https://www.facebook.com',
            'instagram': 'https://www.instagram.com',
            'twitter': 'https://www.twitter.com',
            'whatsapp': 'https://web.whatsapp.com',
            'gmail': 'https://mail.google.com',
            'youtube': 'https://www.youtube.com',
            'google': 'https://www.google.com'
        }
        
        query_lower = query.lower()
        
        # Check for specific song requests with Spotify
        if 'spotify' in query_lower and ('play' in query_lower or 'song' in query_lower):
            song_match = re.search(r'play\s+(.+?)(?:\s+on\s+spotify|$)', query, re.IGNORECASE)
            if song_match:
                song_name = song_match.group(1).strip()
                
                # Try to get specific song URL from Tavily if available
                if self.tavily_api_key:
                    print(f"   🔄 Searching for song on Spotify via Tavily...")
                    song_result = await self._search_song_on_spotify(song_name)
                    if song_result:
                        print(f"   ✅ Found direct Spotify track")
                        return song_result
                
                # Fallback to Spotify search
                spotify_search_url = f"https://open.spotify.com/search/{urllib.parse.quote_plus(song_name)}"
                print(f"   ✅ Generated Spotify search URL for: {song_name}")
                return {
                    "type": "open",
                    "text": f"Playing '{song_name}' on Spotify. Click to listen.",
                    "url": spotify_search_url,
                    "metadata": {"site": "spotify", "song": song_name}
                }
        
        # Regular website opening
        for site, url in website_mappings.items():
            if site in query_lower:
                print(f"   ✅ Opening {site.title()}")
                return {
                    "type": "open",
                    "text": f"Opening {site.title()}. Click the link below.",
                    "url": url,
                    "metadata": {"site": site}
                }
        
        print(f"   ⚠️  Website not specified or not found")
        return {
            "type": "open",
            "text": "Please specify which app/website to open (e.g., 'open spotify').",
            "url": None,
            "metadata": {"error": "site_not_specified"}
        }

    async def _search_song_on_spotify(self, song_name: str) -> Optional[Dict]:
        """Search for specific song URL using Tavily"""
        try:
            if not self.tavily_api_key:
                return None
            search_query = f"spotify {song_name} track url"
            result = await self._tavily_search(search_query)
            
            if result and result.get('url') and 'spotify.com/track/' in result['url']:
                return {
                    "type": "open",
                    "text": f"Found '{song_name}' on Spotify. Click to play directly.",
                    "url": result['url'],
                    "metadata": {"site": "spotify", "song": song_name, "direct_track": True}
                }
        except:
            pass
        
        return None
