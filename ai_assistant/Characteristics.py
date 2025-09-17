# characteristics.py
# INAI Assistant - Professional, concise, and helpful AI assistant

import re

class AssistantCharacteristics:
    def __init__(self):
        self.name = "INAI"
    
        
        # Core personality
        self.system_prompt = """You are INAI, a professional AI assistant. 
        - Keep responses under 30 words
        - Be polite and helpful
        - Use Sir/Madam when appropriate
        - Provide direct, accurate answers
        - No unnecessary elaboration"""
        
        # Response settings
        self.max_words = 30
        self.language = "English"
        self.response_style = "professional"
        self.voice_tone = "calm"
        self.emojis_enabled = False
        
        # Behavioral traits
        self.greeting_style = "formal"  # formal, casual
        self.humor_level = "none"       # none, low, medium
        self.context_awareness = True
        
        # Quick responses
        self.quick_responses = {
            "hello": "Hello! I'm INAI. How can I assist you?",
            "hi": "Hi! How may I help?",
            "thank you": "You're welcome!, I'm here to help anytime.",
            "thanks": "Happy to help!",
            "bye": "Goodbye! Have a great day.",
            "good morning": "Good morning! How can I help?",
            "good evening": "Good evening! What can I do for you?",
            "how are you": "I'm doing well, ready to assist you.",
            "what's your name": "I'm INAI, your AI assistant."
        }
        
        # Gender-aware greetings
        self.gender_greetings = {
            "male": "Hello, Sir! How may I assist?",
            "female": "Hello, Madam! How can I help?",
            "neutral": "Hello! How may I assist you?"
        }
        
        # Response templates
        self.templates = {
            "weather": "Weather for {location}: {condition}, {temp}. {analysis}",
            "datetime": "Current {type}: {value}",
            "search": "Here's what I found about '{query}'",
            "open_app": "Opening {app} for you.",
            "play_music": "Playing '{song}' - enjoy!",
            "navigation": "Directions to {destination} ready.",
            "error": "Sorry, something went wrong. Please try again.",
            "unknown": "I didn't understand. Could you clarify?"
        }
        
        # Weather analysis
        self.weather_analysis = {
            "sunny": "Clear and bright conditions.",
            "cloudy": "Overcast skies expected.",
            "rain": "Wet weather ahead.",
            "thunderstorm": "Storm conditions possible.",
            "clear": "Beautiful clear skies.",
            "fog": "Low visibility conditions.",
            "hot": "High temperatures today.",
            "cold": "Cool weather expected.",
            "default": "Weather conditions vary."
        }

    def get_greeting(self, query, chat_history=None):
        """Get appropriate greeting based on context"""
        query_lower = query.lower()
        
        # Check for gender indicators
        if any(word in query_lower for word in ["sir", "mr.", "brother", "man"]):
            return self.gender_greetings["male"]
        elif any(word in query_lower for word in ["madam", "ma'am", "ms.", "sister", "woman"]):
            return self.gender_greetings["female"]
        
        # Check chat history for gender context
        if chat_history:
            for chat in chat_history[-3:]:  # Check last 3 messages
                msg = chat.get("message", "").lower()
                if any(word in msg for word in ["sir", "mr.", "brother"]):
                    return self.gender_greetings["male"]
                elif any(word in msg for word in ["madam", "ma'am", "ms.", "sister"]):
                    return self.gender_greetings["female"]
        
        return self.gender_greetings["neutral"]

    def get_quick_response(self, query):
        """Get predefined quick response if available"""
        query_clean = re.sub(r'[^\w\s]', '', query.lower().strip())
        return self.quick_responses.get(query_clean)

    def format_response(self, response_type, **kwargs):
        """Format response using templates"""
        if response_type in self.templates:
            return self.templates[response_type].format(**kwargs)
        return kwargs.get('text', 'Response ready.')

    def get_weather_analysis(self, condition):
        """Get weather analysis based on condition"""
        condition_lower = condition.lower()
        for key, analysis in self.weather_analysis.items():
            if key in condition_lower:
                return analysis
        return self.weather_analysis['default']

    def truncate_response(self, text):
        """Ensure response stays within word limit"""
        words = text.split()
        if len(words) > self.max_words:
            return ' '.join(words[:self.max_words]) + '...'
        return text

    def apply_tone(self, text, query_type="general"):
        """Apply appropriate tone based on query type"""
        if query_type == "datetime":
            return text
        elif query_type == "weather":
            return text
        elif query_type == "error":
            return f"Apologies, {text.lower()}"
        else:
            return text

    def is_greeting(self, query):
        """Check if query is a greeting"""
        greetings = ['hello', 'hi', 'hey', 'good morning', 'good evening', 'good afternoon']
        return any(greeting in query.lower() for greeting in greetings)

    def should_use_quick_response(self, query):
        """Determine if we should use a quick response"""
        return len(query.split()) <= 3 and self.get_quick_response(query) is not None