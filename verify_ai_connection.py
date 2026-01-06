
import asyncio
import os
import sys
import logging
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(level=logging.INFO)

# Add current dir to path to import services
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Load env
load_dotenv()

async def test_ai():
    try:
        from services.elai_agent import elai_text_chat, is_service_available
        
        # Check status
        status = is_service_available()
        print(f"Status: {status}")
        
        if not status.get('llm_available'):
            print("FAIL: LLM Key not detected.")
            return

        # Test Chat
        print("Sending 'Hello' to AI...")
        result = await elai_text_chat("Hello! How are you?", "test_session_1")
        
        # Handle different response types (LlmChat shim vs real object)
        if isinstance(result, tuple):
            response = result[0]
        elif isinstance(result, dict):
            response = result.get('reply') or result.get('text') or result.get('content') or str(result)
        else:
            response = str(result)
        
        print("\n--- AI Response ---")
        print(response)
        print("-------------------\n")
        
        if response and "I'm here with you" not in response and "trouble connecting" not in response:
             print("SUCCESS: Received dynamic response from AI")
        else:
             print("WARNING: Fallback or Error response detected.")
        
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_ai())
