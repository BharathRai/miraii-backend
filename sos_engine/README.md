# SOS / Fall Detection Engine

## Overview
This folder is the integration point for the SOS and fall detection algorithms.

## Expected Structure
When SOS engine files are delivered, place them here:
```
sos_engine/
├── __init__.py
├── detector.py       # Main fall detection logic
├── processor.py      # Sensor data processing
├── alerts.py         # Alert generation and escalation
└── models/           # ML models for detection
```

## Required Functions

### detector.py
```python
def detect_fall(sensor_data: dict) -> dict:
    """
    Analyze sensor data for fall detection.
    
    Args:
        sensor_data: {
            "accelerometer": {"x": float, "y": float, "z": float},
            "gyroscope": {"x": float, "y": float, "z": float},
            "timestamp": int
        }
    
    Returns:
        {
            "fall_detected": bool,
            "confidence": float,
            "fall_type": str  # 'hard', 'soft', 'trip', etc.
        }
    """
    pass

def process_sensor_event(event: dict) -> dict:
    """
    Process raw sensor event for anomaly detection.
    """
    pass

def calculate_risk_level(vitals: dict) -> str:
    """
    Calculate health risk level from vitals.
    Returns: 'low', 'medium', 'high', 'critical'
    """
    pass
```

## Integration
Once files are in place, update `/app/backend/routers/sos.py`:
```python
from sos_engine.detector import detect_fall, process_sensor_event
SOS_ENGINE_AVAILABLE = True
```

## Alert Flow
1. Sensor data received from ring/app
2. Fall detection algorithm analyzes data
3. If fall detected → trigger SOS
4. Send notifications via EmailService
5. Store incident in database
6. Wait for acknowledgment from caregivers
