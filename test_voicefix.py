
import asyncio
import httpx

KEY = "sk-emergent-b51E086AbDfF936940"
BASE_URL = "https://voicefix-8.preview.emergentagent.com"

async def test_probe():
    print("Starting probe...")
    
    paths_to_test = [
        "/api/chat",
        "/api/v1/chat/completions"
    ]
    
    headers_strategies = [
        {"name": "Bearer", "h": {"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"}},
        {"name": "X-API-KEY", "h": {"x-api-key": KEY, "Content-Type": "application/json"}},
        {"name": "None", "h": {"Content-Type": "application/json"}}
    ]
    
    payload = {
        "messages": [{"role": "user", "content": "hi"}],
        "model": "gpt-4"
    }
    
    async with httpx.AsyncClient() as client:
        for path in paths_to_test:
            url = BASE_URL + path
            print(f"\n--- Testing {url} ---")
            
            for strat in headers_strategies:
                print(f"  Auth: {strat['name']} ... ", end="")
                try:
                    resp = await client.post(url, headers=strat['h'], json=payload, timeout=10.0)
                    print(f"Status: {resp.status_code}")
                    if resp.status_code == 200:
                        print("    SUCCESS!")
                        print(f"    Body: {resp.text[:100]}")
                        return
                    elif resp.status_code != 404:
                         print(f"    Detail: {resp.text[:100]}")
                except Exception as e:
                    print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(test_probe())
