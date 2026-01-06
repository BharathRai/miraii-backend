
import asyncio
import httpx
import os
from dotenv import load_dotenv

load_dotenv()
KEY = os.getenv("EMERGENT_LLM_KEY")

URLS = [
    "https://api.emergent.sh/v1/chat/completions",
    "https://api.emergentagent.com/v1/chat/completions",
    "https://gateway.emergent.sh/v1/chat/completions",
    "https://voicefix-8.emergent.sh/v1/chat/completions",
    "https://voicefix-8.emergentagent.com/v1/chat/completions",
    "https://voicefix-8.emergent.ai/v1/chat/completions",
    "https://api.emergent.sh/voicefix-8/v1/chat/completions",
]

async def probe():
    print(f"Probing with key: {KEY[:8]}...")
    
    headers = {
        "Authorization": f"Bearer {KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "gpt-4o",
        "messages": [{"role": "user", "content": "hi"}],
        "max_tokens": 5
    }
    
    async with httpx.AsyncClient() as client:
        for url in URLS:
            print(f"Trying {url}...")
            try:
                resp = await client.post(url, headers=headers, json=payload, timeout=5.0)
                print(f"  Result: {resp.status_code}")
                if resp.status_code == 200:
                    print(f"  SUCCESS! Response: {resp.text}")
                    return url
                elif resp.status_code != 404 and resp.status_code != 502:
                     print(f"  Interesting error: {resp.status_code} - {resp.text[:100]}")
            except Exception as e:
                print(f"  Error: {e}")

if __name__ == "__main__":
    asyncio.run(probe())
