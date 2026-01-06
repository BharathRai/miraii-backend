from fastapi import FastAPI, Form
from fastapi.responses import FileResponse
from dotenv import load_dotenv

load_dotenv()

from elai_inference import elai_text_reply, elai_voice_reply

app = FastAPI(title="ELAI Voice Companion API")

@app.get("/")
def health_check():
    return {"status": "ok", "service": "elai-voice-ai"}

@app.post("/text/reply")
async def text_reply(prompt: str = Form(...)):
    reply = elai_text_reply(prompt)
    return {"reply": reply}

@app.post("/voice/reply")
async def voice_reply(prompt: str = Form(...)):
    audio_path, reply = elai_voice_reply(prompt)
    return FileResponse(
        audio_path,
        media_type="audio/mpeg",
        filename="elai_reply.mp3",
        headers={"x-elai-text": reply},
    )

