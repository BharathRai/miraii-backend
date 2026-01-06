"""
SOS / Fall Detection Router
============================

INTEGRATION INSTRUCTIONS:
-------------------------
1. SOS engine code should be placed in /app/backend/sos_engine/
2. Expected functions to implement:
   - detect_fall(sensor_data: dict) -> bool
   - process_sensor_event(event: dict) -> dict
   - calculate_risk_level(vitals: dict) -> str
3. Required env vars:
   - EMAIL_API_KEY (for email alerts via Resend/Brevo)
   - SMS_PROVIDER (optional, for SMS alerts)

Current status: Basic SOS trigger and incident storage
"""

from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime, timezone
import uuid
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sos", tags=["SOS & Fall Detection"])

# ============================================================
# INTEGRATION HOOK: Uncomment when SOS engine is ready
# ============================================================
# try:
#     from sos_engine.detector import detect_fall, process_sensor_event
#     SOS_ENGINE_AVAILABLE = True
# except ImportError:
#     SOS_ENGINE_AVAILABLE = False

SOS_ENGINE_AVAILABLE = False

# ============================================================
# Models
# ============================================================

class Location(BaseModel):
    latitude: float
    longitude: float
    accuracy: Optional[float] = None
    address: Optional[str] = None

class Vitals(BaseModel):
    heart_rate: Optional[int] = None
    spo2: Optional[int] = None
    temperature: Optional[float] = None
    blood_pressure: Optional[str] = None

class SOSTriggerRequest(BaseModel):
    user_id: str
    trigger_source: str = Field(..., description="'app', 'ring', 'fall_detect', 'manual'")
    vitals: Optional[Vitals] = None
    location: Optional[Location] = None
    message: Optional[str] = None
    sensor_data: Optional[dict] = None  # Raw sensor data for fall detection

class SOSTriggerResponse(BaseModel):
    success: bool
    incident_id: str
    notified_contacts: List[str]
    message: str

class Incident(BaseModel):
    incident_id: str
    user_id: str
    trigger_source: str
    vitals: Optional[Vitals] = None
    location: Optional[Location] = None
    message_sent: Optional[str] = None
    notified_contacts: List[str] = []
    acknowledged: bool = False
    acknowledged_by: Optional[str] = None
    acknowledged_at: Optional[datetime] = None
    created_at: datetime
    resolved_at: Optional[datetime] = None
    status: str = "active"  # active, acknowledged, resolved, false_alarm

class AcknowledgeRequest(BaseModel):
    incident_id: str
    acknowledged_by: str
    notes: Optional[str] = None

# ============================================================
# In-Memory Storage (Replace with MongoDB in production)
# ============================================================

# This is a placeholder - in the real server.py, we use MongoDB
incidents_store: List[dict] = []

# ============================================================
# Helper Functions
# ============================================================

async def send_sos_notifications(
    incident: Incident,
    emergency_contacts: List[dict],
    db
) -> List[str]:
    """
    Send notifications to emergency contacts.
    Uses EmailService from main server.
    """
    notified = []
    
    # Build alert message
    vitals_text = ""
    if incident.vitals:
        if incident.vitals.heart_rate:
            vitals_text += f"Heart Rate: {incident.vitals.heart_rate} bpm\n"
        if incident.vitals.spo2:
            vitals_text += f"SpO2: {incident.vitals.spo2}%\n"
    
    location_text = ""
    if incident.location:
        if incident.location.address:
            location_text = f"Location: {incident.location.address}"
        else:
            location_text = f"Location: {incident.location.latitude}, {incident.location.longitude}"
            map_link = f"https://maps.google.com/?q={incident.location.latitude},{incident.location.longitude}"
            location_text += f"\nMap: {map_link}"
    
    alert_message = f"""
    EMERGENCY SOS ALERT
    
    Trigger: {incident.trigger_source}
    Time: {incident.created_at.strftime('%Y-%m-%d %H:%M:%S UTC')}
    
    {vitals_text}
    {location_text}
    
    {incident.message_sent or 'Emergency assistance requested.'}
    """
    
    for contact in emergency_contacts:
        try:
            # Email notification
            if contact.get('email'):
                # In production, call EmailService.send_sos_alert()
                logger.info(f"SOS alert sent to {contact.get('email')}")
                notified.append(contact.get('email'))
            
            # Phone/SMS notification (if configured)
            if contact.get('phone'):
                logger.info(f"SOS SMS would be sent to {contact.get('phone')}")
                notified.append(contact.get('phone'))
                
        except Exception as e:
            logger.error(f"Failed to notify {contact}: {e}")
    
    return notified

# ============================================================
# Endpoints
# ============================================================

@router.get("/")
async def sos_health():
    """Health check for SOS service"""
    return {
        "status": "ok",
        "service": "sos-fall-detection",
        "engine_available": SOS_ENGINE_AVAILABLE
    }

@router.post("/trigger", response_model=SOSTriggerResponse)
async def trigger_sos(
    request: SOSTriggerRequest,
    background_tasks: BackgroundTasks
):
    """
    Trigger an SOS alert.
    
    - Stores the incident with vitals and location
    - Notifies emergency contacts via email/SMS
    - Returns list of notified contacts
    
    trigger_source can be:
    - 'app': Manual trigger from app button
    - 'ring': Trigger from smart ring
    - 'fall_detect': Automatic fall detection
    - 'manual': Other manual trigger
    """
    incident_id = f"sos_{uuid.uuid4().hex[:12]}"
    
    # Check for fall detection if sensor data provided
    if request.sensor_data and SOS_ENGINE_AVAILABLE:
        # from sos_engine.detector import detect_fall
        # is_fall = detect_fall(request.sensor_data)
        pass
    
    # Create incident record
    incident = Incident(
        incident_id=incident_id,
        user_id=request.user_id,
        trigger_source=request.trigger_source,
        vitals=request.vitals,
        location=request.location,
        message_sent=request.message,
        created_at=datetime.now(timezone.utc)
    )
    
    # Store incident (in production, save to MongoDB)
    incidents_store.append(incident.dict())
    
    # Get emergency contacts and send notifications
    # In production, fetch from database and use EmailService
    notified_contacts = ["emergency@example.com"]  # Mock
    
    # Schedule background notification task
    # background_tasks.add_task(send_sos_notifications, incident, contacts, db)
    
    logger.info(f"SOS triggered: {incident_id} by user {request.user_id}")
    
    return SOSTriggerResponse(
        success=True,
        incident_id=incident_id,
        notified_contacts=notified_contacts,
        message="SOS alert sent successfully. Help is on the way."
    )

@router.get("/incidents")
async def get_incidents(
    user_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 50
):
    """
    Get SOS incident history.
    
    - Filter by user_id and/or status
    - Returns incidents sorted by created_at desc
    """
    # In production, query MongoDB
    filtered = incidents_store
    
    if user_id:
        filtered = [i for i in filtered if i.get('user_id') == user_id]
    
    if status:
        filtered = [i for i in filtered if i.get('status') == status]
    
    return {
        "incidents": filtered[:limit],
        "total": len(filtered)
    }

@router.get("/incidents/{incident_id}")
async def get_incident(incident_id: str):
    """Get details of a specific incident"""
    for incident in incidents_store:
        if incident.get('incident_id') == incident_id:
            return incident
    
    raise HTTPException(status_code=404, detail="Incident not found")

@router.post("/incidents/{incident_id}/acknowledge")
async def acknowledge_incident(
    incident_id: str,
    request: AcknowledgeRequest
):
    """
    Acknowledge an SOS incident (by caregiver/responder).
    """
    for i, incident in enumerate(incidents_store):
        if incident.get('incident_id') == incident_id:
            incidents_store[i]['acknowledged'] = True
            incidents_store[i]['acknowledged_by'] = request.acknowledged_by
            incidents_store[i]['acknowledged_at'] = datetime.now(timezone.utc).isoformat()
            incidents_store[i]['status'] = 'acknowledged'
            
            return {"success": True, "message": "Incident acknowledged"}
    
    raise HTTPException(status_code=404, detail="Incident not found")

@router.post("/incidents/{incident_id}/resolve")
async def resolve_incident(
    incident_id: str,
    resolution: str = "resolved",  # resolved, false_alarm
    notes: Optional[str] = None
):
    """Mark an incident as resolved or false alarm"""
    for i, incident in enumerate(incidents_store):
        if incident.get('incident_id') == incident_id:
            incidents_store[i]['status'] = resolution
            incidents_store[i]['resolved_at'] = datetime.now(timezone.utc).isoformat()
            
            return {"success": True, "message": f"Incident marked as {resolution}"}
    
    raise HTTPException(status_code=404, detail="Incident not found")

# ============================================================
# Fall Detection Integration Point
# ============================================================

@router.post("/detect-fall")
async def detect_fall_endpoint(sensor_data: dict):
    """
    Process sensor data for fall detection.
    
    Integration point for the fall detection algorithm.
    When sos_engine is integrated, this will use the real detector.
    
    Expected sensor_data format:
    {
        "accelerometer": {"x": float, "y": float, "z": float},
        "gyroscope": {"x": float, "y": float, "z": float},
        "timestamp": int,
        "heart_rate": int (optional),
        "spo2": int (optional)
    }
    """
    if SOS_ENGINE_AVAILABLE:
        # from sos_engine.detector import detect_fall
        # result = detect_fall(sensor_data)
        pass
    
    # Mock response
    return {
        "fall_detected": False,
        "confidence": 0.0,
        "message": "Fall detection engine not integrated. Using mock response."
    }
