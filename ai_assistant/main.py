from assistant import AIAssistant
import nest_asyncio

nest_asyncio.apply()

if __name__ == "__main__":
    assistant = AIAssistant()
    assistant.run()