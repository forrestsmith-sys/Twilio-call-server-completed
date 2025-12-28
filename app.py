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
    number = number.strip()
    digits = re.sub(r"[^\d+]", "", number)
    return bool(PHONE_RE.match(digits))

# ======================
# SPELL OUT DIGITS HELPER
# ======================
def spell_out_digits(number: str) -> str:
    """Convert a string of digits into a comma-separated string for Twilio <Say>"""
    return ", ".join(number)

# ======================
# OPTIONAL: VALIDATE TWILIO REQUESTS
# ======================
def validate_twilio_request(f):
    if not TWILIO_AUTH_TOKEN:
        return f  # dev mode
    from twilio.request_validator import RequestValidator

    @wraps(f)
    def decorated_function(*args, **kwargs):
        validator = RequestValidator(TWILIO_AUTH_TOKEN)
        signature = request.headers.get("X-Twilio-Signature", "")
        url = request.url
        form = request.form.to_dict(flat=True)
        if not validator.validate(url, form, signature):
            return abort(403)
        return f(*args, **kwargs)

    return decorated_function

# ======================
# BUSINESS HOURS
# ======================
def is_business_hours():
    pacific = ZoneInfo("America/Los_Angeles")
    now = datetime.now(pacific)
    weekday = now.weekday()
    hour = now.hour
    month = now.month
    day = now.day

    if weekday >= 5:
        return False
    if month == 12 and day == 24:
        return hour < 14
    if month == 12 and day == 25:
        return False
    if month == 12 and day == 26:
        return hour < 14
    return 8 <= hour < 17

# ======================
# CALL LOG (IN-MEMORY)
# ======================
CALL_LOG = []

def log_call(agent_number, patient_number, call_sid=None, duration=None):
    CALL_LOG.append({
        "agent": agent_number,
        "patient": patient_number,
        "timestamp": datetime.now().isoformat(),
        "call_sid": call_sid,
        "duration": duration
    })
    print("Logged call:", CALL_LOG[-1])

# ======================
# MAIN ENTRY (INCOMING CALL)
# ======================
@app.route("/voice", methods=["POST"])
@validate_twilio_request
def voice():
    response = VoiceResponse()
    from_number = request.form.get("From")

    # Announce recording and emergency instructions
    response.say(
        "This call may be recorded for quality and training purposes. "
        "If this is an emergency, please hang up and call 9 1 1.",
        voice="alice"
    )

    # Team members go straight to agent IVR
    if from_number in TEAM_NUMBERS:
        response.redirect("/agent-ivr")
        return Response(str(response), mimetype="text/xml")

    # Present main menu: 1 = existing, 2 = prospective, 3 = staff
    gather = response.gather(
        num_digits=1,
        action="/handle-menu",
        method="POST",
        timeout=5,
    )
    gather.say(
        "Thank you for calling Doctor Daliva's office. "
        "If you are an existing patient, a pharmacist, or calling from a provider's office, press 1. "
        "If you are a prospective patient, press 2. "
        "If you are a staff member, press 3.",
        voice="alice"
    )

    response.redirect("/voicemail")
    return Response(str(response), mimetype="text/xml")

# ======================
# HANDLE MENU
# ======================
@app.route("/handle-menu", methods=["POST"])
@validate_twilio_request
def handle_menu():
    response = VoiceResponse()
    choice = request.form.get("Digits")

    if choice == "1":  # Existing patient
        dial = Dial(
            timeout=20,
            callerId=TWILIO_NUMBER,
            record="record-from-answer",
            recordingStatusCallback="/recording-complete",
            recordingStatusCallbackMethod="POST"
        )
        for number in TEAM_NUMBERS:
            dial.number(number)
        response.append(dial)
    elif choice == "2":  # Prospective patient
        response.redirect("/voicemail")
    elif choice == "3":  # Staff PIN
        gather = response.gather(
            num_digits=4,
            action="/verify-agent-pin",
            method="POST",
            timeout=5
        )
        gather.say("Please enter your four digit PIN now.", voice="alice")
        response.redirect("/voice")
    else:
        response.say("Invalid selection.", voice="alice")
        response.redirect("/voice")

    return Response(str(response), mimetype="text/xml")

# ======================
# VERIFY PIN
# ======================
@app.route("/verify-agent-pin", methods=["POST"])
@validate_twilio_request
def verify_agent_pin():
    response = VoiceResponse()
    pin = request.form.get("Digits")
    from_number = request.form.get("From")

    if pin == AGENT_PIN:
        response.redirect("/agent-ivr")
    else:
        response.say("Invalid pin. Goodbye.", voice="alice")
        response.hangup()
        print(f"Failed PIN attempt from {from_number} at {datetime.now()}")
    return Response(str(response), mimetype="text/xml")

# ======================
# AGENT IVR
# ======================
@app.route("/agent-ivr", methods=["POST"])
@validate_twilio_request
def agent_ivr():
    response = VoiceResponse()
    gather = response.gather(
        finishOnKey="#",
        action="/confirm-number",
        method="POST",
    )
    gather.say(
        "Please enter the patient’s phone number followed by the pound key.",
        voice="alice",
    )
    return Response(str(response), mimetype="text/xml")

# ======================
# CONFIRM PHONE NUMBER
# ======================
@app.route("/confirm-number", methods=["POST"])
@validate_twilio_request
def confirm_number():
    response = VoiceResponse()
    patient_phone = request.form.get("Digits")
    from_number = request.form.get("From")

    if not is_valid_phone(patient_phone):
        response.say("Invalid phone number. Goodbye.", voice="alice")
        response.hangup()
        return Response(str(response), mimetype="text/xml")

    spoken_number = spell_out_digits(patient_phone)

    gather = response.gather(
        num_digits=1,
        action=f"/confirm-number-choice?patient_phone={patient_phone}",
        method="POST",
        timeout=5,
    )
    gather.say(
        f"You entered the following digits: {spoken_number}. "
        "Press 1 to confirm or 2 to re-enter.",
        voice="alice"
    )
    response.redirect("/agent-ivr")
    return Response(str(response), mimetype="text/xml")

# ======================
# HANDLE CONFIRM / RE-ENTER
# ======================
@app.route("/confirm-number-choice", methods=["POST"])
@validate_twilio_request
def confirm_number_choice():
    response = VoiceResponse()
    choice = request.form.get("Digits")
    patient_phone = request.args.get("patient_phone")

    if choice == "1":
        response.redirect(f"/dial-patient?patient_phone={patient_phone}")
    elif choice == "2":
        response.redirect("/agent-ivr")
    else:
        response.say("Invalid selection.", voice="alice")
        response.redirect("/agent-ivr")
    return Response(str(response), mimetype="text/xml")

# ======================
# DIAL PATIENT
# ======================
@app.route("/dial-patient", methods=["POST"])
@validate_twilio_request
def dial_patient():
    response = VoiceResponse()
    patient_phone = request.args.get("patient_phone")
    agent_number = request.form.get("From")

    if not is_valid_phone(patient_phone):
        response.say("Invalid phone number. Goodbye.", voice="alice")
        response.hangup()
        return Response(str(response), mimetype="text/xml")

    dial = Dial(
        callerId=TWILIO_NUMBER,
        record="record-from-answer",
        recordingStatusCallback="/recording-complete",
        recordingStatusCallbackMethod="POST",
    )
    dial.number(patient_phone, url="/patient-recording-disclosure", method="POST")
    response.append(dial)

    log_call(agent_number, patient_phone)
    return Response(str(response), mimetype="text/xml")

# ======================
# PATIENT RECORDING DISCLOSURE
# ======================
@app.route("/patient-recording-disclosure", methods=["POST"])
@validate_twilio_request
def patient_recording_disclosure():
    response = VoiceResponse()
    response.say(
        "This call may be recorded for quality and training purposes.",
        voice="alice",
    )
    return Response(str(response), mimetype="text/xml")

# ======================
# RECORDING CALLBACK
# ======================
@app.route("/recording-complete", methods=["POST"])
@validate_twilio_request
def recording_complete():
    call_sid = request.form.get("CallSid")
    recording_sid = request.form.get("RecordingSid")
    call_duration = request.form.get("RecordingDuration")
    call_from = request.form.get("From")
    call_to = request.form.get("To")

    log_call(call_from, call_to, call_sid=recording_sid or call_sid, duration=call_duration)
    return ("", 204)

# ======================
# VOICEMAIL
# ======================
@app.route("/voicemail", methods=["POST"])
@validate_twilio_request
def voicemail():
    response = VoiceResponse()
    response.say(
        "Please leave a detailed message with your name and callback number.",
        voice="alice",
    )
    response.record(
        maxLength=120,
        playBeep=True,
        action="/voicemail-complete",
        method="POST",
    )
    response.say("Thank you. Goodbye.", voice="alice")
    return Response(str(response), mimetype="text/xml")

@app.route("/voicemail-complete", methods=["POST"])
@validate_twilio_request
def voicemail_complete():
    response = VoiceResponse()
    response.say("Thank you. Goodbye.", voice="alice")
    response.hangup()
    return Response(str(response), mimetype="text/xml")

# ======================
# SMS
# ======================
@app.route("/sms", methods=["POST"])
@validate_twilio_request
def sms():
    response = MessagingResponse()
    response.message(
        "Thanks for texting Align Medicine! We received your message and will respond shortly."
    )
    return Response(str(response), mimetype="text/xml")

# ======================
# START SERVER
# ======================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 3000))
    app.run(host="0.0.0.0", port=port)
