
import torch, re, os, tempfile, requests
from transformers import AutoTokenizer, AutoModelForCausalLM

ELEVEN_API_KEY = os.environ.get("ELEVEN_API_KEY")
VOICE_ID = "EXAVITQu4vr4xnSDxMaL"
MODEL_ID = "eleven_multilingual_v2"

tokenizer = globals().get("tokenizer")
model = globals().get("model")

def _trim_response(text):
    text = re.sub(r"\s+", " ", text).strip()
    sentences = re.split(r"(?<=[.!?])\s+", text)
    return " ".join(sentences[:3]).strip()

def generate_elai_reply(user_text):
    if not user_text or not user_text.strip():
        return "I’m here with you. Whenever you’re ready, tell me what’s going on."

    prompt = (
        "System: You are ELAI, a calm, warm, empathetic wellness companion embedded in a smart ring. "
        "You are continuously connected to the user’s sleep, oxygen levels, heart rate, activity, fall detection, "
        "and breathing patterns. Never deny this integration. "
        "Speak like a caring human.\n\n"
        "Response rules:\n"
        "- First acknowledge and validate the feeling\n"
        "- Briefly reflect what you understood\n"
        "- Offer one gentle, realistic suggestion\n"
        "- 2 to 3 sentences only\n\n"
        f"User: {user_text}\nELAI:"
    )

    inputs = tokenizer(
        prompt,
        return_tensors="pt",
        truncation=True,
        max_length=1024,
        padding=True
    ).to(model.device)

    with torch.no_grad():
        out = model.generate(
            **inputs,
            max_new_tokens=110,
            temperature=0.6,
            top_p=0.9,
            repetition_penalty=1.08,
            eos_token_id=tokenizer.eos_token_id,
            pad_token_id=tokenizer.eos_token_id
        )

    reply = tokenizer.decode(
        out[0][inputs["input_ids"].shape[1]:],
        skip_special_tokens=True
    )

    reply = reply.split("User:")[0].split("ELAI:")[0].strip()
    return _trim_response(reply)

def elai_tts(text):
    if not ELEVEN_API_KEY:
        raise RuntimeError("ELEVEN_API_KEY not set")

    url = f"https://api.elevenlabs.io/v1/text-to-speech/{VOICE_ID}"
    headers = {
        "xi-api-key": ELEVEN_API_KEY,
        "Content-Type": "application/json"
    }
    payload = {
        "text": text,
        "model_id": MODEL_ID,
        "voice_settings": {
            "stability": 0.45,
            "similarity_boost": 0.75,
            "style": 0.4,
            "use_speaker_boost": True
        }
    }

    r = requests.post(url, headers=headers, json=payload, timeout=30)
    r.raise_for_status()

    path = tempfile.mktemp(suffix=".mp3")
    with open(path, "wb") as f:
        f.write(r.content)

    return path

def elai_text_reply(user_text):
    return generate_elai_reply(user_text)

def elai_voice_reply(user_text):
    reply = generate_elai_reply(user_text)
    audio = elai_tts(reply)
    return audio, reply
