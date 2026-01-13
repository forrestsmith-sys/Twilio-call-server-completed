from flask import Flask, Response, request, send_from_directory
from twilio.twiml.voice_response import VoiceResponse, Dial
from twilio.twiml.messaging_response import MessagingResponse
from datetime import datetime
from zoneinfo import ZoneInfo
import os
import re
import requests
from requests.auth import HTTPBasicAuth
import logging

app = Flask(__name__)

# ======================
# LOGGING
# ======================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ======================
# CONFIG
# ======================
TWILIO_NUMBER = os.environ.get("TWILIO_NUMBER", "+19099705700")
TEAM_NUMBERS = [
    "+19097810829",
    "+19094377512",
    "+16502014457",
]
AGENT_PIN = os.environ.get("AGENT_PIN", "4321")

# ======================
# SECRETS
# ======================
TWILIO_ACCOUNT_SID = os.environ["TWILIO_ACCOUNT_SID"]
TWILIO_AUTH_TOKEN = os.environ["TWILIO_AUTH_TOKEN"]
ROCKETCHAT_WEBHOOK_URL = os.environ["ROCKETCHAT_WEBHOOK_URL"]

PUBLIC_BASE_URL = os.environ.get(
    "PUBLIC_BASE_URL",
    "https://twilio-call-server-completed-with.onrender.com"
)

# ======================
# STORAGE
# ======================
VOICEMAIL_DIR = "voicemails"
os.makedirs(VOICEMAIL_DIR, exist_ok=True)

# ======================
# HELPERS
# ======================
def is_business_hours():
    pacific = ZoneInfo("America/Los_Angeles")
    now = datetime.now(pacific)
    return now.weekday() < 5 and 8 <= now.hour < 17

def is_valid_phone(number):
    digits = re.sub(r"[^\d]", "", number or "")
    return len(digits) in (10, 11)

def spell_out_digits(number):
    return ", ".join(re.sub(r"[^\d]", "", number))

# ======================
# ENTRY
# ======================
@app.route("/voice", methods=["POST"])
def voice():
    r = VoiceResponse()
    r.say(
        "This call may be recorded for care coordination purposes. "
        "If this is a medical emergency, please hang up and dial 9 1 1. "
        "Thank you for calling Doctor Daliva's office.",
        voice="alice"
    )
    r.redirect("/menu")
    return Response(str(r), mimetype="text/xml")

# ======================
# MAIN MENU
# ======================
@app.route("/menu", methods=["POST"])
def menu():
    r = VoiceResponse()

    if not is_business_hours():
        r.redirect("/voicemail")
        return Response(str(r), mimetype="text/xml")

    g = r.gather(num_digits=1, action="/handle-menu", timeout=5)
    g.say(
        "Press 1 if you are an existing patient or provider. "
        "Press 2 if you are a prospective patient. "
        "Press 3 if you are staff.",
        voice="alice"
    )

    r.redirect("/voicemail")
    return Response(str(r), mimetype="text/xml")

@app.route("/handle-menu", methods=["POST"])
def handle_menu():
    r = VoiceResponse()
    choice = request.form.get("Digits")
    logger.info("Handle menu choice: %s", choice)

    if choice == "1":
        d = Dial(
            callerId=TWILIO_NUMBER,
            record="record-from-answer",
            recordingStatusCallback="/call-recording-complete",
            recordingStatusCallbackMethod="POST",
            action="/dial-complete",
            timeout=20
        )
        for n in TEAM_NUMBERS:
            d.number(n)
        r.append(d)

    elif choice == "2":
        r.redirect("/voicemail")

    elif choice == "3":
        g = r.gather(num_digits=4, action="/verify-pin", timeout=5)
        g.say("Please enter your four digit staff pin.", voice="alice")

    else:
        r.say("Invalid selection.", voice="alice")
        r.redirect("/menu")

    return Response(str(r), mimetype="text/xml")

# ======================
# DIAL COMPLETE → VOICEMAIL FALLBACK
# ======================
@app.route("/dial-complete", methods=["POST"])
def dial_complete():
    dial_status = request.form.get("DialCallStatus")
    logger.info("Dial complete with status: %s", dial_status)

    if dial_status in ("no-answer", "busy", "failed"):
        r = VoiceResponse()
        r.redirect("/voicemail")
        return Response(str(r), mimetype="text/xml")

    return ("", 204)

# ======================
# STAFF PIN
# ======================
@app.route("/verify-pin", methods=["POST"])
def verify_pin():
    r = VoiceResponse()
    digits = request.form.get("Digits", "")
    logger.info("Verify PIN attempt: %s", digits)

    if digits == AGENT_PIN:
        r.redirect("/agent-ivr")
    else:
        r.say("Invalid pin. Goodbye.", voice="alice")
        r.hangup()
    return Response(str(r), mimetype="text/xml")

# ======================
# STAFF OUTBOUND
# ======================
@app.route("/agent-ivr", methods=["POST"])
def agent_ivr():
    r = VoiceResponse()
    g = r.gather(finishOnKey="#", action="/confirm-number", timeout=10)
    g.say("Enter the patient phone number, followed by pound.", voice="alice")
    return Response(str(r), mimetype="text/xml")

@app.route("/confirm-number", methods=["POST"])
def confirm_number():
    r = VoiceResponse()
    number = request.form.get("Digits")
    logger.info("Confirm number digits: %s", number)

    if not is_valid_phone(number):
        r.say("Invalid number.", voice="alice")
        r.redirect("/agent-ivr")
        return Response(str(r), mimetype="text/xml")

    spoken = spell_out_digits(number)
    g = r.gather(num_digits=1, action=f"/dial-patient?num={number}", timeout=5)
    g.say(f"You entered {spoken}. Press 1 to confirm.", voice="alice")
    r.redirect("/agent-ivr")
    return Response(str(r), mimetype="text/xml")

@app.route("/dial-patient", methods=["POST"])
def dial_patient():
    r = VoiceResponse()
    num = request.args.get("num")
    logger.info("Dial patient: %s", num)

    d = Dial(
        callerId=TWILIO_NUMBER,
        record="record-from-answer",
        recordingStatusCallback="/call-recording-complete",
        recordingStatusCallbackMethod="POST",
        action="/dial-complete",
        timeout=20
    )
    d.number(num)
    r.append(d)
    return Response(str(r), mimetype="text/xml")

# ======================
# VOICEMAIL
# ======================
@app.route("/voicemail", methods=["POST"])
def voicemail():
    r = VoiceResponse()
    caller_number = request.form.get("From", "Unknown")

    # Pass the caller number through the recordingStatusCallback URL
    callback_url = f"/voicemail-complete?from={caller_number}"

    r.say(
        "Please leave a detailed message with your name and phone number. "
        "We will return your call as soon as possible.",
        voice="alice"
    )
    r.record(
        maxLength=180,
        playBeep=True,
        recordingStatusCallback=callback_url,
        recordingStatusCallbackMethod="POST"
    )
    r.say("Thank you. Goodbye.", voice="alice")
    r.hangup()
    return Response(str(r), mimetype="text/xml")

@app.route("/voicemail-complete", methods=["POST"])
def voicemail_complete():
    recording_url = request.form.get("RecordingUrl")

    # Prefer number passed in query param; fall back to form
    caller_number = request.args.get("from") or request.form.get("From", "Unknown")
    recording_duration = request.form.get("RecordingDuration")

    logger.info(
        "Voicemail complete: from=%s url=%s duration=%s",
        caller_number, recording_url, recording_duration
    )

    if not recording_url:
        logger.warning("Voicemail callback missing RecordingUrl")
        return ("", 204)

    filename = f"vm_{int(datetime.utcnow().timestamp())}.mp3"
    filepath = os.path.join(VOICEMAIL_DIR, filename)

    try:
        audio = requests.get(
            recording_url + ".mp3",
            auth=HTTPBasicAuth(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN),
            timeout=30
        )
    except Exception as e:
        logger.exception("Error downloading voicemail audio: %s", e)
        return ("", 204)

    if audio.status_code != 200:
        logger.error(
            "Failed to download voicemail audio. Status: %s Body: %s",
            audio.status_code,
            audio.text[:500]
        )
        return ("", 204)

    try:
        with open(filepath, "wb") as f:
            f.write(audio.content)
    except Exception as e:
        logger.exception("Error saving voicemail file: %s", e)
        return ("", 204)

    public_url = f"{PUBLIC_BASE_URL}/voicemails/{filename}"
    logger.info("Voicemail saved: %s (public: %s)", filepath, public_url)

    try:
        resp = requests.post(
            ROCKETCHAT_WEBHOOK_URL,
            json={
                "text": (
                    f"📞 **New Voicemail**\n"
                    f"From: {caller_number}\n\n"
                    f"🔊 Listen: {public_url}"
                )
            },
            timeout=30
        )
        if resp.status_code >= 400:
            logger.error(
                "Rocket.Chat webhook failed: %s %s",
                resp.status_code,
                resp.text[:500]
            )
    except Exception as e:
        logger.exception("Error posting to Rocket.Chat: %s", e)

    return ("", 204)

# ======================
# RECORDING CALLBACK
# ======================
@app.route("/call-recording-complete", methods=["POST"])
def call_recording_complete():
    logger.info("Call recording callback: %s", dict(request.form))
    return ("", 204)

# ======================
# SERVE VOICEMAILS
# ======================
@app.route("/voicemails/<filename>")
def serve_voicemail(filename):
    return send_from_directory(VOICEMAIL_DIR, filename)

# ======================
# SMS
# ======================
@app.route("/sms", methods=["POST"])
def sms():
    r = MessagingResponse()
    r.message("Thanks for contacting Align Medicine.")
    return Response(str(r), mimetype="text/xml")


