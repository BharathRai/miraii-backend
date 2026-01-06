"""
Elai AI Companion Router
========================

Full-featured AI wellness companion with:
- LLM-powered empathetic conversations
- Text-to-Speech options:
  1. Edge TTS (Microsoft) - Free, no API key required
  2. ElevenLabs - Premium quality (requires paid plan)
  3. Frontend fallback - Browser/Native speech synthesis
- Speech-to-Text (OpenAI Whisper)
- Health context awareness
- Agentic capabilities (SOS, breathing exercises, etc.)

Environment Variables:
- EMERGENT_LLM_KEY: Universal LLM key for GPT-4o
- ELEVEN_API_KEY: (Optional) ElevenLabs API key
- ELEVEN_VOICE_ID: (Optional) Voice ID for ElevenLabs
- TTS_PROVIDER: (Optional) 'edge', 'elevenlabs', or 'none' (default: 'edge')
- EDGE_VOICE: (Optional) Edge TTS voice (default: 'en-US-JennyNeural')
"""

from fastapi import APIRouter, Form, UploadFile, File, HTTPException, Depends, BackgroundTasks
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
import os
import uuid
import json
import tempfile
import logging
from datetime import datetime, timezone

# Import the Elai agent service
try:
    from services.elai_agent import (
        elai_text_chat,
        elai_voice_chat,
        elai_get_audio_response,
        handle_action,
        get_conversation_history,
        clear_conversation,
        is_service_available
    )
    ELAI_SERVICE_AVAILABLE = True
except ImportError as e:
    ELAI_SERVICE_AVAILABLE = False
    logging.warning(f"Elai service import failed: {e}")

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/elai", tags=["Elai AI Companion"])

# ============================================================
# Request/Response Models
# ============================================================

class ChatRequest(BaseModel):
    conversation_id: Optional[str] = None
    message: str
    metrics_context: Optional[Dict[str, Any]] = None
    user_name: Optional[str] = None

class ChatResponse(BaseModel):
    reply: str
    conversation_id: str
    actions: Optional[List[Dict]] = None
    tts_available: bool = False
    metadata: Optional[Dict] = None

class VoiceResponse(BaseModel):
    transcript: str
    reply: str
    conversation_id: str
    audio_url: Optional[str] = None
    actions: Optional[List[Dict]] = None
    tts_available: bool = False

class TTSRequest(BaseModel):
    text: str

class ActionRequest(BaseModel):
    action_type: str
    action_data: Optional[str] = None
    session_id: str

# ============================================================
# Health Check
# ============================================================

@router.get("/")
async def elai_health():
    """Health check for Elai service"""
    if ELAI_SERVICE_AVAILABLE:
        services = is_service_available()
        return {
            "status": "ok",
            "service": "elai-ai-companion",
            "mode": "production",
            "capabilities": {
                "text_chat": services.get("llm_available", False),
                "voice_input": services.get("stt_available", False),
                "voice_output": services.get("tts_available", False),
                "health_context": True,
                "agentic_actions": True
            }
        }
    else:
        return {
            "status": "degraded",
            "service": "elai-ai-companion",
            "mode": "mock",
            "message": "Elai service not available, using fallback responses"
        }

@router.get("/status")
async def elai_status():
    """Detailed status of Elai services"""
    if ELAI_SERVICE_AVAILABLE:
        return is_service_available()
    return {
        "llm_available": False,
        "tts_available": False,
        "stt_available": False
    }

# ============================================================
# Text Chat Endpoint
# ============================================================

@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """
    Send a text message to Elai and get a response.
    
    - conversation_id: Optional. Creates new conversation if not provided.
    - message: The user's message
    - metrics_context: Optional health metrics from ring for context-aware responses
    - user_name: Optional user's name for personalization
    """
    conversation_id = request.conversation_id or f"conv_{uuid.uuid4().hex[:12]}"
    
    if ELAI_SERVICE_AVAILABLE:
        try:
            result = await elai_text_chat(
                message=request.message,
                session_id=conversation_id,
                health_context=request.metrics_context,
                user_name=request.user_name
            )
            
            return ChatResponse(
                reply=result["reply"],
                conversation_id=conversation_id,
                actions=result.get("actions", []),
                tts_available=result.get("tts_available", False),
                metadata={
                    "model": "gpt-4o",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "has_health_context": bool(request.metrics_context)
                }
            )
        except Exception as e:
            logger.error(f"Elai chat error: {e}")
            # Fall through to mock response
    
    # Fallback mock response
    mock_reply = get_fallback_response(request.message, request.metrics_context)
    return ChatResponse(
        reply=mock_reply,
        conversation_id=conversation_id,
        actions=[],
        tts_available=False,
        metadata={
            "model": "fallback",
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    )

# ============================================================
# Voice Chat Endpoint
# ============================================================

@router.post("/voice")
async def voice_chat(
    conversation_id: str = Form(None),
    audio: UploadFile = File(...),
    metrics_context: str = Form(None),
    user_name: str = Form(None)
):
    """
    Send voice message to Elai and get response (with optional audio).
    
    - conversation_id: Optional conversation ID
    - audio: Audio file (wav, mp3, webm, etc.)
    - metrics_context: Optional JSON string with health metrics
    - user_name: Optional user's name
    """
    conversation_id = conversation_id or f"conv_{uuid.uuid4().hex[:12]}"
    
    # Parse metrics context
    metrics = None
    if metrics_context:
        try:
            metrics = json.loads(metrics_context)
        except:
            pass
    
    # Save uploaded audio temporarily
    temp_audio_path = None
    try:
        suffix = os.path.splitext(audio.filename or "audio.wav")[1] or ".wav"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            content = await audio.read()
            tmp.write(content)
            temp_audio_path = tmp.name
        
        if ELAI_SERVICE_AVAILABLE:
            try:
                result = await elai_voice_chat(
                    audio_path=temp_audio_path,
                    session_id=conversation_id,
                    health_context=metrics,
                    user_name=user_name
                )
                
                return JSONResponse({
                    "conversation_id": conversation_id,
                    "transcript": result.get("transcript", ""),
                    "reply": result["reply"],
                    "audio_url": None,  # Audio served via /tts endpoint
                    "has_audio": result.get("tts_available", False),
                    "actions": result.get("actions", []),
                    "metadata": {
                        "model": "gpt-4o",
                        "stt_model": "whisper-1",
                        "timestamp": datetime.now(timezone.utc).isoformat()
                    }
                })
            except Exception as e:
                logger.error(f"Elai voice chat error: {e}")
        
        # Fallback response
        return JSONResponse({
            "conversation_id": conversation_id,
            "transcript": "[Voice input received]",
            "reply": "I received your voice message. I'm here to listen whenever you're ready to share.",
            "audio_url": None,
            "has_audio": False,
            "actions": [],
            "metadata": {
                "model": "fallback",
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
        })
        
    finally:
        # Cleanup temp file
        if temp_audio_path and os.path.exists(temp_audio_path):
            try:
                os.unlink(temp_audio_path)
            except:
                pass

# ============================================================
# Text-to-Speech Endpoint
# ============================================================

@router.post("/tts")
async def text_to_speech_endpoint(request: TTSRequest):
    """
    Convert text to speech using configured TTS provider.
    
    Supports multiple providers:
    - Edge TTS (Microsoft): Free, high quality, no API key required
    - ElevenLabs: Premium quality (requires paid plan)
    
    Returns audio file (MP3) or error if TTS unavailable.
    """
    if not ELAI_SERVICE_AVAILABLE:
        raise HTTPException(status_code=503, detail="TTS service unavailable")
    
    try:
        audio_path = await elai_get_audio_response(request.text)
        
        if audio_path and os.path.exists(audio_path):
            return FileResponse(
                audio_path,
                media_type="audio/mpeg",
                filename="elai_response.mp3"
            )
        else:
            return JSONResponse({
                "status": "tts_unavailable",
                "message": "Voice synthesis not available. Please use browser speech synthesis.",
                "text": request.text
            }, status_code=200)
            
    except Exception as e:
        logger.error(f"TTS error: {e}")
        return JSONResponse({
            "status": "error",
            "message": str(e),
            "text": request.text
        }, status_code=200)

# ============================================================
# Action Execution Endpoint
# ============================================================

@router.post("/action")
async def execute_action(request: ActionRequest, background_tasks: BackgroundTasks):
    """
    Execute an Elai action (SOS, breathing exercise, etc.)
    """
    if not ELAI_SERVICE_AVAILABLE:
        raise HTTPException(status_code=503, detail="Action service unavailable")
    
    try:
        action = {
            "type": request.action_type,
            "data": request.action_data
        }
        
        result = await handle_action(action, request.session_id)
        return result
        
    except Exception as e:
        logger.error(f"Action execution error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================
# Conversation History Endpoints
# ============================================================

@router.get("/conversations/{conversation_id}")
async def get_conversation(conversation_id: str):
    """Get conversation history for a session"""
    if ELAI_SERVICE_AVAILABLE:
        messages = get_conversation_history(conversation_id)
        return {
            "conversation_id": conversation_id,
            "messages": messages,
            "message_count": len(messages)
        }
    
    return {
        "conversation_id": conversation_id,
        "messages": [],
        "message_count": 0
    }

@router.delete("/conversations/{conversation_id}")
async def delete_conversation(conversation_id: str):
    """Clear conversation history for a session"""
    if ELAI_SERVICE_AVAILABLE:
        clear_conversation(conversation_id)
    
    return {"status": "cleared", "conversation_id": conversation_id}

@router.get("/conversations")
async def list_conversations(limit: int = 20):
    """List recent conversations (placeholder - needs database integration)"""
    return {
        "conversations": [],
        "total": 0,
        "note": "Full conversation history requires database integration"
    }

# ============================================================
# Breathing Exercise Endpoint
# ============================================================

@router.get("/exercises/breathing")
async def get_breathing_exercise(exercise_type: str = "4-7-8"):
    """
    Get breathing exercise instructions.
    
    Types: 4-7-8, box, calming, energizing
    """
    exercises = {
        "4-7-8": {
            "name": "4-7-8 Relaxation Breath",
            "description": "A calming technique to reduce anxiety",
            "steps": [
                {"action": "inhale", "duration": 4, "instruction": "Breathe in quietly through your nose"},
                {"action": "hold", "duration": 7, "instruction": "Hold your breath"},
                {"action": "exhale", "duration": 8, "instruction": "Exhale completely through your mouth"},
            ],
            "cycles": 4,
            "total_duration_seconds": 76
        },
        "box": {
            "name": "Box Breathing",
            "description": "Used by Navy SEALs to stay calm",
            "steps": [
                {"action": "inhale", "duration": 4, "instruction": "Breathe in slowly"},
                {"action": "hold", "duration": 4, "instruction": "Hold your breath"},
                {"action": "exhale", "duration": 4, "instruction": "Breathe out slowly"},
                {"action": "hold", "duration": 4, "instruction": "Hold empty lungs"},
            ],
            "cycles": 4,
            "total_duration_seconds": 64
        },
        "calming": {
            "name": "Calming Breath",
            "description": "Simple technique to slow down",
            "steps": [
                {"action": "inhale", "duration": 4, "instruction": "Breathe in gently"},
                {"action": "exhale", "duration": 6, "instruction": "Breathe out slowly"},
            ],
            "cycles": 6,
            "total_duration_seconds": 60
        }
    }
    
    exercise = exercises.get(exercise_type, exercises["4-7-8"])
    return exercise

# ============================================================
# Fallback Response Generator
# ============================================================

def get_fallback_response(message: str, metrics_context: Dict = None) -> str:
    """Generate contextual fallback response when LLM is unavailable"""
    msg_lower = message.lower()
    
    # Emergency keywords
    if any(word in msg_lower for word in ['emergency', 'help me', 'dying', 'chest pain', 'cant breathe']):
        return "I hear that you're in distress. Your safety is most important. Please call emergency services (911) immediately if you're having a medical emergency. I'm here with you."
    
    # Anxiety/stress keywords
    if any(word in msg_lower for word in ['anxious', 'stressed', 'worried', 'panic', 'overwhelmed']):
        return "I can sense you're feeling overwhelmed right now, and that's completely okay. Let's take a moment together. Try taking three slow, deep breaths with me. Inhale for 4 counts, hold for 4, exhale for 6."
    
    # Sleep keywords
    if any(word in msg_lower for word in ['sleep', 'tired', 'exhausted', 'insomnia', 'cant sleep']):
        return "Rest is so important for your wellbeing, and I understand how frustrating sleep troubles can be. Your body needs time to recover. Would you like to try a gentle relaxation exercise before bed?"
    
    # Heart/health keywords
    if any(word in msg_lower for word in ['heart', 'pulse', 'bpm', 'racing']):
        if metrics_context and metrics_context.get('hr', 0) > 100:
            return f"I notice your heart rate is at {metrics_context.get('hr')} bpm, which is a bit elevated. Let's try to calm down together. Find a comfortable position and take some slow breaths."
        return "I'm keeping an eye on your heart metrics through your ring. How are you feeling right now? If you're experiencing any discomfort, please let me know."
    
    # Oxygen keywords
    if any(word in msg_lower for word in ['oxygen', 'breathing', 'spo2', 'breath']):
        return "Your breathing and oxygen levels are something I monitor closely through your ring. Deep, slow breathing can help maintain good levels. Would you like to try a breathing exercise together?"
    
    # Greeting
    if any(word in msg_lower for word in ['hello', 'hi', 'hey', 'good morning', 'good evening']):
        return "Hello! I'm here with you. How are you feeling today? I'm always ready to listen, whether you want to talk about your health, your day, or just need some company."
    
    # Default empathetic response
    return "I hear you, and I appreciate you sharing that with me. I'm here whenever you need to talk. Is there anything specific on your mind that you'd like to explore together?"
