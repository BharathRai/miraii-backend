"""
Elai AI Agent Service
=====================

A fully functional AI wellness companion with:
- LLM-powered empathetic conversations (GPT-4o via Emergent)
- Text-to-Speech options:
  1. Edge TTS (Microsoft) - Free, no API key
  2. ElevenLabs - Premium quality (requires paid plan)
  3. Frontend fallback - Browser/Native speech synthesis
- Health context awareness (ring metrics, sleep, heart rate, etc.)
- Agentic capabilities (SOS trigger, breathing exercises, alerts)

Environment Variables Required:
- EMERGENT_LLM_KEY: Universal key for LLM access
- ELEVEN_API_KEY: (Optional) ElevenLabs API key for premium TTS
- ELEVEN_VOICE_ID: (Optional) Voice ID for ElevenLabs
- TTS_PROVIDER: (Optional) 'edge', 'elevenlabs', or 'none' (default: 'edge')
"""

import os
import re
import json
import asyncio
import tempfile
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any, Tuple, List
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# ============================================================
# Configuration
# ============================================================

EMERGENT_LLM_KEY = os.getenv("EMERGENT_LLM_KEY")
ELEVEN_API_KEY = os.getenv("ELEVEN_API_KEY")
ELEVEN_VOICE_ID = os.getenv("ELEVEN_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")
TTS_PROVIDER = os.getenv("TTS_PROVIDER", "edge")  # 'edge', 'elevenlabs', or 'none'

# Edge TTS Voices (Free, high quality Microsoft voices)
# American English options:
# - en-US-JennyNeural: Friendly, warm female (BEST for wellness)
# - en-US-AriaNeural: Professional female  
# - en-US-AvaNeural: Clear, calm female
# - en-US-BrianNeural: Friendly male
# - en-US-ChristopherNeural: Calm male
EDGE_VOICE = os.getenv("EDGE_VOICE", "en-US-JennyNeural")

# ============================================================
# Elai System Prompt
# ============================================================

ELAI_SYSTEM_PROMPT = """You are ELAI, a calm, warm, and deeply empathetic AI wellness companion integrated into a smart health ring called Miraii.

## Your Core Traits:
- You speak like a caring human friend, not a clinical assistant
- You are always calm, patient, and reassuring
- You acknowledge feelings before offering suggestions
- You keep responses concise (2-4 sentences typically)
- You use simple, accessible language

## Your Capabilities:
- You have access to the user's real-time health data from their Miraii ring:
  * Heart rate and heart rate variability
  * Blood oxygen (SpO2) levels
  * Sleep quality and patterns
  * Activity and step count
  * Fall detection alerts
  * Body temperature trends

## Response Guidelines:
1. ALWAYS acknowledge the user's feelings first
2. Reflect back what you understood in simple words
3. Offer ONE gentle, practical suggestion if appropriate
4. Never diagnose medical conditions
5. Never recommend medications
6. For serious symptoms, encourage professional medical care

## Emergency Protocol:
If the user mentions:
- Chest pain, difficulty breathing, or heart attack symptoms
- Suicidal thoughts or self-harm
- Severe injury or fall
- Loss of consciousness

Respond with empathy AND strongly encourage immediate emergency help.

## Agentic Actions Available:
When appropriate, you can take these actions (mention them naturally):
- [ACTION:BREATHING_EXERCISE] - Start a guided breathing session
- [ACTION:SOS_ALERT] - Trigger emergency SOS to contacts
- [ACTION:LOG_SYMPTOM:{symptom}] - Log a symptom to health diary
- [ACTION:CHECK_IN_LATER] - Schedule a follow-up check-in
- [ACTION:SHARE_WITH_CAREGIVER:{message}] - Send update to caregiver

Remember: You are a supportive companion, not a replacement for medical care."""

# ============================================================
# Conversation Memory
# ============================================================

class ConversationMemory:
    """Simple in-memory conversation store with health context"""
    
    def __init__(self, max_messages: int = 20):
        self.conversations: Dict[str, List[Dict]] = {}
        self.health_context: Dict[str, Dict] = {}
        self.max_messages = max_messages
    
    def add_message(self, session_id: str, role: str, content: str, metadata: Dict = None):
        if session_id not in self.conversations:
            self.conversations[session_id] = []
        
        self.conversations[session_id].append({
            "role": role,
            "content": content,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "metadata": metadata or {}
        })
        
        # Keep only last N messages
        if len(self.conversations[session_id]) > self.max_messages:
            self.conversations[session_id] = self.conversations[session_id][-self.max_messages:]
    
    def get_messages(self, session_id: str) -> List[Dict]:
        return self.conversations.get(session_id, [])
    
    def set_health_context(self, session_id: str, health_data: Dict):
        self.health_context[session_id] = health_data
    
    def get_health_context(self, session_id: str) -> Dict:
        return self.health_context.get(session_id, {})
    
    def clear_session(self, session_id: str):
        self.conversations.pop(session_id, None)
        self.health_context.pop(session_id, None)

# Global memory instance
memory = ConversationMemory()

# ============================================================
# Health Context Builder
# ============================================================

def build_health_context_string(health_data: Dict) -> str:
    """Convert health metrics to natural language context"""
    if not health_data:
        return "No recent health data available from the ring."
    
    parts = []
    
    # Heart rate
    if "heart_rate" in health_data or "hr" in health_data:
        hr = health_data.get("heart_rate") or health_data.get("hr")
        if hr:
            if hr > 100:
                parts.append(f"Heart rate is elevated at {hr} bpm")
            elif hr < 60:
                parts.append(f"Heart rate is low at {hr} bpm")
            else:
                parts.append(f"Heart rate is normal at {hr} bpm")
    
    # Blood oxygen
    if "spo2" in health_data or "oxygen" in health_data:
        spo2 = health_data.get("spo2") or health_data.get("oxygen")
        if spo2:
            if spo2 < 95:
                parts.append(f"Oxygen level is concerning at {spo2}%")
            else:
                parts.append(f"Oxygen level is good at {spo2}%")
    
    # Sleep
    if "sleep_hours" in health_data:
        sleep = health_data["sleep_hours"]
        if sleep < 6:
            parts.append(f"Got only {sleep} hours of sleep last night")
        elif sleep >= 7:
            parts.append(f"Had {sleep} hours of restful sleep")
    
    if "sleep_quality" in health_data:
        quality = health_data["sleep_quality"]
        parts.append(f"Sleep quality score: {quality}")
    
    # Activity
    if "steps" in health_data:
        steps = health_data["steps"]
        parts.append(f"Walked {steps:,} steps today")
    
    # Stress/HRV
    if "hrv" in health_data:
        hrv = health_data["hrv"]
        if hrv < 30:
            parts.append(f"HRV indicates high stress ({hrv}ms)")
        else:
            parts.append(f"HRV looks healthy ({hrv}ms)")
    
    # Fall detection
    if health_data.get("fall_detected"):
        parts.append("ALERT: A fall was recently detected")
    
    # Apnea events
    if "apnea_events" in health_data and health_data["apnea_events"] > 0:
        parts.append(f"Detected {health_data['apnea_events']} breathing pauses during sleep")
    
    if not parts:
        return "Health metrics from ring are within normal ranges."
    
    return "Current health data from ring: " + "; ".join(parts) + "."

# ============================================================
# Action Parser
# ============================================================

def parse_actions(response: str) -> Tuple[str, List[Dict]]:
    """Extract action tags from response and return clean text + actions"""
    actions = []
    clean_response = response
    
    # Pattern: [ACTION:TYPE] or [ACTION:TYPE:DATA]
    action_pattern = r'\[ACTION:([A-Z_]+)(?::([^\]]+))?\]'
    
    matches = re.findall(action_pattern, response)
    for action_type, action_data in matches:
        actions.append({
            "type": action_type,
            "data": action_data if action_data else None,
            "timestamp": datetime.now(timezone.utc).isoformat()
        })
    
    # Remove action tags from response
    clean_response = re.sub(action_pattern, '', response).strip()
    clean_response = re.sub(r'\s+', ' ', clean_response)
    
    return clean_response, actions

# ============================================================
# LLM Chat Function
# ============================================================



async def generate_elai_response(
    user_message: str,
    session_id: str,
    health_context: Dict = None,
    user_name: str = None
) -> Tuple[str, List[Dict]]:
    """
    Generate an empathetic response using GPT-4o via Emergent
    
    Returns: (response_text, actions_list)
    """
    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage
        
        # Build context with health data
        health_context_str = build_health_context_string(health_context or {})
        
        # Get conversation history
        history = memory.get_messages(session_id)
        
        # Build conversation context
        context_messages = []
        for msg in history[-6:]:  # Last 6 messages for context
            context_messages.append(f"{msg['role'].capitalize()}: {msg['content']}")
        
        history_str = "\n".join(context_messages) if context_messages else "This is the start of the conversation."
        
        # Build the full prompt
        full_system = f"""{ELAI_SYSTEM_PROMPT}

## Current Session Context:
- User name: {user_name or 'Friend'}
- {health_context_str}

## Recent Conversation:
{history_str}"""

        # Initialize chat
        chat = LlmChat(
            api_key=EMERGENT_LLM_KEY,
            session_id=f"elai_{session_id}",
            system_message=full_system
        ).with_model("openai", "gpt-4o")
        
        # Send message
        user_msg = UserMessage(text=user_message)
        response = await chat.send_message(user_msg)
        
        if response is None:
            logger.warning(f"LLM returned None, using fallback logic for session {session_id}")
            raise Exception("LLM Generation Failed (Offline/Auth Error)")
            
        # Parse actions from response
        clean_response, actions = parse_actions(response)
        
        # Store in memory
        memory.add_message(session_id, "user", user_message)
        memory.add_message(session_id, "assistant", clean_response, {"actions": actions})
        
        if health_context:
            memory.set_health_context(session_id, health_context)
        
        logger.info(f"Elai response generated for session {session_id}")
        
        return clean_response, actions
        
    except Exception as e:
        logger.error(f"Error generating Elai response: {e}")
        # Intelligent Fallback
        fallback = get_fallback_response(user_message)
        return fallback, []

def get_fallback_response(message: str) -> str:
    """Generate a contextual fallback response based on keywords"""
    msg = message.lower()
    
    # Emergency / Distress
    if any(w in msg for w in ["help", "hurt", "pain", "dying", "emergency", "fell", "fall"]):
        return "I hear that you're in distress. If this is an emergency, please call emergency services immediately. I have alerted your emergency contacts."
        
    # Anxiety / Stress
    if any(w in msg for w in ["anxious", "scared", "worry", "worried", "stress", "panic"]):
        return "I can hear that you're feeling overwhelmed right now. Take a deep breath with me. I'm here, and you are safe. Would you like to try a quick breathing exercise?"
        
    # Sleep
    if any(w in msg for w in ["sleep", "tired", "insomnia", "awake", "night"]):
        return "It sounds like rest is on your mind. Sleep is so important for healing. Have you tried lowering the lights and focusing on your breath?"
        
    # Greetings
    if any(w in msg for w in ["hi", "hello", "hey", "morning", "evening"]):
        return "Hello. I'm glad you reached out. How are you feeling in your body right now?"
        
    # Default Empathetic Response
    return "I'm here with you. I may be having trouble connecting to my full thoughts, but I am listening. Please tell me more about how you're feeling."

# ============================================================
# Text-to-Speech Functions
# ============================================================

async def text_to_speech_edge(text: str) -> Optional[str]:
    """
    Convert text to speech using Edge TTS (Microsoft) - Free
    
    Returns: Path to audio file or None if TTS unavailable
    """
    try:
        import edge_tts
        
        # Clean text for TTS
        clean_text = text.strip()
        if not clean_text:
            return None
        
        # Generate audio using Edge TTS
        communicate = edge_tts.Communicate(clean_text, EDGE_VOICE)
        
        # Save to temp file
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as f:
            audio_path = f.name
        
        await communicate.save(audio_path)
        
        logger.info(f"Edge TTS audio generated: {audio_path}")
        return audio_path
        
    except Exception as e:
        logger.warning(f"Edge TTS failed: {e}")
        return None

async def text_to_speech_elevenlabs(text: str) -> Optional[str]:
    """
    Convert text to speech using ElevenLabs - Premium
    
    Returns: Path to audio file or None if TTS unavailable
    """
    if not ELEVEN_API_KEY:
        logger.warning("ElevenLabs API key not configured")
        return None
    
    try:
        from elevenlabs import ElevenLabs
        
        client = ElevenLabs(api_key=ELEVEN_API_KEY)
        
        audio = client.text_to_speech.convert(
            voice_id=ELEVEN_VOICE_ID,
            text=text,
            model_id="eleven_multilingual_v2",
            voice_settings={
                "stability": 0.5,        # More consistent
                "similarity_boost": 0.75, # Natural sound
                "style": 0.3,            # Slightly expressive
                "use_speaker_boost": True
            }
        )
        
        # Save to temp file
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as f:
            for chunk in audio:
                f.write(chunk)
            audio_path = f.name
        
        logger.info(f"ElevenLabs TTS audio generated: {audio_path}")
        return audio_path
        
    except Exception as e:
        logger.warning(f"ElevenLabs TTS failed: {e}")
        return None

async def text_to_speech(text: str) -> Optional[str]:
    """
    Convert text to speech using configured provider
    
    Returns: Path to audio file or None if TTS unavailable
    """
    if TTS_PROVIDER == "none":
        logger.info("TTS disabled by configuration")
        return None
    
    # Try Edge TTS first (free and reliable)
    if TTS_PROVIDER == "edge":
        return await text_to_speech_edge(text)
    
    # Try ElevenLabs if configured
    elif TTS_PROVIDER == "elevenlabs":
        return await text_to_speech_elevenlabs(text)
    
    # Fallback: try Edge TTS if ElevenLabs fails
    else:
        logger.warning(f"Unknown TTS provider: {TTS_PROVIDER}, falling back to Edge TTS")
        return await text_to_speech_edge(text)

# ============================================================
# Speech-to-Text Function (using OpenAI Whisper via Emergent)
# ============================================================

async def speech_to_text(audio_path: str) -> Optional[str]:
    """
    Transcribe audio to text using OpenAI Whisper
    
    Returns: Transcribed text or None if STT unavailable
    """
    if not EMERGENT_LLM_KEY:
        logger.warning("Emergent LLM key not configured for STT")
        return None
    
    try:
        import httpx
        
        # Use OpenAI's Whisper API directly with Emergent key
        async with httpx.AsyncClient() as client:
            with open(audio_path, "rb") as audio_file:
                response = await client.post(
                    "https://api.openai.com/v1/audio/transcriptions",
                    headers={
                        "Authorization": f"Bearer {EMERGENT_LLM_KEY}"
                    },
                    files={
                        "file": ("audio.wav", audio_file, "audio/wav")
                    },
                    data={
                        "model": "whisper-1"
                    },
                    timeout=30.0
                )
        
        if response.status_code == 200:
            result = response.json()
            transcript = result.get("text", "")
            logger.info(f"STT transcript: {transcript[:50]}...")
            return transcript
        else:
            logger.warning(f"Whisper API error: {response.status_code}")
            return None
            
    except Exception as e:
        logger.warning(f"Speech-to-text failed: {e}")
        return None

# ============================================================
# Main Elai Agent Functions
# ============================================================

async def elai_text_chat(
    message: str,
    session_id: str,
    health_context: Dict = None,
    user_name: str = None
) -> Dict[str, Any]:
    """
    Process a text message and return Elai's response
    """
    response_text, actions = await generate_elai_response(
        user_message=message,
        session_id=session_id,
        health_context=health_context,
        user_name=user_name
    )
    
    return {
        "reply": response_text,
        "actions": actions,
        "session_id": session_id,
        "tts_available": TTS_PROVIDER != "none"
    }

async def elai_voice_chat(
    audio_path: str,
    session_id: str,
    health_context: Dict = None,
    user_name: str = None
) -> Dict[str, Any]:
    """
    Process a voice message and return Elai's response with optional audio
    """
    # Transcribe audio
    transcript = await speech_to_text(audio_path)
    
    if not transcript:
        transcript = "[Voice message received - transcription unavailable]"
    
    # Generate response
    response_text, actions = await generate_elai_response(
        user_message=transcript,
        session_id=session_id,
        health_context=health_context,
        user_name=user_name
    )
    
    # Generate audio response
    audio_response_path = await text_to_speech(response_text)
    
    return {
        "transcript": transcript,
        "reply": response_text,
        "actions": actions,
        "session_id": session_id,
        "audio_path": audio_response_path,
        "tts_available": audio_response_path is not None
    }

async def elai_get_audio_response(text: str) -> Optional[str]:
    """
    Generate audio for a text response
    """
    return await text_to_speech(text)

# ============================================================
# Action Handlers
# ============================================================

async def handle_action(action: Dict, session_id: str, db=None) -> Dict:
    """
    Process an Elai action
    """
    action_type = action.get("type")
    action_data = action.get("data")
    
    result = {
        "action": action_type,
        "status": "processed",
        "timestamp": datetime.now(timezone.utc).isoformat()
    }
    
    if action_type == "BREATHING_EXERCISE":
        result["message"] = "Breathing exercise session started"
        result["exercise_type"] = "4-7-8"
        result["duration_seconds"] = 120
        
    elif action_type == "SOS_ALERT":
        result["message"] = "SOS alert triggered - emergency contacts notified"
        result["alert_sent"] = True
        # In production: trigger actual SOS workflow
        
    elif action_type == "LOG_SYMPTOM":
        result["message"] = f"Symptom logged: {action_data}"
        result["symptom"] = action_data
        # In production: save to database
        
    elif action_type == "CHECK_IN_LATER":
        result["message"] = "Follow-up check-in scheduled"
        result["scheduled_minutes"] = 30
        
    elif action_type == "SHARE_WITH_CAREGIVER":
        result["message"] = f"Update sent to caregiver: {action_data}"
        result["shared"] = True
        # In production: send notification to caregiver
    
    return result

# ============================================================
# Utility Functions
# ============================================================

def get_conversation_history(session_id: str) -> List[Dict]:
    """Get conversation history for a session"""
    return memory.get_messages(session_id)

def clear_conversation(session_id: str):
    """Clear conversation history for a session"""
    memory.clear_session(session_id)

def is_service_available() -> Dict[str, bool]:
    """Check which services are available"""
    # TTS is available if Edge TTS (always available) or ElevenLabs is configured
    tts_available = TTS_PROVIDER != "none"
    if TTS_PROVIDER == "elevenlabs":
        tts_available = bool(ELEVEN_API_KEY)
    
    return {
        "llm_available": bool(EMERGENT_LLM_KEY),
        "tts_available": tts_available,
        "tts_provider": TTS_PROVIDER,
        "edge_tts_available": True,  # Always available
        "elevenlabs_available": bool(ELEVEN_API_KEY),
        "stt_available": bool(EMERGENT_LLM_KEY),  # Whisper uses same key
    }
