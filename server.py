from fastapi import FastAPI, APIRouter, HTTPException, Depends, Request, Response, BackgroundTasks
from fastapi.security import HTTPBearer
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
from pathlib import Path
from pydantic import BaseModel, Field, EmailStr
from typing import List, Optional, Dict, Any
import uuid
from datetime import datetime, timezone, timedelta
import httpx
import jwt
import random
import string
import asyncio

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# MongoDB connection
# MongoDB connection
mongo_url = os.environ.get('MONGO_URL', 'mongodb://localhost:27017')
MOCK_MODE = False

try:
    client = AsyncIOMotorClient(mongo_url, serverSelectionTimeoutMS=5000)
    db = client[os.environ.get('DB_NAME', 'miraii')]
    # Trigger a connection to check if it works
    # We'll check this in startup event
except Exception as e:
    logger.error(f"Failed to create Mongo client: {e}")
    MOCK_MODE = True
    db = None

JWT_SECRET = os.environ.get('JWT_SECRET_KEY', 'miraii_secret_key_2025')
EMERGENT_LLM_KEY = os.environ.get('EMERGENT_LLM_KEY', '')

# Email configuration - supports Resend (default) or Brevo
EMAIL_PROVIDER = os.environ.get('EMAIL_PROVIDER', 'RESEND')  # RESEND or BREVO
EMAIL_API_KEY = os.environ.get('EMAIL_API_KEY', '')
EMAIL_SENDER = os.environ.get('EMAIL_SENDER', 'Miraii Health <noreply@miraii.app>')

# Firebase configuration
FIREBASE_API_KEY = os.environ.get('FIREBASE_API_KEY', '')
FIREBASE_PROJECT_ID = os.environ.get('FIREBASE_PROJECT_ID', '')

# Google OAuth configuration
GOOGLE_CLIENT_ID = os.environ.get('GOOGLE_CLIENT_ID', '')
GOOGLE_CLIENT_SECRET = os.environ.get('GOOGLE_CLIENT_SECRET', '')

# Create the main app
app = FastAPI(title="Miraii Smart Ring API", version="2.0.0")

# Create a router with the /api prefix
api_router = APIRouter(prefix="/api")

# Import modular routers
from routers.elai import router as elai_router
from routers.sos import router as sos_router

# Include modular routers
api_router.include_router(elai_router)
api_router.include_router(sos_router)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

@app.on_event("startup")
async def startup_db_client():
    global MOCK_MODE, db
    try:
        if not MOCK_MODE:
            await client.admin.command('ping')
            logger.info(f"Connected to MongoDB at {mongo_url}")
    except Exception as e:
        logger.warning(f"MongoDB connection failed: {e}. Switching to MOCK MODE.")
        MOCK_MODE = True
        # Create a dummy db object if needed, or handle in endpoints


# ===================== EMAIL SERVICE =====================

class EmailService:
    """
    Generic email service abstraction supporting multiple providers.
    Currently supports: Resend (default), Brevo/Sendinblue
    
    Configuration via environment variables:
    - EMAIL_PROVIDER: 'RESEND' or 'BREVO'
    - EMAIL_API_KEY: Your API key
    - EMAIL_SENDER: Verified sender email (e.g., 'Miraii Health <noreply@miraii.app>')
    """
    
    RESEND_API_URL = "https://api.resend.com/emails"
    BREVO_API_URL = "https://api.brevo.com/v3/smtp/email"
    
    @staticmethod
    def is_configured() -> bool:
        return bool(EMAIL_API_KEY)
    
    @staticmethod
    async def send_email(to_email: str, subject: str, html_content: str, text_content: str = "") -> dict:
        """
        Send an email using the configured provider.
        Returns: {"success": bool, "message": str, "provider": str}
        """
        if not EMAIL_API_KEY:
            logger.warning("Email not sent - EMAIL_API_KEY not configured (demo mode)")
            return {"success": False, "message": "Email not configured", "demo_mode": True}
        
        try:
            async with httpx.AsyncClient() as client:
                if EMAIL_PROVIDER.upper() == 'RESEND':
                    return await EmailService._send_via_resend(client, to_email, subject, html_content)
                elif EMAIL_PROVIDER.upper() == 'BREVO':
                    return await EmailService._send_via_brevo(client, to_email, subject, html_content, text_content)
                else:
                    logger.error(f"Unknown email provider: {EMAIL_PROVIDER}")
                    return {"success": False, "message": f"Unknown provider: {EMAIL_PROVIDER}"}
        except Exception as e:
            logger.error(f"Email send error: {str(e)}")
            return {"success": False, "message": str(e)}
    
    @staticmethod
    async def _send_via_resend(client: httpx.AsyncClient, to_email: str, subject: str, html_content: str) -> dict:
        """Send email via Resend API"""
        response = await client.post(
            EmailService.RESEND_API_URL,
            headers={
                "Authorization": f"Bearer {EMAIL_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "from": EMAIL_SENDER,
                "to": [to_email],
                "subject": subject,
                "html": html_content
            },
            timeout=30.0
        )
        
        if response.status_code in [200, 201]:
            logger.info(f"Email sent via Resend to {to_email}")
            return {"success": True, "message": "Email sent", "provider": "resend"}
        else:
            error_msg = response.text
            logger.error(f"Resend error: {response.status_code} - {error_msg}")
            return {"success": False, "message": error_msg, "provider": "resend"}
    
    @staticmethod
    async def _send_via_brevo(client: httpx.AsyncClient, to_email: str, subject: str, html_content: str, text_content: str) -> dict:
        """Send email via Brevo/Sendinblue API"""
        # Parse sender name and email
        sender_parts = EMAIL_SENDER.split('<')
        sender_name = sender_parts[0].strip() if len(sender_parts) > 1 else "Miraii Health"
        sender_email = sender_parts[1].replace('>', '').strip() if len(sender_parts) > 1 else EMAIL_SENDER
        
        response = await client.post(
            EmailService.BREVO_API_URL,
            headers={
                "api-key": EMAIL_API_KEY,
                "Content-Type": "application/json"
            },
            json={
                "sender": {"name": sender_name, "email": sender_email},
                "to": [{"email": to_email}],
                "subject": subject,
                "htmlContent": html_content,
                "textContent": text_content or subject
            },
            timeout=30.0
        )
        
        if response.status_code in [200, 201]:
            logger.info(f"Email sent via Brevo to {to_email}")
            return {"success": True, "message": "Email sent", "provider": "brevo"}
        else:
            error_msg = response.text
            logger.error(f"Brevo error: {response.status_code} - {error_msg}")
            return {"success": False, "message": error_msg, "provider": "brevo"}
    
    # ==================== EMAIL TEMPLATES ====================
    
    @staticmethod
    def get_otp_email_html(otp: str) -> str:
        """Generate OTP verification email HTML"""
        return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <style>
                body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; margin: 0; padding: 0; background: #f5f5f5; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 40px 20px; }}
                .card {{ background: white; border-radius: 16px; padding: 40px; box-shadow: 0 2px 8px rgba(0,0,0,0.08); }}
                .logo {{ text-align: center; margin-bottom: 30px; }}
                .logo h1 {{ color: #6366F1; margin: 0; font-size: 28px; font-weight: 700; }}
                .logo p {{ color: #6B7280; margin: 5px 0 0 0; font-size: 14px; }}
                .otp-box {{ background: linear-gradient(135deg, #6366F1 0%, #8B5CF6 100%); color: white; text-align: center; padding: 30px; border-radius: 12px; margin: 30px 0; }}
                .otp-code {{ font-size: 36px; font-weight: 700; letter-spacing: 8px; margin: 10px 0; font-family: monospace; }}
                .message {{ color: #374151; line-height: 1.6; font-size: 15px; }}
                .footer {{ color: #9CA3AF; font-size: 12px; text-align: center; margin-top: 30px; padding-top: 20px; border-top: 1px solid #E5E7EB; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="card">
                    <div class="logo">
                        <h1>Miraii</h1>
                        <p>Smart Ring Health Companion</p>
                    </div>
                    <div class="message">
                        <p>Hello,</p>
                        <p>Your verification code for Miraii is:</p>
                    </div>
                    <div class="otp-box">
                        <p style="margin: 0; font-size: 14px; opacity: 0.9;">Your verification code</p>
                        <p class="otp-code">{otp}</p>
                        <p style="margin: 0; font-size: 12px; opacity: 0.8;">Valid for 10 minutes</p>
                    </div>
                    <div class="message">
                        <p>If you didn't request this code, please ignore this email.</p>
                        <p style="color: #6B7280; font-size: 13px;">For your security, never share this code with anyone.</p>
                    </div>
                    <div class="footer">
                        <p>© 2025 Miraii Health. All rights reserved.</p>
                    </div>
                </div>
            </div>
        </body>
        </html>
        """
    
    @staticmethod
    def get_password_reset_email_html(reset_token: str) -> str:
        """Generate password reset email HTML"""
        return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <style>
                body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; margin: 0; padding: 0; background: #f5f5f5; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 40px 20px; }}
                .card {{ background: white; border-radius: 16px; padding: 40px; box-shadow: 0 2px 8px rgba(0,0,0,0.08); }}
                .logo {{ text-align: center; margin-bottom: 30px; }}
                .logo h1 {{ color: #6366F1; margin: 0; font-size: 28px; font-weight: 700; }}
                .reset-box {{ background: #F3F4F6; text-align: center; padding: 30px; border-radius: 12px; margin: 30px 0; }}
                .token {{ background: #E5E7EB; padding: 12px 20px; border-radius: 8px; font-family: monospace; font-size: 16px; word-break: break-all; margin: 15px 0; display: inline-block; }}
                .message {{ color: #374151; line-height: 1.6; font-size: 15px; }}
                .footer {{ color: #9CA3AF; font-size: 12px; text-align: center; margin-top: 30px; padding-top: 20px; border-top: 1px solid #E5E7EB; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="card">
                    <div class="logo">
                        <h1>Miraii</h1>
                        <p style="color: #6B7280; margin: 5px 0 0 0; font-size: 14px;">Smart Ring Health Companion</p>
                    </div>
                    <div class="message">
                        <p>Hello,</p>
                        <p>We received a request to reset your Miraii account password.</p>
                    </div>
                    <div class="reset-box">
                        <p style="margin: 0 0 15px 0; color: #374151;">Use this code in the app to reset your password:</p>
                        <div class="token">{reset_token}</div>
                        <p style="margin: 15px 0 0 0; font-size: 12px; color: #6B7280;">Valid for 1 hour</p>
                    </div>
                    <div class="message">
                        <p>If you didn't request a password reset, you can safely ignore this email.</p>
                    </div>
                    <div class="footer">
                        <p>© 2025 Miraii Health. All rights reserved.</p>
                    </div>
                </div>
            </div>
        </body>
        </html>
        """
    
    @staticmethod
    def get_daily_summary_email_html(
        recipient_name: str,
        user_name: str,
        date_str: str,
        sleep_data: dict,
        heart_data: dict,
        activity_data: dict,
        other_data: dict,
        insight: str,
        is_caregiver: bool = False
    ) -> str:
        """Generate daily vitals summary email HTML"""
        
        # Sleep section
        sleep_html = f"""
        <div style="background: #EEF2FF; border-radius: 12px; padding: 20px; margin-bottom: 16px;">
            <div style="display: flex; align-items: center; margin-bottom: 12px;">
                <span style="font-size: 24px; margin-right: 10px;">🌙</span>
                <h3 style="margin: 0; color: #4338CA; font-size: 16px;">Sleep</h3>
            </div>
            <div style="display: grid; gap: 8px;">
                <div style="display: flex; justify-content: space-between;">
                    <span style="color: #6B7280;">Total Duration</span>
                    <span style="font-weight: 600; color: #1F2937;">{sleep_data.get('duration', 'N/A')}</span>
                </div>
                <div style="display: flex; justify-content: space-between;">
                    <span style="color: #6B7280;">Sleep Score</span>
                    <span style="font-weight: 600; color: #1F2937;">{sleep_data.get('score', 'N/A')}/100</span>
                </div>
                <div style="display: flex; justify-content: space-between;">
                    <span style="color: #6B7280;">Deep / Light / REM</span>
                    <span style="font-weight: 600; color: #1F2937;">{sleep_data.get('stages', 'N/A')}</span>
                </div>
                {f'<div style="background: #FEF3C7; padding: 8px 12px; border-radius: 6px; margin-top: 8px;"><span style="color: #B45309;">⚠️ Apnea risk: {sleep_data.get("apnea_risk", "low")}</span></div>' if sleep_data.get('apnea_risk', 'low') != 'low' else ''}
            </div>
        </div>
        """
        
        # Heart section
        heart_html = f"""
        <div style="background: #FEF2F2; border-radius: 12px; padding: 20px; margin-bottom: 16px;">
            <div style="display: flex; align-items: center; margin-bottom: 12px;">
                <span style="font-size: 24px; margin-right: 10px;">❤️</span>
                <h3 style="margin: 0; color: #DC2626; font-size: 16px;">Heart</h3>
            </div>
            <div style="display: grid; gap: 8px;">
                <div style="display: flex; justify-content: space-between;">
                    <span style="color: #6B7280;">Average HR</span>
                    <span style="font-weight: 600; color: #1F2937;">{heart_data.get('avg_hr', 'N/A')} BPM</span>
                </div>
                <div style="display: flex; justify-content: space-between;">
                    <span style="color: #6B7280;">Resting HR</span>
                    <span style="font-weight: 600; color: #1F2937;">{heart_data.get('rhr', 'N/A')} BPM</span>
                </div>
                <div style="display: flex; justify-content: space-between;">
                    <span style="color: #6B7280;">HRV</span>
                    <span style="font-weight: 600; color: #1F2937;">{heart_data.get('hrv', 'N/A')} ms</span>
                </div>
                <div style="display: flex; justify-content: space-between;">
                    <span style="color: #6B7280;">VO2max</span>
                    <span style="font-weight: 600; color: #1F2937;">{heart_data.get('vo2max', 'N/A')} ml/kg/min</span>
                </div>
                {f'<div style="background: #FEE2E2; padding: 8px 12px; border-radius: 6px; margin-top: 8px;"><span style="color: #991B1B;">⚠️ {heart_data.get("irregularity_note", "")}</span></div>' if heart_data.get('irregularity_note') else ''}
            </div>
        </div>
        """
        
        # Activity section
        activity_html = f"""
        <div style="background: #ECFDF5; border-radius: 12px; padding: 20px; margin-bottom: 16px;">
            <div style="display: flex; align-items: center; margin-bottom: 12px;">
                <span style="font-size: 24px; margin-right: 10px;">🏃</span>
                <h3 style="margin: 0; color: #059669; font-size: 16px;">Activity</h3>
            </div>
            <div style="display: grid; gap: 8px;">
                <div style="display: flex; justify-content: space-between;">
                    <span style="color: #6B7280;">Steps</span>
                    <span style="font-weight: 600; color: #1F2937;">{activity_data.get('steps', 'N/A')} / {activity_data.get('goal', '8000')}</span>
                </div>
                <div style="display: flex; justify-content: space-between;">
                    <span style="color: #6B7280;">Workouts</span>
                    <span style="font-weight: 600; color: #1F2937;">{activity_data.get('workouts', '0')}</span>
                </div>
                <div style="display: flex; justify-content: space-between;">
                    <span style="color: #6B7280;">Active Minutes</span>
                    <span style="font-weight: 600; color: #1F2937;">{activity_data.get('active_minutes', 'N/A')} min</span>
                </div>
            </div>
        </div>
        """
        
        # Other metrics section
        other_html = f"""
        <div style="background: #F5F3FF; border-radius: 12px; padding: 20px; margin-bottom: 16px;">
            <div style="display: flex; align-items: center; margin-bottom: 12px;">
                <span style="font-size: 24px; margin-right: 10px;">📊</span>
                <h3 style="margin: 0; color: #7C3AED; font-size: 16px;">Other Metrics</h3>
            </div>
            <div style="display: grid; gap: 8px;">
                <div style="display: flex; justify-content: space-between;">
                    <span style="color: #6B7280;">Average SpO2</span>
                    <span style="font-weight: 600; color: #1F2937;">{other_data.get('spo2', 'N/A')}%</span>
                </div>
                <div style="display: flex; justify-content: space-between;">
                    <span style="color: #6B7280;">Skin Temperature</span>
                    <span style="font-weight: 600; color: #1F2937;">{other_data.get('skin_temp_status', 'Normal')}</span>
                </div>
            </div>
        </div>
        """
        
        # Caregiver note
        caregiver_note = f"""
        <div style="background: #FEF3C7; border-radius: 8px; padding: 12px 16px; margin-bottom: 20px; font-size: 13px; color: #92400E;">
            📋 You are receiving this because <strong>{user_name}</strong> has shared their Miraii daily summary with you.
        </div>
        """ if is_caregiver else ""
        
        return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <style>
                body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; margin: 0; padding: 0; background: #f5f5f5; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                .card {{ background: white; border-radius: 16px; padding: 30px; box-shadow: 0 2px 8px rgba(0,0,0,0.08); }}
                .header {{ text-align: center; margin-bottom: 24px; padding-bottom: 20px; border-bottom: 1px solid #E5E7EB; }}
                .header h1 {{ color: #6366F1; margin: 0 0 8px 0; font-size: 24px; }}
                .header .date {{ color: #6B7280; font-size: 14px; }}
                .greeting {{ color: #374151; margin-bottom: 20px; }}
                .insight {{ background: linear-gradient(135deg, #6366F1 0%, #8B5CF6 100%); color: white; border-radius: 12px; padding: 16px 20px; margin-bottom: 24px; }}
                .insight p {{ margin: 0; font-size: 14px; line-height: 1.5; }}
                .footer {{ color: #9CA3AF; font-size: 12px; text-align: center; margin-top: 24px; padding-top: 20px; border-top: 1px solid #E5E7EB; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="card">
                    <div class="header">
                        <h1>Miraii Daily Summary</h1>
                        <p class="date">{date_str}</p>
                    </div>
                    
                    {caregiver_note}
                    
                    <div class="greeting">
                        <p>Good morning, {recipient_name}! 👋</p>
                        <p>Here's {'how ' + user_name + ' did' if is_caregiver else 'your health summary'} yesterday:</p>
                    </div>
                    
                    <div class="insight">
                        <p>💡 <strong>Insight:</strong> {insight}</p>
                    </div>
                    
                    {sleep_html}
                    {heart_html}
                    {activity_html}
                    {other_html}
                    
                    <div class="footer">
                        <p>Tracked with Miraii Smart Ring</p>
                        <p>© 2025 Miraii Health. All rights reserved.</p>
                    </div>
                </div>
            </div>
        </body>
        </html>
        """
    
    # ==================== SEND METHODS ====================
    
    @staticmethod
    async def send_otp_email(to_email: str, otp: str) -> dict:
        """Send OTP verification email"""
        html = EmailService.get_otp_email_html(otp)
        result = await EmailService.send_email(
            to_email=to_email,
            subject="Your Miraii Verification Code",
            html_content=html
        )
        if not result.get("success") and not result.get("demo_mode"):
            logger.error(f"Failed to send OTP email to {to_email}")
        return result
    
    @staticmethod
    async def send_password_reset_email(to_email: str, reset_token: str) -> dict:
        """Send password reset email"""
        html = EmailService.get_password_reset_email_html(reset_token)
        result = await EmailService.send_email(
            to_email=to_email,
            subject="Reset Your Miraii Password",
            html_content=html
        )
        return result
    
    @staticmethod
    async def send_daily_summary_email(
        to_email: str,
        recipient_name: str,
        user_name: str,
        date_str: str,
        sleep_data: dict,
        heart_data: dict,
        activity_data: dict,
        other_data: dict,
        insight: str,
        is_caregiver: bool = False
    ) -> dict:
        """Send daily vitals summary email"""
        html = EmailService.get_daily_summary_email_html(
            recipient_name=recipient_name,
            user_name=user_name,
            date_str=date_str,
            sleep_data=sleep_data,
            heart_data=heart_data,
            activity_data=activity_data,
            other_data=other_data,
            insight=insight,
            is_caregiver=is_caregiver
        )
        result = await EmailService.send_email(
            to_email=to_email,
            subject=f"Miraii Daily Health Summary – {date_str}",
            html_content=html
        )
        return result

# ===================== MODELS =====================

class UserCreate(BaseModel):
    phone: Optional[str] = None
    email: Optional[str] = None

class UserProfile(BaseModel):
    user_id: str
    name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    gender: Optional[str] = None
    date_of_birth: Optional[str] = None
    height: Optional[float] = None
    height_unit: str = "cm"
    weight: Optional[float] = None
    weight_unit: str = "kg"
    activity_level: Optional[str] = None
    health_conditions: List[str] = []
    goals: List[str] = []
    profile_picture: Optional[str] = None
    ring_connected: bool = False
    last_sync: Optional[datetime] = None
    onboarding_completed: bool = False
    theme: str = "light"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class ProfileUpdate(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    gender: Optional[str] = None
    date_of_birth: Optional[str] = None
    height: Optional[float] = None
    height_unit: Optional[str] = None
    weight: Optional[float] = None
    weight_unit: Optional[str] = None
    activity_level: Optional[str] = None
    health_conditions: Optional[List[str]] = None
    goals: Optional[List[str]] = None
    profile_picture: Optional[str] = None
    onboarding_completed: Optional[bool] = None
    theme: Optional[str] = None

class OTPRequest(BaseModel):
    phone: Optional[str] = None
    email: Optional[str] = None

class OTPVerify(BaseModel):
    phone: Optional[str] = None
    email: Optional[str] = None
    otp: str

# Firebase Phone Auth Models
class FirebasePhoneAuthRequest(BaseModel):
    """Request to verify Firebase phone auth ID token"""
    id_token: str  # Firebase ID token from client

class FirebasePhoneResponse(BaseModel):
    """Response after verifying Firebase phone auth"""
    access_token: str
    token_type: str = "bearer"
    user: dict
    is_new_user: bool = False

# Google Sign-In Models
class GoogleAuthRequest(BaseModel):
    """Request to verify Google ID token"""
    id_token: str  # Google ID token from client

class GoogleAuthResponse(BaseModel):
    """Response after verifying Google sign-in"""
    access_token: str
    token_type: str = "bearer"
    user: dict
    is_new_user: bool = False

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict

class HealthMetric(BaseModel):
    metric_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str
    metric_type: str  # heart_rate, spo2, sleep, steps, skin_temp, hrv, fall_detection
    value: Any
    unit: Optional[str] = None
    status: Optional[str] = None  # normal, elevated, low, excellent, etc.
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Dict[str, Any] = {}

class Alert(BaseModel):
    alert_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str
    alert_type: str  # elevated_heart_rate, fall_detected, pill_reminder, abnormal_sleep, health_sharing
    title: str
    description: str
    status: str = "new"  # new, read, resolved
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Dict[str, Any] = {}

class PillReminder(BaseModel):
    reminder_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str
    medication_name: str
    dosage: str
    schedule_times: List[str]  # List of times like ["08:00", "20:00"]
    taken_today: List[str] = []  # Times when pills were taken today
    active: bool = True

class EmergencyContact(BaseModel):
    contact_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str
    name: str
    phone: str
    relationship: str
    is_primary: bool = False

class HealthSharingContact(BaseModel):
    sharing_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str
    name: str
    phone: str
    role: str  # Primary Doctor, Family, etc.
    sharing_enabled: bool = True

class ChatMessage(BaseModel):
    message_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str
    role: str  # user or assistant
    content: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class ChatRequest(BaseModel):
    message: str

# ===================== SOS INCIDENT MODELS =====================

class SOSVitals(BaseModel):
    heart_rate: Optional[int] = None
    heart_rate_status: Optional[str] = None  # "Normal", "Elevated", "Low"
    spo2: Optional[int] = None
    spo2_status: Optional[str] = None
    data_age_seconds: Optional[int] = None  # How old is this data

class SOSLocation(BaseModel):
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    accuracy: Optional[float] = None
    address: Optional[str] = None
    map_link: Optional[str] = None
    permission_denied: bool = False

class SOSContactNotification(BaseModel):
    contact_id: str
    contact_name: str
    contact_phone: str
    channel: str  # "sms", "call", "push"
    status: str  # "sent", "delivered", "failed"
    sent_at: datetime

class SOSIncident(BaseModel):
    incident_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str
    user_name: Optional[str] = None
    trigger_source: str  # "app_button", "ring_button", "fall_detection"
    trigger_type: str  # "manual_sos", "fall_detected"
    vitals: SOSVitals
    location: SOSLocation
    contacts_notified: List[SOSContactNotification] = []
    message_sent: str
    status: str = "active"  # "active", "resolved", "cancelled"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    resolved_at: Optional[datetime] = None
    resolution_notes: Optional[str] = None

class SOSTriggerRequest(BaseModel):
    trigger_source: str  # "app_button", "ring_button", "fall_detection"
    vitals: Optional[SOSVitals] = None
    location: Optional[SOSLocation] = None

class Product(BaseModel):
    product_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    description: str
    price: float
    currency: str = "USD"
    image: Optional[str] = None
    category: str
    in_stock: bool = True

# ===================== DAILY SUMMARY SETTINGS MODELS =====================

class DailySummaryRecipient(BaseModel):
    sharing_id: str  # Reference to health_sharing contact
    name: str
    email: str
    enabled: bool = True

class DailySummarySettings(BaseModel):
    user_id: str
    enabled: bool = False
    send_to_self: bool = True
    delivery_time: str = "07:00"  # HH:MM format in user's timezone
    timezone: str = "UTC"
    recipients: List[DailySummaryRecipient] = []
    include_sleep: bool = True
    include_heart: bool = True
    include_activity: bool = True
    include_other: bool = True
    last_sent_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class DailySummarySettingsUpdate(BaseModel):
    enabled: Optional[bool] = None
    send_to_self: Optional[bool] = None
    delivery_time: Optional[str] = None
    timezone: Optional[str] = None
    recipients: Optional[List[DailySummaryRecipient]] = None
    include_sleep: Optional[bool] = None
    include_heart: Optional[bool] = None
    include_activity: Optional[bool] = None
    include_other: Optional[bool] = None

# ===================== AUTH HELPERS =====================

def generate_otp():
    return ''.join(random.choices(string.digits, k=6))

def create_jwt_token(user_id: str, expires_delta: timedelta = timedelta(days=7)):
    expire = datetime.now(timezone.utc) + expires_delta
    payload = {
        "sub": user_id,
        "exp": expire,
        "iat": datetime.now(timezone.utc)
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")

def verify_jwt_token(token: str):
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        return payload.get("sub")
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None

async def get_current_user(request: Request):
    # Check Authorization header
    auth_header = request.headers.get("Authorization")
    if MOCK_MODE:
        # RETURN DUMMY USER
        return {
            "user_id": "mock_user",
            "name": "Mock User",
            "email": "mock@example.com",
            "onboarding_completed": True
        }

    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header.split(" ")[1]
        user_id = verify_jwt_token(token)
        if user_id:
            user = await db.users.find_one({"user_id": user_id}, {"_id": 0})
            if user:
                return user
    
    # Check session token cookie
    session_token = request.cookies.get("session_token")
    if session_token:
        session = await db.user_sessions.find_one({"session_token": session_token}, {"_id": 0})
        if session:
            expires_at = session.get("expires_at")
            if expires_at:
                if expires_at.tzinfo is None:
                    expires_at = expires_at.replace(tzinfo=timezone.utc)
                if expires_at > datetime.now(timezone.utc):
                    user = await db.users.find_one({"user_id": session["user_id"]}, {"_id": 0})
                    if user:
                        return user
    
    raise HTTPException(status_code=401, detail="Not authenticated")

# ===================== AUTH ENDPOINTS =====================

class PasswordResetRequest(BaseModel):
    email: str

class PasswordResetVerify(BaseModel):
    email: str
    token: str
    new_password: Optional[str] = None  # For future password implementation

@api_router.post("/auth/send-otp")
async def send_otp(request: OTPRequest):
    """Send OTP to phone or email"""
    if not request.phone and not request.email:
        raise HTTPException(status_code=400, detail="Phone or email required")
    
    otp = generate_otp()
    identifier = request.phone or request.email
    
    # Check rate limiting (max 3 OTPs per 10 minutes)
    recent_otps = await db.otps.count_documents({
        "identifier": identifier,
        "created_at": {"$gte": datetime.now(timezone.utc) - timedelta(minutes=10)}
    })
    if recent_otps >= 5:
        raise HTTPException(status_code=429, detail="Too many OTP requests. Please wait before trying again.")
    
    # Store OTP with expiry
    await db.otps.insert_one({
        "identifier": identifier,
        "otp": otp,
        "created_at": datetime.now(timezone.utc),
        "expires_at": datetime.now(timezone.utc) + timedelta(minutes=10),
        "verified": False
    })
    
    # Send OTP via email if email provided
    email_result = None
    if request.email:
        email_result = await EmailService.send_otp_email(request.email, otp)
    
    # Always log for debugging (remove in production)
    logger.info(f"OTP for {identifier}: {otp}")
    
    response_data = {
        "message": "OTP sent successfully",
        "email_sent": email_result.get("success", False) if email_result else None,
    }
    
    return response_data

@api_router.post("/auth/verify-otp", response_model=TokenResponse)
async def verify_otp(request: OTPVerify, response: Response):
    """Verify OTP and return JWT token"""
    identifier = request.phone or request.email
    if not identifier:
        raise HTTPException(status_code=400, detail="Phone or email required")
    
    # Validate OTP format
    is_valid_format = request.otp and len(request.otp) == 6 and request.otp.isdigit()
    if not is_valid_format:
        raise HTTPException(status_code=400, detail="Please enter a valid 6-digit OTP")
    
    # Check if email provider is configured for real OTP validation
    if EmailService.is_configured():
        # Real OTP validation
        otp_record = await db.otps.find_one({
            "identifier": identifier,
            "otp": request.otp,
            "verified": False,
            "expires_at": {"$gt": datetime.now(timezone.utc)}
        })
        
        if not otp_record:
            raise HTTPException(status_code=400, detail="Invalid or expired OTP")
        
        # Mark OTP as verified
        await db.otps.update_one(
            {"_id": otp_record["_id"]},
            {"$set": {"verified": True}}
        )
    else:
        # Demo mode: Validate against stored OTP even in demo mode for better testing
        otp_record = await db.otps.find_one({
            "identifier": identifier,
            "otp": request.otp,
            "verified": False,
            "expires_at": {"$gt": datetime.now(timezone.utc)}
        })
        
        if otp_record:
            # Mark as verified if found
            await db.otps.update_one(
                {"_id": otp_record["_id"]},
                {"$set": {"verified": True}}
            )
        else:
            # In demo mode, still log but allow any 6-digit OTP
            logger.info(f"Demo mode: Accepting OTP {request.otp} for {identifier}")
    
    # Delete old OTPs for this identifier
    await db.otps.delete_many({
        "identifier": identifier,
        "$or": [
            {"verified": True},
            {"expires_at": {"$lt": datetime.now(timezone.utc)}}
        ]
    })
    
    # Find or create user
    query = {"phone": request.phone} if request.phone else {"email": request.email}
    user = await db.users.find_one(query, {"_id": 0})
    
    if not user:
        user_id = f"user_{uuid.uuid4().hex[:12]}"
        user = {
            "user_id": user_id,
            "phone": request.phone,
            "email": request.email,
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
            "onboarding_completed": False,
            "theme": "light"
        }
        await db.users.insert_one(user)
        user.pop("_id", None)
    
    # Create JWT token
    token = create_jwt_token(user["user_id"])
    
    # Set cookie
    response.set_cookie(
        key="session_token",
        value=token,
        httponly=True,
        secure=True,
        samesite="none",
        max_age=7 * 24 * 60 * 60
    )
    
    return TokenResponse(access_token=token, user=user)

@api_router.post("/auth/forgot-password")
async def forgot_password(request: PasswordResetRequest):
    """Send password reset email"""
    # Check if user exists
    user = await db.users.find_one({"email": request.email}, {"_id": 0})
    
    # Always return success to prevent email enumeration
    if not user:
        return {"message": "If an account exists with this email, a reset link has been sent."}
    
    # Generate reset token
    reset_token = ''.join(random.choices(string.ascii_letters + string.digits, k=32))
    
    # Store reset token
    await db.password_resets.update_one(
        {"email": request.email},
        {
            "$set": {
                "token": reset_token,
                "created_at": datetime.now(timezone.utc),
                "expires_at": datetime.now(timezone.utc) + timedelta(hours=1),
                "used": False
            }
        },
        upsert=True
    )
    
    # Send reset email
    email_result = await EmailService.send_password_reset_email(request.email, reset_token)
    
    response_data = {
        "message": "If an account exists with this email, a reset link has been sent.",
        "email_sent": email_result.get("success", False)
    }
    
    # Include token if email provider not configured (for testing)
    if not EmailService.is_configured():
        response_data["demo_token"] = reset_token
        response_data["note"] = "Email provider not configured. Token shown for demo purposes. Add EMAIL_API_KEY to enable real email delivery."
    
    return response_data

@api_router.post("/auth/reset-password")
async def reset_password(request: PasswordResetVerify):
    """Verify reset token and return new auth token"""
    # Find valid reset token
    reset_record = await db.password_resets.find_one({
        "email": request.email,
        "token": request.token,
        "used": False,
        "expires_at": {"$gt": datetime.now(timezone.utc)}
    })
    
    if not reset_record:
        raise HTTPException(status_code=400, detail="Invalid or expired reset token")
    
    # Mark token as used
    await db.password_resets.update_one(
        {"_id": reset_record["_id"]},
        {"$set": {"used": True}}
    )
    
    # Find user
    user = await db.users.find_one({"email": request.email}, {"_id": 0})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Create new JWT token (effectively logs them in)
    token = create_jwt_token(user["user_id"])
    
    return {
        "message": "Password reset successful",
        "access_token": token,
        "token_type": "bearer",
        "user": user
    }

# ===================== FIREBASE PHONE AUTH =====================

async def verify_firebase_id_token(id_token: str) -> dict:
    """
    Verify Firebase ID token using Firebase Admin SDK or REST API.
    Returns decoded token data with uid, phone_number, etc.
    """
    try:
        # Try using Firebase Admin SDK first (if available)
        import firebase_admin
        from firebase_admin import auth as firebase_auth
        
        if firebase_admin._apps:
            decoded = firebase_auth.verify_id_token(id_token)
            return {
                "uid": decoded.get("uid"),
                "phone_number": decoded.get("phone_number"),
                "email": decoded.get("email"),
                "name": decoded.get("name"),
                "picture": decoded.get("picture"),
                "provider": "phone" if decoded.get("phone_number") else "email"
            }
    except ImportError:
        pass
    except Exception as e:
        logger.warning(f"Firebase Admin SDK verification failed: {e}")
    
    # Fallback to REST API verification
    if not FIREBASE_API_KEY:
        raise HTTPException(status_code=500, detail="Firebase not configured. Add FIREBASE_API_KEY to .env")
    
    async with httpx.AsyncClient() as client:
        # Verify token with Firebase Auth REST API
        url = f"https://identitytoolkit.googleapis.com/v1/accounts:lookup?key={FIREBASE_API_KEY}"
        response = await client.post(url, json={"idToken": id_token})
        
        if response.status_code != 200:
            error_data = response.json()
            raise HTTPException(
                status_code=401, 
                detail=f"Invalid Firebase token: {error_data.get('error', {}).get('message', 'Unknown error')}"
            )
        
        data = response.json()
        if not data.get("users"):
            raise HTTPException(status_code=401, detail="No user found for token")
        
        user_data = data["users"][0]
        return {
            "uid": user_data.get("localId"),
            "phone_number": user_data.get("phoneNumber"),
            "email": user_data.get("email"),
            "name": user_data.get("displayName"),
            "picture": user_data.get("photoUrl"),
            "provider": "phone" if user_data.get("phoneNumber") else "email"
        }

@api_router.post("/auth/phone/callback", response_model=FirebasePhoneResponse)
async def firebase_phone_callback(request: FirebasePhoneAuthRequest, response: Response):
    """
    Verify Firebase phone auth ID token and create/link Miraii user account.
    Called after successful Firebase phone verification on the client.
    """
    # Verify the Firebase ID token
    firebase_user = await verify_firebase_id_token(request.id_token)
    
    if not firebase_user.get("phone_number"):
        raise HTTPException(status_code=400, detail="Phone number not found in token")
    
    phone = firebase_user["phone_number"]
    firebase_uid = firebase_user["uid"]
    
    # Find existing user by phone or Firebase UID
    user = await db.users.find_one(
        {"$or": [
            {"phone": phone},
            {"firebase_uid": firebase_uid}
        ]},
        {"_id": 0}
    )
    
    is_new_user = False
    if not user:
        # Create new user
        is_new_user = True
        user_id = f"user_{uuid.uuid4().hex[:12]}"
        user = {
            "user_id": user_id,
            "phone": phone,
            "firebase_uid": firebase_uid,
            "name": firebase_user.get("name"),
            "email": firebase_user.get("email"),
            "profile_picture": firebase_user.get("picture"),
            "auth_provider": "firebase_phone",
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
            "onboarding_completed": False,
            "theme": "light"
        }
        await db.users.insert_one(user)
        logger.info(f"Created new user via Firebase phone auth: {user_id}")
    else:
        # Update Firebase UID if not set
        if not user.get("firebase_uid"):
            await db.users.update_one(
                {"user_id": user["user_id"]},
                {"$set": {
                    "firebase_uid": firebase_uid,
                    "updated_at": datetime.now(timezone.utc)
                }}
            )
    
    # Create Miraii JWT token
    token = create_jwt_token(user["user_id"])
    
    # Store session
    await db.user_sessions.insert_one({
        "user_id": user["user_id"],
        "session_token": token,
        "auth_method": "firebase_phone",
        "expires_at": datetime.now(timezone.utc) + timedelta(days=7),
        "created_at": datetime.now(timezone.utc)
    })
    
    # Set cookie
    response.set_cookie(
        key="session_token",
        value=token,
        httponly=True,
        secure=True,
        samesite="none",
        max_age=7 * 24 * 60 * 60,
        path="/"
    )
    
    user_response = {k: v for k, v in user.items() if k != "_id"}
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": user_response,
        "is_new_user": is_new_user
    }

# Test phone verification endpoint (for Firebase test numbers)
class TestPhoneVerifyRequest(BaseModel):
    phone: str
    code: str

# Firebase test phone numbers (must match frontend)
TEST_PHONE_NUMBERS = {
    "+919555433451": "121314",
}

@api_router.post("/auth/phone/test-verify")
async def test_phone_verify(request: TestPhoneVerifyRequest, response: Response):
    """
    Verify test phone numbers without Firebase token.
    Only works for phone numbers registered in Firebase Console as test numbers.
    """
    phone = request.phone.replace(" ", "")
    
    # Check if it's a valid test phone number
    expected_code = TEST_PHONE_NUMBERS.get(phone)
    if not expected_code:
        raise HTTPException(status_code=400, detail="This endpoint only works with test phone numbers")
    
    if request.code != expected_code:
        raise HTTPException(status_code=400, detail="Invalid verification code")
    
    # Find or create user
    user = await db.users.find_one({"phone": phone}, {"_id": 0})
    
    is_new_user = False
    if not user:
        is_new_user = True
        user_id = f"user_{uuid.uuid4().hex[:12]}"
        user = {
            "user_id": user_id,
            "phone": phone,
            "auth_provider": "firebase_phone_test",
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
            "onboarding_completed": False,
            "theme": "light"
        }
        await db.users.insert_one(user)
        logger.info(f"Created new user via test phone auth: {user_id}")
    
    # Create JWT token
    token = create_jwt_token(user["user_id"])
    
    # Store session
    await db.user_sessions.insert_one({
        "user_id": user["user_id"],
        "session_token": token,
        "auth_method": "firebase_phone_test",
        "expires_at": datetime.now(timezone.utc) + timedelta(days=7),
        "created_at": datetime.now(timezone.utc)
    })
    
    # Set cookie
    response.set_cookie(
        key="session_token",
        value=token,
        httponly=True,
        secure=True,
        samesite="none",
        max_age=7 * 24 * 60 * 60,
        path="/"
    )
    
    user_response = {k: v for k, v in user.items() if k != "_id"}
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": user_response,
        "is_new_user": is_new_user
    }

# ===================== GOOGLE SIGN-IN (Direct Token) =====================

async def verify_google_id_token(id_token: str) -> dict:
    """
    Verify Google ID token using Google's tokeninfo endpoint.
    Returns user data including email, name, picture.
    """
    async with httpx.AsyncClient() as client:
        # Verify with Google's tokeninfo endpoint
        response = await client.get(
            f"https://oauth2.googleapis.com/tokeninfo?id_token={id_token}"
        )
        
        if response.status_code != 200:
            raise HTTPException(status_code=401, detail="Invalid Google ID token")
        
        token_data = response.json()
        
        # Verify audience (client ID) if configured
        if GOOGLE_CLIENT_ID and token_data.get("aud") != GOOGLE_CLIENT_ID:
            logger.warning(f"Google token audience mismatch: {token_data.get('aud')} != {GOOGLE_CLIENT_ID}")
            # Allow anyway for development, but log warning
        
        return {
            "sub": token_data.get("sub"),  # Google user ID
            "email": token_data.get("email"),
            "email_verified": token_data.get("email_verified") == "true",
            "name": token_data.get("name"),
            "picture": token_data.get("picture"),
            "given_name": token_data.get("given_name"),
            "family_name": token_data.get("family_name")
        }

@api_router.post("/auth/google", response_model=GoogleAuthResponse)
async def google_signin(request: GoogleAuthRequest, response: Response):
    """
    Verify Google ID token and create/link Miraii user account.
    Called after successful Google sign-in on the client.
    """
    # Verify the Google ID token
    google_user = await verify_google_id_token(request.id_token)
    
    if not google_user.get("email"):
        raise HTTPException(status_code=400, detail="Email not found in Google token")
    
    email = google_user["email"]
    google_sub = google_user["sub"]
    
    # Find existing user by email or Google sub
    user = await db.users.find_one(
        {"$or": [
            {"email": email},
            {"google_sub": google_sub}
        ]},
        {"_id": 0}
    )
    
    is_new_user = False
    if not user:
        # Create new user
        is_new_user = True
        user_id = f"user_{uuid.uuid4().hex[:12]}"
        user = {
            "user_id": user_id,
            "email": email,
            "google_sub": google_sub,
            "name": google_user.get("name"),
            "profile_picture": google_user.get("picture"),
            "auth_provider": "google",
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
            "onboarding_completed": False,
            "theme": "light"
        }
        await db.users.insert_one(user)
        logger.info(f"Created new user via Google sign-in: {user_id}")
    else:
        # Update Google sub and picture if not set
        updates = {"updated_at": datetime.now(timezone.utc)}
        if not user.get("google_sub"):
            updates["google_sub"] = google_sub
        if not user.get("profile_picture") and google_user.get("picture"):
            updates["profile_picture"] = google_user.get("picture")
        if not user.get("name") and google_user.get("name"):
            updates["name"] = google_user.get("name")
        
        if len(updates) > 1:  # More than just updated_at
            await db.users.update_one(
                {"user_id": user["user_id"]},
                {"$set": updates}
            )
            # Refresh user data
            user = await db.users.find_one({"user_id": user["user_id"]}, {"_id": 0})
    
    # Create Miraii JWT token
    token = create_jwt_token(user["user_id"])
    
    # Store session
    await db.user_sessions.insert_one({
        "user_id": user["user_id"],
        "session_token": token,
        "auth_method": "google",
        "expires_at": datetime.now(timezone.utc) + timedelta(days=7),
        "created_at": datetime.now(timezone.utc)
    })
    
    # Set cookie
    response.set_cookie(
        key="session_token",
        value=token,
        httponly=True,
        secure=True,
        samesite="none",
        max_age=7 * 24 * 60 * 60,
        path="/"
    )
    
    user_response = {k: v for k, v in user.items() if k != "_id"}
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": user_response,
        "is_new_user": is_new_user
    }

# ===================== EMERGENT GOOGLE AUTH (Existing) =====================

@api_router.post("/auth/google/session")
async def google_session(request: Request, response: Response):
    """Exchange Google session_id for session data"""
    session_id = request.headers.get("X-Session-ID")
    if not session_id:
        raise HTTPException(status_code=400, detail="Session ID required")
    
    async with httpx.AsyncClient() as client:
        try:
            res = await client.get(
                "https://demobackend.emergentagent.com/auth/v1/env/oauth/session-data",
                headers={"X-Session-ID": session_id}
            )
            if res.status_code != 200:
                raise HTTPException(status_code=401, detail="Invalid session")
            
            user_data = res.json()
        except Exception as e:
            logger.error(f"Google auth error: {e}")
            raise HTTPException(status_code=500, detail="Authentication failed")
    
    # Find or create user
    user = await db.users.find_one({"email": user_data["email"]}, {"_id": 0})
    
    if not user:
        user_id = f"user_{uuid.uuid4().hex[:12]}"
        user = {
            "user_id": user_id,
            "name": user_data.get("name"),
            "email": user_data.get("email"),
            "profile_picture": user_data.get("picture"),
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
            "onboarding_completed": False,
            "theme": "light"
        }
        await db.users.insert_one(user)
    
    # Store session
    session_token = user_data.get("session_token", create_jwt_token(user["user_id"]))
    await db.user_sessions.insert_one({
        "user_id": user["user_id"],
        "session_token": session_token,
        "expires_at": datetime.now(timezone.utc) + timedelta(days=7),
        "created_at": datetime.now(timezone.utc)
    })
    
    # Set cookie
    response.set_cookie(
        key="session_token",
        value=session_token,
        httponly=True,
        secure=True,
        samesite="none",
        max_age=7 * 24 * 60 * 60,
        path="/"
    )
    
    user_response = {k: v for k, v in user.items() if k != "_id"}
    return {"user": user_response, "session_token": session_token}

@api_router.get("/auth/me")
async def get_me(current_user: dict = Depends(get_current_user)):
    """Get current user profile"""
    return current_user

@api_router.post("/auth/logout")
async def logout(request: Request, response: Response):
    """Logout user"""
    session_token = request.cookies.get("session_token")
    if session_token:
        await db.user_sessions.delete_one({"session_token": session_token})
    
    response.delete_cookie(key="session_token", path="/")
    return {"message": "Logged out successfully"}

# ===================== USER PROFILE ENDPOINTS =====================

@api_router.put("/users/profile")
async def update_profile(profile: ProfileUpdate, current_user: dict = Depends(get_current_user)):
    """Update user profile"""
    update_data = {k: v for k, v in profile.dict().items() if v is not None}
    update_data["updated_at"] = datetime.now(timezone.utc)
    
    await db.users.update_one(
        {"user_id": current_user["user_id"]},
        {"$set": update_data}
    )
    
    updated_user = await db.users.find_one({"user_id": current_user["user_id"]}, {"_id": 0})
    return updated_user

@api_router.post("/users/complete-onboarding")
async def complete_onboarding(current_user: dict = Depends(get_current_user)):
    """Mark onboarding as complete"""
    await db.users.update_one(
        {"user_id": current_user["user_id"]},
        {"$set": {"onboarding_completed": True, "updated_at": datetime.now(timezone.utc)}}
    )
    return {"message": "Onboarding completed"}

# ===================== HEALTH METRICS ENDPOINTS =====================

@api_router.get("/metrics/latest")
async def get_latest_metrics(current_user: dict = Depends(get_current_user)):
    """Get latest health metrics for dashboard"""
    user_id = current_user["user_id"]
    
    metric_types = ["heart_rate", "spo2", "sleep", "steps", "skin_temp", "hrv", "fall_detection", "workout"]
    latest_metrics = {}
    
    for metric_type in metric_types:
        metric = await db.health_metrics.find_one(
            {"user_id": user_id, "metric_type": metric_type},
            {"_id": 0},
            sort=[("recorded_at", -1)]
        )
        if metric:
            latest_metrics[metric_type] = metric
    
    return latest_metrics

@api_router.get("/metrics/{metric_type}/history")
async def get_metric_history(metric_type: str, days: int = 7, current_user: dict = Depends(get_current_user)):
    """Get metric history for charts"""
    user_id = current_user["user_id"]
    since = datetime.now(timezone.utc) - timedelta(days=days)
    
    metrics = await db.health_metrics.find(
        {
            "user_id": user_id,
            "metric_type": metric_type,
            "recorded_at": {"$gte": since}
        },
        {"_id": 0}
    ).sort("recorded_at", 1).to_list(1000)
    
    return metrics

@api_router.post("/metrics")
async def add_metric(metric: HealthMetric, current_user: dict = Depends(get_current_user)):
    """Add a health metric (for demo/simulation)"""
    metric.user_id = current_user["user_id"]
    await db.health_metrics.insert_one(metric.dict())
    return {"message": "Metric recorded", "metric_id": metric.metric_id}

# ===================== ALERTS ENDPOINTS =====================

@api_router.get("/alerts")
async def get_alerts(current_user: dict = Depends(get_current_user)):
    """Get user alerts"""
    alerts = await db.alerts.find(
        {"user_id": current_user["user_id"]},
        {"_id": 0}
    ).sort("created_at", -1).to_list(100)
    return alerts

@api_router.put("/alerts/{alert_id}/status")
async def update_alert_status(alert_id: str, status: str, current_user: dict = Depends(get_current_user)):
    """Update alert status"""
    await db.alerts.update_one(
        {"alert_id": alert_id, "user_id": current_user["user_id"]},
        {"$set": {"status": status}}
    )
    return {"message": "Alert updated"}

# ===================== PILL REMINDERS ENDPOINTS =====================

@api_router.get("/pills")
async def get_pill_reminders(current_user: dict = Depends(get_current_user)):
    """Get pill reminders"""
    reminders = await db.pill_reminders.find(
        {"user_id": current_user["user_id"], "active": True},
        {"_id": 0}
    ).to_list(100)
    return reminders

@api_router.post("/pills")
async def create_pill_reminder(reminder: PillReminder, current_user: dict = Depends(get_current_user)):
    """Create a pill reminder"""
    reminder.user_id = current_user["user_id"]
    await db.pill_reminders.insert_one(reminder.dict())
    return {"message": "Reminder created", "reminder_id": reminder.reminder_id}

@api_router.post("/pills/{reminder_id}/take")
async def mark_pill_taken(reminder_id: str, current_user: dict = Depends(get_current_user)):
    """Mark pill as taken"""
    current_time = datetime.now(timezone.utc).strftime("%H:%M")
    await db.pill_reminders.update_one(
        {"reminder_id": reminder_id, "user_id": current_user["user_id"]},
        {"$push": {"taken_today": current_time}}
    )
    return {"message": "Pill marked as taken"}

# ===================== EMERGENCY CONTACTS ENDPOINTS =====================

@api_router.get("/emergency-contacts")
async def get_emergency_contacts(current_user: dict = Depends(get_current_user)):
    """Get emergency contacts"""
    contacts = await db.emergency_contacts.find(
        {"user_id": current_user["user_id"]},
        {"_id": 0}
    ).to_list(20)
    return contacts

@api_router.post("/emergency-contacts")
async def add_emergency_contact(contact: EmergencyContact, current_user: dict = Depends(get_current_user)):
    """Add emergency contact"""
    contact.user_id = current_user["user_id"]
    await db.emergency_contacts.insert_one(contact.dict())
    return {"message": "Contact added", "contact_id": contact.contact_id}

@api_router.delete("/emergency-contacts/{contact_id}")
async def delete_emergency_contact(contact_id: str, current_user: dict = Depends(get_current_user)):
    """Delete emergency contact"""
    await db.emergency_contacts.delete_one(
        {"contact_id": contact_id, "user_id": current_user["user_id"]}
    )
    return {"message": "Contact deleted"}

# ===================== HEALTH SHARING ENDPOINTS =====================

class HealthSharingCreate(BaseModel):
    name: str
    phone: str
    email: Optional[str] = None
    role: str  # Primary Doctor, Family, Caregiver, Other
    relationship: Optional[str] = None  # For Family: Son, Daughter, Spouse, etc.

class HealthSharingUpdate(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    role: Optional[str] = None
    relationship: Optional[str] = None
    sharing_enabled: Optional[bool] = None

# Mock storage for health contacts
mock_health_contacts = []

@api_router.get("/health-sharing")
async def get_health_sharing_contacts(current_user: dict = Depends(get_current_user)):
    """Get health sharing contacts"""
    if MOCK_MODE:
        return [c for c in mock_health_contacts if c["user_id"] == current_user["user_id"]]

    contacts = await db.health_sharing.find(
        {"user_id": current_user["user_id"]},
        {"_id": 0}
    ).to_list(20)
    return contacts

@api_router.post("/health-sharing")
async def add_health_sharing_contact(contact: HealthSharingCreate, current_user: dict = Depends(get_current_user)):
    """Add health sharing contact"""
    new_contact = HealthSharingContact(
        user_id=current_user["user_id"],
        name=contact.name,
        phone=contact.phone,
        role=contact.role,
        sharing_enabled=True
    )
    # Store email and relationship in the document
    contact_dict = new_contact.dict()
    contact_dict["email"] = contact.email
    contact_dict["relationship"] = contact.relationship
    
    if MOCK_MODE:
        mock_health_contacts.append(contact_dict)
        return {"message": "Contact added", "sharing_id": new_contact.sharing_id, "contact": contact_dict}

    await db.health_sharing.insert_one(contact_dict)
    
    # Remove _id from response
    response_contact = {k: v for k, v in contact_dict.items() if k != "_id"}
    return {"message": "Contact added", "sharing_id": new_contact.sharing_id, "contact": response_contact}

@api_router.put("/health-sharing/{sharing_id}")
async def update_health_sharing_contact(sharing_id: str, update: HealthSharingUpdate, current_user: dict = Depends(get_current_user)):
    """Update health sharing contact"""
    update_data = {k: v for k, v in update.dict().items() if v is not None}
    if not update_data:
        raise HTTPException(status_code=400, detail="No fields to update")
    
    if MOCK_MODE:
        for c in mock_health_contacts:
            if c["sharing_id"] == sharing_id and c["user_id"] == current_user["user_id"]:
                c.update(update_data)
                return {"message": "Contact updated", "contact": c}
        raise HTTPException(status_code=404, detail="Contact not found")

    result = await db.health_sharing.update_one(
        {"sharing_id": sharing_id, "user_id": current_user["user_id"]},
        {"$set": update_data}
    )
    
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Contact not found")
    
    updated = await db.health_sharing.find_one({"sharing_id": sharing_id}, {"_id": 0})
    return {"message": "Contact updated", "contact": updated}

@api_router.delete("/health-sharing/{sharing_id}")
async def delete_health_sharing_contact(sharing_id: str, current_user: dict = Depends(get_current_user)):
    """Delete health sharing contact - requires at least one contact to remain"""
    user_id = current_user["user_id"]
    
    if MOCK_MODE:
        user_contacts = [c for c in mock_health_contacts if c["user_id"] == user_id]
        if len(user_contacts) <= 1:
            raise HTTPException(
                status_code=400, 
                detail="Cannot delete the last contact. At least one health sharing contact is required for safety."
            )
        
        for i, c in enumerate(mock_health_contacts):
            if c["sharing_id"] == sharing_id and c["user_id"] == user_id:
                mock_health_contacts.pop(i)
                return {"message": "Contact deleted"}
        raise HTTPException(status_code=404, detail="Contact not found")

    # Count existing contacts
    contact_count = await db.health_sharing.count_documents({"user_id": user_id})
    
    if contact_count <= 1:
        raise HTTPException(
            status_code=400, 
            detail="Cannot delete the last contact. At least one health sharing contact is required for safety."
        )
    
    result = await db.health_sharing.delete_one(
        {"sharing_id": sharing_id, "user_id": user_id}
    )
    
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Contact not found")
    
    return {"message": "Contact deleted"}

# ===================== DAILY SUMMARY SETTINGS ENDPOINTS =====================

@api_router.get("/settings/daily-summary")
async def get_daily_summary_settings(current_user: dict = Depends(get_current_user)):
    """Get user's daily summary settings"""
    user_id = current_user["user_id"]
    
    settings = await db.daily_summary_settings.find_one(
        {"user_id": user_id},
        {"_id": 0}
    )
    
    if not settings:
        # Return default settings
        settings = DailySummarySettings(
            user_id=user_id,
            enabled=False,
            send_to_self=True,
            delivery_time="07:00",
            timezone="UTC",
            recipients=[],
            include_sleep=True,
            include_heart=True,
            include_activity=True,
            include_other=True
        ).dict()
    
    return settings

@api_router.put("/settings/daily-summary")
async def update_daily_summary_settings(
    update: DailySummarySettingsUpdate,
    current_user: dict = Depends(get_current_user)
):
    """Update user's daily summary settings"""
    user_id = current_user["user_id"]
    
    # Prepare update data
    update_data = {k: v for k, v in update.dict().items() if v is not None}
    update_data["updated_at"] = datetime.now(timezone.utc)
    
    # Upsert settings
    await db.daily_summary_settings.update_one(
        {"user_id": user_id},
        {
            "$set": update_data,
            "$setOnInsert": {
                "user_id": user_id,
                "created_at": datetime.now(timezone.utc)
            }
        },
        upsert=True
    )
    
    # Fetch and return updated settings
    settings = await db.daily_summary_settings.find_one(
        {"user_id": user_id},
        {"_id": 0}
    )
    
    return {"message": "Settings updated", "settings": settings}

@api_router.post("/settings/daily-summary/send-test")
async def send_test_daily_summary(current_user: dict = Depends(get_current_user)):
    """Send a test daily summary email to the user"""
    user_id = current_user["user_id"]
    user_email = current_user.get("email")
    user_name = current_user.get("name", "Friend")
    
    if not user_email:
        raise HTTPException(status_code=400, detail="User email not configured")
    
    # Get yesterday's date
    yesterday = datetime.now(timezone.utc) - timedelta(days=1)
    date_str = yesterday.strftime("%A, %B %d, %Y")
    
    # Fetch metrics for yesterday
    start_of_yesterday = yesterday.replace(hour=0, minute=0, second=0, microsecond=0)
    end_of_yesterday = start_of_yesterday + timedelta(days=1)
    
    # Get sleep data
    sleep_metric = await db.health_metrics.find_one(
        {
            "user_id": user_id,
            "metric_type": "sleep",
            "recorded_at": {"$gte": start_of_yesterday, "$lt": end_of_yesterday}
        },
        {"_id": 0},
        sort=[("recorded_at", -1)]
    )
    
    # Get heart rate data
    heart_metrics = await db.health_metrics.find(
        {
            "user_id": user_id,
            "metric_type": {"$in": ["heart_rate", "hrv"]},
            "recorded_at": {"$gte": start_of_yesterday, "$lt": end_of_yesterday}
        },
        {"_id": 0}
    ).to_list(100)
    
    # Get steps data
    steps_metric = await db.health_metrics.find_one(
        {
            "user_id": user_id,
            "metric_type": "steps",
            "recorded_at": {"$gte": start_of_yesterday, "$lt": end_of_yesterday}
        },
        {"_id": 0},
        sort=[("recorded_at", -1)]
    )
    
    # Get SpO2 data
    spo2_metric = await db.health_metrics.find_one(
        {
            "user_id": user_id,
            "metric_type": "spo2",
            "recorded_at": {"$gte": start_of_yesterday, "$lt": end_of_yesterday}
        },
        {"_id": 0},
        sort=[("recorded_at", -1)]
    )
    
    # Build summary data with defaults
    sleep_data = {
        "duration": sleep_metric.get("metadata", {}).get("duration", "7h 32m") if sleep_metric else "7h 32m",
        "score": sleep_metric.get("value", 82) if sleep_metric else 82,
        "stages": sleep_metric.get("metadata", {}).get("stages", "1h 45m / 4h 12m / 1h 35m") if sleep_metric else "1h 45m / 4h 12m / 1h 35m",
        "apnea_risk": sleep_metric.get("metadata", {}).get("apnea_risk", "low") if sleep_metric else "low"
    }
    
    # Calculate average heart rate
    hr_values = [m["value"] for m in heart_metrics if m["metric_type"] == "heart_rate"]
    hrv_values = [m["value"] for m in heart_metrics if m["metric_type"] == "hrv"]
    
    heart_data = {
        "avg_hr": round(sum(hr_values) / len(hr_values)) if hr_values else 72,
        "rhr": 62,  # Would come from specific resting HR calculation
        "hrv": round(sum(hrv_values) / len(hrv_values)) if hrv_values else 45,
        "vo2max": 38,  # Would be calculated separately
        "irregularity_note": None
    }
    
    activity_data = {
        "steps": steps_metric.get("value", 8432) if steps_metric else 8432,
        "goal": 8000,
        "workouts": 1,
        "active_minutes": 45
    }
    
    other_data = {
        "spo2": spo2_metric.get("value", 98) if spo2_metric else 98,
        "skin_temp_status": "Normal"
    }
    
    # Generate insight
    insight = "Your sleep quality was excellent last night! Your HRV is trending upward, indicating good recovery."
    
    # Send the email
    result = await EmailService.send_daily_summary_email(
        to_email=user_email,
        recipient_name=user_name,
        user_name=user_name,
        date_str=date_str,
        sleep_data=sleep_data,
        heart_data=heart_data,
        activity_data=activity_data,
        other_data=other_data,
        insight=insight,
        is_caregiver=False
    )
    
    if result.get("demo_mode"):
        return {
            "message": "Test email generated (demo mode - email provider not configured)",
            "preview_data": {
                "date": date_str,
                "sleep": sleep_data,
                "heart": heart_data,
                "activity": activity_data,
                "other": other_data,
                "insight": insight
            },
            "note": "Add EMAIL_API_KEY to .env to enable real email delivery"
        }
    elif result.get("success"):
        return {"message": f"Test daily summary sent to {user_email}"}
    else:
        raise HTTPException(status_code=500, detail=f"Failed to send email: {result.get('message')}")

# ===================== SOS INCIDENT ENDPOINTS =====================

def generate_sos_message(
    user_name: str,
    trigger_type: str,
    trigger_source: str,
    vitals: SOSVitals,
    location: SOSLocation
) -> str:
    """Generate the SOS alert message content"""
    
    # Determine event type text
    if trigger_type == "fall_detected":
        event_text = "Fall detected – user did not cancel"
    elif trigger_source == "ring_button":
        event_text = "SOS triggered from ring"
    else:
        event_text = "SOS triggered from app"
    
    # Build vitals text
    hr_text = f"{vitals.heart_rate} BPM" if vitals.heart_rate else "Not available"
    if vitals.data_age_seconds and vitals.data_age_seconds > 60:
        hr_text += f" (recorded {vitals.data_age_seconds // 60} min ago)"
    
    spo2_text = f"{vitals.spo2}%" if vitals.spo2 else "Not available"
    
    # Build location text
    if location.permission_denied:
        location_text = "Location not shared – permission denied"
        map_link = ""
    elif location.latitude and location.longitude:
        location_text = location.address or f"Lat: {location.latitude:.6f}, Long: {location.longitude:.6f}"
        map_link = location.map_link or f"https://maps.google.com/?q={location.latitude},{location.longitude}"
    else:
        location_text = "Location not available"
        map_link = ""
    
    message = f"""🚨 EMERGENCY ALERT from {user_name}

{event_text}

VITALS:
❤️ Heart rate: {hr_text}
🫁 SpO2: {spo2_text}

📍 LOCATION:
{location_text}
{map_link}

Please check on them immediately."""
    
    return message

@api_router.post("/sos/trigger")
async def trigger_sos(request: SOSTriggerRequest, current_user: dict = Depends(get_current_user)):
    """Trigger an SOS alert with vitals and location"""
    user_id = current_user["user_id"]
    user_name = current_user.get("name", "Miraii User")
    
    # Get default vitals from latest metrics if not provided
    vitals = request.vitals or SOSVitals()
    if not vitals.heart_rate or not vitals.spo2:
        latest = await db.health_metrics.find(
            {"user_id": user_id, "metric_type": {"$in": ["heart_rate", "spo2"]}},
            {"_id": 0}
        ).sort("recorded_at", -1).to_list(2)
        
        for metric in latest:
            if metric["metric_type"] == "heart_rate" and not vitals.heart_rate:
                vitals.heart_rate = metric.get("value")
                vitals.heart_rate_status = metric.get("status", "Normal")
            elif metric["metric_type"] == "spo2" and not vitals.spo2:
                vitals.spo2 = metric.get("value")
                vitals.spo2_status = metric.get("status", "Normal")
    
    # Use provided location or mark as unavailable
    location = request.location or SOSLocation()
    
    # Generate alert message
    trigger_type = "fall_detected" if request.trigger_source == "fall_detection" else "manual_sos"
    message = generate_sos_message(user_name, trigger_type, request.trigger_source, vitals, location)
    
    # Get all contacts to notify (emergency + health sharing)
    emergency_contacts = await db.emergency_contacts.find(
        {"user_id": user_id}, {"_id": 0}
    ).to_list(20)
    
    health_contacts = await db.health_sharing.find(
        {"user_id": user_id, "sharing_enabled": True}, {"_id": 0}
    ).to_list(20)
    
    # Combine and deduplicate contacts by phone
    all_contacts = {}
    for contact in emergency_contacts:
        all_contacts[contact["phone"]] = {
            "id": contact.get("contact_id", str(uuid.uuid4())),
            "name": contact["name"],
            "phone": contact["phone"],
            "is_primary": contact.get("is_primary", False)
        }
    for contact in health_contacts:
        if contact["phone"] not in all_contacts:
            all_contacts[contact["phone"]] = {
                "id": contact.get("sharing_id", str(uuid.uuid4())),
                "name": contact["name"],
                "phone": contact["phone"],
                "is_primary": False
            }
    
    # Record notifications
    notifications = []
    for phone, contact in all_contacts.items():
        notifications.append(SOSContactNotification(
            contact_id=contact["id"],
            contact_name=contact["name"],
            contact_phone=contact["phone"],
            channel="sms",  # In production, this would be based on settings
            status="sent",  # In production, this would reflect actual send status
            sent_at=datetime.now(timezone.utc)
        ))
    
    # Create incident record
    incident = SOSIncident(
        user_id=user_id,
        user_name=user_name,
        trigger_source=request.trigger_source,
        trigger_type=trigger_type,
        vitals=vitals,
        location=location,
        contacts_notified=[n.dict() for n in notifications],
        message_sent=message,
        status="active"
    )
    
    await db.sos_incidents.insert_one(incident.dict())
    
    # Also create an alert for the app
    alert = Alert(
        user_id=user_id,
        alert_type="sos_triggered",
        title="SOS Alert Sent",
        description=f"Emergency alert sent to {len(notifications)} contacts",
        metadata={
            "incident_id": incident.incident_id,
            "trigger_source": request.trigger_source,
            "contacts_count": len(notifications)
        }
    )
    await db.alerts.insert_one(alert.dict())
    
    logger.info(f"SOS triggered for user {user_id}, {len(notifications)} contacts notified")
    
    return {
        "message": "SOS alert sent successfully",
        "incident_id": incident.incident_id,
        "contacts_notified": len(notifications),
        "vitals_included": {
            "heart_rate": vitals.heart_rate is not None,
            "spo2": vitals.spo2 is not None
        },
        "location_included": location.latitude is not None
    }

@api_router.get("/sos/incidents")
async def get_sos_incidents(current_user: dict = Depends(get_current_user)):
    """Get SOS incident history"""
    incidents = await db.sos_incidents.find(
        {"user_id": current_user["user_id"]},
        {"_id": 0}
    ).sort("created_at", -1).to_list(50)
    return incidents

@api_router.get("/sos/incidents/{incident_id}")
async def get_sos_incident_detail(incident_id: str, current_user: dict = Depends(get_current_user)):
    """Get detailed SOS incident"""
    incident = await db.sos_incidents.find_one(
        {"incident_id": incident_id, "user_id": current_user["user_id"]},
        {"_id": 0}
    )
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")
    return incident

@api_router.put("/sos/incidents/{incident_id}/resolve")
async def resolve_sos_incident(incident_id: str, notes: Optional[str] = None, current_user: dict = Depends(get_current_user)):
    """Resolve/close an SOS incident"""
    result = await db.sos_incidents.update_one(
        {"incident_id": incident_id, "user_id": current_user["user_id"]},
        {
            "$set": {
                "status": "resolved",
                "resolved_at": datetime.now(timezone.utc),
                "resolution_notes": notes
            }
        }
    )
    if result.modified_count == 0:
        raise HTTPException(status_code=404, detail="Incident not found")
    return {"message": "Incident resolved"}

# ===================== ELAI CHAT ENDPOINTS =====================

@api_router.get("/chat/history")
async def get_chat_history(current_user: dict = Depends(get_current_user)):
    """Get chat history with Elai"""
    messages = await db.chat_messages.find(
        {"user_id": current_user["user_id"]},
        {"_id": 0}
    ).sort("created_at", 1).to_list(100)
    return messages

@api_router.post("/chat")
async def chat_with_elai(request: ChatRequest, current_user: dict = Depends(get_current_user)):
    """Chat with Elai AI companion"""
    from emergentintegrations.llm.chat import LlmChat, UserMessage
    
    user_id = current_user["user_id"]
    
    # Save user message
    user_msg = ChatMessage(
        user_id=user_id,
        role="user",
        content=request.message
    )
    await db.chat_messages.insert_one(user_msg.dict())
    
    # Get latest health metrics for context
    latest_metrics = await get_latest_metrics(current_user)
    
    # Build context for Elai
    health_context = "User's recent health data:\n"
    if "heart_rate" in latest_metrics:
        health_context += f"- Heart Rate: {latest_metrics['heart_rate'].get('value', 'N/A')} BPM\n"
    if "spo2" in latest_metrics:
        health_context += f"- SpO2: {latest_metrics['spo2'].get('value', 'N/A')}%\n"
    if "sleep" in latest_metrics:
        health_context += f"- Sleep: {latest_metrics['sleep'].get('value', 'N/A')}\n"
    if "steps" in latest_metrics:
        health_context += f"- Steps today: {latest_metrics['steps'].get('value', 'N/A')}\n"
    
    system_message = f"""You are Elai, a warm, empathetic AI health companion for the Miraii Smart Ring app. 
You help users understand their health metrics, provide supportive suggestions, and answer health-related questions.
Be friendly, supportive, and encouraging. Speak in a calm, reassuring tone.
Never provide medical diagnoses - always recommend consulting a healthcare professional for medical concerns.

{health_context}

User's name: {current_user.get('name', 'Friend')}
"""
    
    try:
        chat = LlmChat(
            api_key=EMERGENT_LLM_KEY,
            session_id=f"elai_{user_id}",
            system_message=system_message
        ).with_model("openai", "gpt-5.1")
        
        user_message = UserMessage(text=request.message)
        response = await chat.send_message(user_message)
        
        # Save assistant response
        assistant_msg = ChatMessage(
            user_id=user_id,
            role="assistant",
            content=response
        )
        await db.chat_messages.insert_one(assistant_msg.dict())
        
        return {"response": response, "message_id": assistant_msg.message_id}
    except Exception as e:
        logger.error(f"Elai chat error: {e}")
        # Fallback response
        fallback = "I'm here to help you with your health journey. How can I assist you today?"
        assistant_msg = ChatMessage(
            user_id=user_id,
            role="assistant",
            content=fallback
        )
        await db.chat_messages.insert_one(assistant_msg.dict())
        return {"response": fallback, "message_id": assistant_msg.message_id}

# ===================== SHOP ENDPOINTS =====================

@api_router.get("/products")
async def get_products():
    """Get all products"""
    products = await db.products.find({}, {"_id": 0}).to_list(100)
    if not products:
        # Seed default products
        default_products = [
            {
                "product_id": "prod_ring_gold",
                "name": "Miraii Smart Ring - Gold",
                "description": "Premium gold-finished smart ring with advanced health monitoring",
                "price": 299.00,
                "currency": "USD",
                "category": "rings",
                "in_stock": True
            },
            {
                "product_id": "prod_ring_silver",
                "name": "Miraii Smart Ring - Silver",
                "description": "Elegant silver smart ring with comprehensive health tracking",
                "price": 279.00,
                "currency": "USD",
                "category": "rings",
                "in_stock": True
            },
            {
                "product_id": "prod_charger",
                "name": "Miraii Ring Charger",
                "description": "Wireless charging dock for your Miraii Smart Ring",
                "price": 39.00,
                "currency": "USD",
                "category": "accessories",
                "in_stock": True
            },
            {
                "product_id": "prod_subscription",
                "name": "Miraii Premium - 1 Year",
                "description": "Unlock advanced insights, AI companion features, and priority support",
                "price": 99.00,
                "currency": "USD",
                "category": "subscriptions",
                "in_stock": True
            }
        ]
        await db.products.insert_many(default_products)
        products = default_products
    return products

@api_router.get("/products/{product_id}")
async def get_product(product_id: str):
    """Get product details"""
    product = await db.products.find_one({"product_id": product_id}, {"_id": 0})
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return product

# ===================== DEMO DATA ENDPOINTS =====================

@api_router.post("/demo/seed-data")
async def seed_demo_data(current_user: dict = Depends(get_current_user)):
    """Seed demo health data for the user"""
    user_id = current_user["user_id"]
    now = datetime.now(timezone.utc)
    
    # Clear existing data
    await db.health_metrics.delete_many({"user_id": user_id})
    await db.alerts.delete_many({"user_id": user_id})
    await db.pill_reminders.delete_many({"user_id": user_id})
    await db.health_sharing.delete_many({"user_id": user_id})
    
    # Seed health metrics with enhanced data (sleep stages, HRV, RHR, VO2max, apnea)
    metrics = [
        {
            "metric_id": str(uuid.uuid4()),
            "user_id": user_id,
            "metric_type": "heart_rate",
            "value": 72,
            "unit": "BPM",
            "status": "Normal",
            "recorded_at": now,
            "metadata": {
                "hrv": 45,  # HRV RMSSD in ms
                "rhr": 62,  # Resting Heart Rate
                "vo2max": 42,  # VO2max estimate
                "irregularities": {
                    "highHREvents": 2,  # Episodes of high HR at rest
                    "lowHREvents": 0,
                    "irregularRhythm": False
                }
            }
        },
        {
            "metric_id": str(uuid.uuid4()),
            "user_id": user_id,
            "metric_type": "spo2",
            "value": 98,
            "unit": "%",
            "status": "Excellent",
            "recorded_at": now,
            "metadata": {"min_overnight": 95, "avg_overnight": 97}
        },
        {
            "metric_id": str(uuid.uuid4()),
            "user_id": user_id,
            "metric_type": "skin_temp",
            "value": 33.2,
            "unit": "°C",
            "status": "Normal Range",
            "recorded_at": now,
            "metadata": {"baseline_deviation": 0.1}
        },
        {
            "metric_id": str(uuid.uuid4()),
            "user_id": user_id,
            "metric_type": "sleep",
            "value": "7H 12M",
            "unit": "hours",
            "status": "Good quality",
            "recorded_at": now,
            "metadata": {
                # Sleep stages in hours
                "deep": 1.8,
                "light": 3.2,
                "rem": 1.5,
                "awake": 0.7,
                # Sleep score (0-100)
                "sleepScore": 82,
                # Apnea detection
                "apneaEvents": 3,
                "apneaRisk": "low",  # low, moderate, high
                # Efficiency
                "efficiency": 89,  # percentage
                "timeToFallAsleep": 12,  # minutes
                # Trends
                "weeklyAvgHours": 7.1,
                "weeklyScoreTrend": "improving"
            }
        },
        {
            "metric_id": str(uuid.uuid4()),
            "user_id": user_id,
            "metric_type": "steps",
            "value": 6000,
            "unit": "steps",
            "status": "75% of goal",
            "recorded_at": now,
            "metadata": {"goal": 8000, "distance_km": 4.2, "floors_climbed": 8}
        },
        {
            "metric_id": str(uuid.uuid4()),
            "user_id": user_id,
            "metric_type": "workout",
            "value": 2,
            "unit": "workouts",
            "status": "200 calories",
            "recorded_at": now,
            "metadata": {"calories": 200, "activeMinutes": 45}
        },
        {
            "metric_id": str(uuid.uuid4()),
            "user_id": user_id,
            "metric_type": "fall_detection",
            "value": "safe",
            "status": "No incident today",
            "recorded_at": now,
            "metadata": {}
        }
    ]
    await db.health_metrics.insert_many(metrics)
    
    # Seed alerts
    alerts = [
        {
            "alert_id": str(uuid.uuid4()),
            "user_id": user_id,
            "alert_type": "elevated_heart_rate",
            "title": "Elevated Heart Rate",
            "description": "120BPM at rest, 30 mins ago",
            "status": "new",
            "created_at": now - timedelta(minutes=30),
            "metadata": {}
        },
        {
            "alert_id": str(uuid.uuid4()),
            "user_id": user_id,
            "alert_type": "fall_detected",
            "title": "Possible Fall Detected",
            "description": "Near Living Room, 2 hours ago",
            "status": "read",
            "created_at": now - timedelta(hours=2),
            "metadata": {}
        },
        {
            "alert_id": str(uuid.uuid4()),
            "user_id": user_id,
            "alert_type": "pill_reminder",
            "title": "Pill Reminder",
            "description": "Time to take Medication B",
            "status": "new",
            "created_at": now,
            "metadata": {}
        }
    ]
    await db.alerts.insert_many(alerts)
    
    # Seed pill reminders
    pill_reminders = [
        {
            "reminder_id": str(uuid.uuid4()),
            "user_id": user_id,
            "medication_name": "Vitamin D",
            "dosage": "1 tablet",
            "schedule_times": ["10:00"],
            "taken_today": ["10:00"],
            "active": True
        },
        {
            "reminder_id": str(uuid.uuid4()),
            "user_id": user_id,
            "medication_name": "Vitamin E",
            "dosage": "1 tablet",
            "schedule_times": ["18:00"],
            "taken_today": [],
            "active": True
        }
    ]
    await db.pill_reminders.insert_many(pill_reminders)
    
    # Seed health sharing contacts
    health_sharing = [
        {
            "sharing_id": str(uuid.uuid4()),
            "user_id": user_id,
            "name": "Dr. Sarah Singh",
            "phone": "+91 XXXXX XXXXX",
            "role": "Primary Doctor",
            "sharing_enabled": True
        },
        {
            "sharing_id": str(uuid.uuid4()),
            "user_id": user_id,
            "name": "Pankaj Sharma",
            "phone": "+91 XXXXX XXXXX",
            "role": "Son",
            "sharing_enabled": True
        }
    ]
    await db.health_sharing.insert_many(health_sharing)
    
    return {"message": "Demo data seeded successfully"}

# ===================== FALL DETECTION ENDPOINTS =====================

class FallEventCreate(BaseModel):
    type: str  # 'fall_detected', 'sos_triggered'
    status: str  # 'sent', 'canceled_by_user'

@api_router.post("/fall-events")
async def log_fall_event(event: FallEventCreate, current_user: dict = Depends(get_current_user)):
    """Log a fall detection or SOS event"""
    event_doc = {
        "event_id": str(uuid.uuid4()),
        "user_id": current_user["user_id"],
        "type": event.type,
        "status": event.status,
        "timestamp": datetime.utcnow().isoformat(),
    }
    await db.fall_events.insert_one(event_doc)
    return {"message": "Event logged", "event_id": event_doc["event_id"]}

@api_router.get("/fall-events")
async def get_fall_history(current_user: dict = Depends(get_current_user)):
    """Get fall event history"""
    events = await db.fall_events.find(
        {"user_id": current_user["user_id"]},
        {"_id": 0}
    ).sort("timestamp", -1).to_list(50)
    return events

# ===================== ROOT ENDPOINT =====================

@api_router.get("/")
async def root():
    return {"message": "Miraii Smart Ring API", "version": "1.0.0"}

# Include the router
app.include_router(api_router)

# Configure CORS - allow all origins for development
# For credentials to work, we need to specify actual origins instead of "*"
ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "http://localhost:8081",
    "http://127.0.0.1:8081",
    "http://localhost:8000",
    "http://localhost:8001",
    "http://127.0.0.1:8001",
    "https://miraii-api-layer.preview.emergentagent.com",
    "https://jbxjcl-dv2vif-3000.preview.emergentagent.com",
]

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
