
import httpx
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

class UserMessage:
    def __init__(self, text: str):
        self.text = text

class LlmChat:
    def __init__(self, api_key: str, session_id: str = None, system_message: str = None):
        self.api_key = api_key
        self.session_id = session_id
        self.system_message = system_message
        self.provider = "openai"  # default
        self.model = "gpt-4o"
        self.base_url = None

    def with_model(self, provider: str, model: str):
        self.provider = provider
        self.model = model
        return self

    async def send_message(self, user_msg: UserMessage) -> str:
        """
        Sends message to the configured LLM API using direct httpx to bypass missing library.
        Attempts to detect if the key is OpenAI or Emergent proxy.
        """
        try:
            import os
            custom_url = os.getenv("EMERGENT_BACKEND_URL")
            
            # Determine Endpoint
            if custom_url and custom_url.startswith("http"):
                 # User provided explicit backend
                 url = custom_url
            elif self.api_key.startswith("sk-proj") or self.api_key.startswith("sk-svc") or self.api_key.startswith("sk-"):
                 # Direct OpenAI (Standard)
                 url = "https://api.openai.com/v1/chat/completions"
            else:
                 # Fallback
                 url = "https://api.openai.com/v1/chat/completions"
                 
            # Construct Messages
            messages = []
            if self.system_message:
                messages.append({"role": "system", "content": self.system_message})
            
            messages.append({"role": "user", "content": user_msg.text})
            
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }
            
            # Payload optimization
            if "openai.com" in url:
                body = {
                    "model": self.model,
                    "messages": messages,
                    "temperature": 0.7,
                    "max_tokens": 500
                }
            else:
                # Custom backend likely expects simple text
                body = {"text": user_msg.text}

            logger.info(f"Using LlmChat shim with URL: {url}...")
            
            async with httpx.AsyncClient() as client:
                response = await client.post(url, headers=headers, json=body, timeout=40.0)
                
                if response.status_code == 200:
                    data = response.json()
                    # Handle OpenAI format
                    if "choices" in data:
                        return data['choices'][0]['message']['content']
                    # Handle Custom format
                    return data.get('reply') or data.get('text') or str(data)
                elif response.status_code == 404:
                     # Try fallback URL if 404
                     fallback_url = "https://api.emergent.sh/v1/chat/completions"
                     logger.warning(f"404 on {url}, retrying {fallback_url}")
                     response = await client.post(fallback_url, headers=headers, json=body, timeout=40.0)
                     if response.status_code == 200:
                         data = response.json()
                         return data['choices'][0]['message']['content']
                
                logger.error(f"LlmChat Error: {response.status_code} - {response.text}")
                # Return None to trigger fallback mechanism in agent
                return None
                
        except Exception as e:
            logger.error(f"LlmChat Exception: {e}")
            # Return None to trigger fallback mechanism in agent
            return None
