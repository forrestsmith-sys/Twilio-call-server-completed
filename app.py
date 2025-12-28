from flask import Flask, Response, request, abort
from twilio.twiml.voice_response import VoiceResponse, Dial
from twilio.twiml.messaging_response import MessagingResponse
from datetime import datetime
from zoneinfo import ZoneInfo
from functools import wraps
import os
import re

app = Flask(__name__)

# ======================
# CONFIG
# ======================
TWILIO_NUMBER = "+19099705700"
TEAM_NUMBERS = [
    "+19097810829",  # Diane
    "+19094377512",  # Amy
    "+16502014457",  # Mariza
]
AGENT_PIN = os.environ.get("AGENT_PIN", "4321")  # General PIN
TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN")  # for request validation

# ======================
# SIMPLE PHONE VALIDATION (US-CENTRIC)
# ======================
PHONE_RE = re.compile(r"^\+?1?\d{10}$")  # e.g., +1XXXXXXXXXX or 10 digits

def is_valid_phone(number: str) -> bool:
    if not number:
        return False
    # strip non-digits except leading +
    number = number.strip()
    digits = re.sub(r"[^\d+]", "", number)
    return bool(PHONE_RE.match(digits))

# ======================
# SPELL OUT DIGITS HELPER
# ======================
def spell_out_digits(number: str) -> str:
    """Convert a string of digits into a comma-separated string for Twilio <Say>"""
    return ", ".join(number)

# ==========

