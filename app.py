from flask import Flask, Response, request, abort, send_from_directory
from twilio.twiml.voice_response import VoiceResponse, Dial
from flask import Flask, Response, request, abort, send_from_directory
from twilio.twiml.voice_response import VoiceResponse, Dial
from twilio.twiml.messaging_response import MessagingResponse
from datetime import datetime
from zoneinfo import ZoneInfo
import os
import re
import requests
from requests.auth import HTTPBasicAuth

app = Flask(__name__)

# ======================
# CONFIG
# ======================
TWILIO_NUMBER = os.environ.get("TWILIO_NUMBER")
TEAM_NUMBERS = os.environ.get("TEAM_NUMBERS", "").split(",")  # comma-separated numbers
AGENT_PIN = os.environ.get("AGENT_PIN", "4321")

# ======================
# SECRETS (ENV VARS ONLY)
# ======================
TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN")
ROCKETCHAT_WEBHOOK_URL = os.environ.get("ROCKETCHAT_WEBHOOK_URL")
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL")  # e.g., "https://your-app.onrender.com"

# ======================
# VOICEMAIL STORAGE
# ======================
VOICEMAIL_DIR = "voicemails"
os.makedirs(VOICEMAIL_DIR, exist_ok=True)

# ======================
# HELPERS
# ======================
PHONE_RE = re.compile(r"^\+?1?\d{10}$")

def is_valid_phone(number):
    digits = re.sub(r"[^\d]", "", number or "")
    return len(digits) in (10, 11)

def spell_out_digits(number):
    digits = re.sub(r"[^\d]", "", number)
    return ", ".join(digits)

def is_business_hours():
    pacific = ZoneInfo("America/Los_Angeles")
    now = datetime.now(pacific)
    return now.weekday() < 5 and 8 <= now.hour < 17

# ======================
# LOGGING
# ======================
@app.before_request
def log_request_info():
    print(f"Incoming {request.method} request to {request.url}")
    print(f"Form data: {request.form}")

# ======================
# INCOMING CALL
# ======================
@app.route("/voice", methods=["POST"])
def voice():
    r = VoiceResponse()
    r.say(
        "This call may be recorded for quality and training purposes. "
        "If this is a medical emergency, please hang up and dial 9 1 1.",
        voice="alice"
    )
    r.redirect("/patient-entry")
    return Response(str(r), mimetype="text/xml")

# ======================
# MAIN MENU
# ======================
@app.route("/patient-entry", methods=["POST"])
def patient_entry():
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
    if choice == "1":
        d = Dial(callerId=TWILIO_NUMBER, record="record-from-answer",
                 recordingStatusCallback="/recording-complete",
                 recordingStatusCallbackMethod="POST")
        for n in TEAM_NUMBERS:
            d.number(n)
        r.append(d)
    elif choice == "2":
        r.redirect("/voicemail")
    elif choice == "3":
        g = r.gather(num_digits=4, action="/verify-pin")
        g.say("Please enter your four digit staff pin.", voice="alice")
    else:
        r.say("Invalid selection.", voice="alice")
        r.redirect("/patient-entry")
    return Response(str(r), mimetype="text/xml")

# ======================
# STAFF PIN
# ======================
@app.route("/verify-pin", methods=["POST"])
def verify_pin():
    r = VoiceResponse()
    if request.form.get("Digits") == AGENT_PIN:
        r.redirect("/agent-ivr")
    else:
        r.say("Invalid pin. Goodbye.", voice="alice")
        r.hangup()
    return Response(str(r), mimetype="text/xml")

# ======================
# VOICEMAIL
# ======================
@app.route("/voicemail", methods=["POST"])
def voicemail():
    r = VoiceResponse()
    r.say("Please leave a message after the tone.", voice="alice")
    r.record(
        maxLength=180,
        playBeep=True,
        transcribe=True,
        transcribeCallback="/voicemail-transcription",
        action="/voicemail-complete"
    )
    return Response(str(r), mimetype="text/xml")

@app.route("/voicemail-complete", methods=["POST"])
def voicemail_complete():
    return ("", 204)

# ======================
# RECORDING CALLBACK
# ======================
@app.route("/recording-complete", methods=["POST"])
def recording_complete():
    return ("", 204)

# ======================
# VOICEMAIL TRANSCRIPTION + ROCKET.CHAT
# ======================
@app.route("/voicemail-transcription", methods=["POST"])
def voicemail_transcription():
    recording_url = request.form.get("RecordingUrl")
    transcription = request.form.get("TranscriptionText", "No transcription available")
    print(f"Received transcription: {transcription}, recording_url: {recording_url}")

    filename = f"vm_{int(datetime.utcnow().timestamp())}.mp3"
    filepath = os.path.join(VOICEMAIL_DIR, filename)

    # Download recording
    try:
        audio = requests.get(
            recording_url + ".mp3",
            auth=HTTPBasicAuth(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        )
        with open(filepath, "wb") as f:
            f.write(audio.content)
    except Exception as e:
        print(f"Error downloading recording: {e}")

    public_url = f"{PUBLIC_BASE_URL}/voicemails/{filename}"
    print(f"Public URL for Rocket.Chat: {public_url}")

    # Send to Rocket.Chat
    try:
        resp = requests.post(
            ROCKETCHAT_WEBHOOK_URL,
            json={"text": f"📞 **New Voicemail**\n\n📝 {transcription}\n\n🔊 {public_url}"},
            timeout=5
        )
        print(f"Rocket.Chat response: {resp.status_code} {resp.text}")
    except Exception as e:
        print(f"Error sending to Rocket.Chat: {e}")

    return ("", 204)

# ======================
# SERVE VOICEMAILS
# ======================
@app.route("/voicemails/<filename>", methods=["GET"])
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

# ======================
# START APP
# ======================
if __name__ == "__main__":
    required_envs = ["TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "ROCKETCHAT_WEBHOOK_URL", "PUBLIC_BASE_URL", "TWILIO_NUMBER"]
    missing = [e for e in required_envs if not os.environ.get(e)]
    if missing:
        print(f"Error: Missing required environment variables: {missing}")
        exit(1)

    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 3000)))
