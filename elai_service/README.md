# Elai AI Companion Service

## Overview
This folder contains the Elai voice/text AI companion service.

## Files
- `main.py` - Standalone FastAPI server (for testing)
- `elai_inference.py` - Core inference functions
- `elai.py` - Training/fine-tuning notebook code
- `requirements.txt` - Python dependencies

## Integration with Main Backend

### Option 1: Import Functions Directly
In `/app/backend/routers/elai.py`, uncomment:
```python
from elai_service.elai_inference import elai_text_reply, elai_voice_reply
ELAI_AVAILABLE = True
```

### Option 2: Run as Separate Service
```bash
cd /app/backend/elai_service
pip install -r requirements.txt
uvicorn main:app --port 8002
```

Then proxy requests from the main backend.

## Required Environment Variables
```env
ELEVEN_API_KEY=your_elevenlabs_key  # For TTS
HF_TOKEN=your_huggingface_token     # For model access
```

## Model Requirements
- Uses HuggingFace zephyr-7b-beta model
- Requires GPU with ~8GB+ VRAM for inference
- Falls back to CPU (slower) if no GPU

## API Endpoints (Standalone)
- `GET /` - Health check
- `POST /text/reply` - Text-to-text response
- `POST /voice/reply` - Text-to-speech response
