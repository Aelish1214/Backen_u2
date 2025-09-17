from .query_processor import QueryProcessor
from .tts_engine import TTSEngine
from .speech_recognizer import SpeechRecognizer
from dotenv import load_dotenv
import os
import asyncio
from typing import Dict, Optional

load_dotenv()

class AIAssistant:
    def __init__(self):
        self.groq_key = os.getenv("GROQ_API_KEY")
        self.cohere_key = os.getenv("COHERE_API_KEY")
        self.assistant_name = os.getenv("Assistantname", "INAI")
        self.query_processor = QueryProcessor(self.groq_key, self.cohere_key)
        self.tts_engine = TTSEngine()
        self.speech_recognizer = SpeechRecognizer()

    # def process_query(self, query):
    #     if not query.strip():
    #         return "Please enter a valid query."
    #     intent, corrected_query, destination = self.query_processor.detect_intent_and_locations(query)
    #     if intent == "distance":
    #         return self.query_processor._get_google_maps_link(corrected_query, destination)
    #     if intent == "youtube":
    #         return self.query_processor.generate_media_response(corrected_query)
    #     if intent == "realtime":
    #         return self.query_processor.generate_realtime_response(corrected_query)
    #     if intent == "exit":
    #         return "Goodbye!"
    #     return self.query_processor.generate_general_response(corrected_query)

    # def run(self):
    #     print(f"🤖 {self.assistant_name} Starting...")
    #     welcome_msg = f"Hello! I'm {self.assistant_name}. How can I help you?"
    #     print(f"🤖 {self.assistant_name}: {welcome_msg}")
    #     self.tts_engine.speak_text(welcome_msg)
    #     while True:
    #         try:
    #             user_input, input_type = self.speech_recognizer.listen_for_voice()
    #             if input_type == "quit" or user_input.lower() in ['quit', 'exit', 'bye']:
    #                 goodbye_msg = "Goodbye!"
    #                 print(f"🤖 {self.assistant_name}: {goodbye_msg}")
    #                 self.tts_engine.speak_text(goodbye_msg)
    #                 break
    #             input_icon = "🎤" if input_type == "voice" else "💬"
    #             print(f"\n{input_icon} You: {user_input}")
    #             print("⏳ Processing...")
    #             response = self.query_processor.process_query(user_input)
    #             print(f"🤖 {self.assistant_name}: {response}")
    #             self.tts_engine.speak_text(response)
    #         except KeyboardInterrupt:
    #             goodbye_msg = "Goodbye!"
    #             print(f"\n👋 {self.assistant_name}: {goodbye_msg}")
    #             self.tts_engine.speak_text(goodbye_msg)
    #             break
    #         except Exception as e:
    #             error_msg = "Sorry, I encountered an error."
    #             print(f"❌ Error: {e}")
    #             self.tts_engine.speak_text(error_msg)
    
    def process_query(self, query: str, user_id: str = None) -> Dict:
        """Process user query and return appropriate response"""
        try:
            # Run async method in sync context
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            result = loop.run_until_complete(self.query_processor.process_query(query))
            loop.close()
            return result
        except Exception as e:
            return {
                "type": "error",
                "text": f"Assistant error: {str(e)}",
                "url": None
            }
    
    async def process_query_async(self, query: str, user_id: str = None) -> Dict:
        """Async version of process_query"""
        return await self.query_processor.process_query(query)
    
    def get_response_text(self, result: Dict) -> str:
        """Extract text response from result"""
        return result.get('text', 'Sorry, I could not process your request.')
    
    def get_response_url(self, result: Dict) -> Optional[str]:
        """Extract URL from result"""
        return result.get('url')
    
    def format_response_for_frontend(self, result: Dict) -> Dict:
        """Format response for frontend consumption"""
        return {
            "text": self.get_response_text(result),
            "url": self.get_response_url(result),
            "type": result.get("type", "general"),
            "metadata": {
                "search_terms": result.get("search_terms"),
                "origin": result.get("origin"),
                "destination": result.get("destination"),
                "site": result.get("site"),
                "all_urls": result.get("all_urls", [])
            }
        }