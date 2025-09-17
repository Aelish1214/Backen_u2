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

load_dotenv()

class QueryProcessor:
    def __init__(self, groq_key: Optional[str] = None, cohere_key: Optional[str] = None):
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
            r'\b(breaking|urgent|alert|emergency)\b',  # High priority breaking news
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
                r'\b(play|watch|youtube)\b.*\b(video|song|music)\b(?!.*spotify)',  # Exclude if spotify mentioned
                r'\b(show me|find)\b.*\b(video|song|music)\b(?!.*spotify)',
                r'\b(listen to|watch)\b.*\b(song|video)\b(?!.*spotify)'
            ],
            'maps': [
                r'\b(navigate|directions|route|go to|how to reach)\b',
                r'\b(location of|where is|find place)\b',
                r'\b(distance.*between|nearest)\b',
                r'\b(way to|path to)\b.*\b(place|location|city)\b'
            ]
        }

        self.user_agents = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        ]

        # Language translations for common terms
        self.lang_translations = {
            'hi': {'खोल': 'open', 'चला': 'play', 'समाचार': 'news', 'आज': 'today', 'समय': 'time'},
            'gu': {'ખોલ': 'open', 'ચલાવ': 'play', 'સમાચાર': 'news', 'આજ': 'today', 'સમય': 'time'},
            'bn': {'খোল': 'open', 'চালা': 'play', 'সংবাদ': 'news', 'আজ': 'today', 'সময়': 'time'}
        }

    def detect_and_correct_query(self, query: str) -> Tuple[str, str]:
        """Detect language, correct spelling/grammar and normalize query"""
        try:
            # Detect language
            lang = detect(query)
            query_lower = query.lower()
            
            # Basic translation for common terms
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
            }
            
            for pattern, replacement in corrections.items():
                query_lower = re.sub(pattern, replacement, query_lower, flags=re.IGNORECASE)
            
            return query_lower.strip(), lang
            
        except LangDetectException:
            return query.lower().strip(), 'en'

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

    def classify_query(self, query: str) -> Tuple[str, str, str]:
        """Enhanced query classification with language detection"""
        corrected_query, detected_lang = self.detect_and_correct_query(query)
        
        print(f"🔍 QUERY CLASSIFICATION:")
        print(f"   Original: {query}")
        print(f"   Corrected: {corrected_query}")
        print(f"   Language: {detected_lang}")
        
        # DateTime first - but exclude news patterns
        for pattern in self.datetime_patterns:
            if re.search(pattern, corrected_query, re.IGNORECASE):
                if not any(re.search(news_pattern, corrected_query, re.IGNORECASE) for news_pattern in self.realtime_patterns):
                    print(f"   ✅ Type: DATETIME")
                    return f"datetime {corrected_query}", detected_lang, "datetime"
        
        # Check for Spotify specifically
        if self.is_spotify_query(corrected_query):
            print(f"   ✅ Type: SPOTIFY")
            return f"open {corrected_query}", detected_lang, "open"
        
        # URL patterns (higher priority)
        for category, patterns in self.url_patterns.items():
            for pattern in patterns:
                if re.search(pattern, corrected_query, re.IGNORECASE):
                    print(f"   ✅ Type: {category.upper()}")
                    return f"{category} {corrected_query}", detected_lang, category
        
        # Realtime patterns
        for pattern in self.realtime_patterns:
            if re.search(pattern, corrected_query, re.IGNORECASE):
                print(f"   ✅ Type: REAL-TIME")
                return f"realtime {corrected_query}", detected_lang, "realtime"
        
        print(f"   ✅ Type: GENERAL")
        return f"general {corrected_query}", detected_lang, "general"

    async def process_query(self, user_query: str) -> Dict:
        """Main processing logic with enhanced debugging"""
        classification, detected_lang, query_type = self.classify_query(user_query)
        actual_query = classification.split(' ', 1)[1]
        
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
            if query_type == "general":
                return await handler(actual_query, detected_lang)
            else:
                return await handler(actual_query)
        else:
            return handler(actual_query)

    def handle_datetime_query(self, query: str) -> Dict:
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

    async def handle_general_query(self, query: str, detected_lang: str = 'en') -> Dict:
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
        """Tavily API search - Response with NO URL and clean formatting"""
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
                        
                        # Check if there's a direct answer first
                        if data.get('answer'):
                            clean_answer = str(data['answer']).strip()
                            # Remove JSON-like formatting if present
                            if clean_answer.startswith('{') or clean_answer.startswith('['):
                                clean_answer = "Weather information available - check the search results for details."
                            
                            return {
                                "type": "realtime",
                                "text": clean_answer,
                                "url": None,
                                "metadata": {"source": "tavily", "search_method": "tavily_answer"}
                            }
                        
                        # Fallback to first result content
                        if data.get('results'):
                            first_result = data['results'][0]
                            content = first_result.get('content', '')
                            
                            # Clean up content - remove JSON formatting
                            if content.startswith('{') or content.startswith('[') or 'location' in content.lower():
                                # For weather queries, provide a cleaner response
                                if any(word in query.lower() for word in ['weather', 'temperature', 'climate']):
                                    content = f"Current weather information for {query}. Check weather apps for detailed forecast."
                                else:
                                    content = content[:300] if len(content) > 300 else content
                            
                            return {
                                "type": "realtime",
                                "text": f"Latest information: {content}",
                                "url": None,
                                "metadata": {"source": "tavily", "title": first_result.get('title'), "search_method": "tavily"}
                            }
        except Exception as e:
            print(f"   ❌ Tavily search error: {e}")
        
        return None

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
        
        search_terms = re.sub(r'\b(play|watch|youtube|video|song|music|show me|find|listen to)\b', '', query, flags=re.IGNORECASE).strip()
        
        if not search_terms:
            search_terms = "popular music"
        
        youtube_url = f"https://www.youtube.com/results?search_query={urllib.parse.quote_plus(search_terms)}"
        
        print(f"   ✅ Generated YouTube URL for: {search_terms}")
        return {
            "type": "youtube",
            "text": f"Playing '{search_terms}' on YouTube. Click to watch/listen.",
            "url": youtube_url,
            "metadata": {"search_terms": search_terms}
        }

    async def handle_maps_query(self, query: str) -> Dict:
        """Handle maps queries"""
        print(f"🗺️  MAPS HANDLER:")
        
        patterns = [
            r'(?:navigate|directions|route|go)\s+to\s+(.+?)(?:\s*[.,]|$)',
            r'(?:how to reach|way to|path to)\s+(.+?)(?:\s*[.,]|$)',
            r'(?:location of|where is|find)\s+(.+?)(?:\s*[.,]|$)',
        ]
        
        destination = None
        for pattern in patterns:
            match = re.search(pattern, query, re.IGNORECASE)
            if match:
                destination = match.group(1).strip()
                break
        
        if destination:
            maps_url = f"https://www.google.com/maps/dir/Current+Location/{urllib.parse.quote_plus(destination)}"
            print(f"   ✅ Generated Maps URL for: {destination}")
            return {
                "type": "maps",
                "text": f"Directions to {destination.title()}",
                "url": maps_url,
                "metadata": {"destination": destination}
            }
        else:
            print(f"   ⚠️  Destination not found in query")
            return {
                "type": "maps",
                "text": "Specify destination (e.g., 'navigate to Mumbai')",
                "url": "https://www.google.com/maps",
                "metadata": {"error": "location_not_found"}
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