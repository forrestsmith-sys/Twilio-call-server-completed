from flask import Flask, Response, request, send_from_directory
from twilio.twiml.voice_response import VoiceResponse, Dial
from twilio.twiml.messaging_response import MessagingResponse
from datetime import datetime
from zoneinfo import ZoneInfo
from functools import wraps
import os
import re
import requests
from requests.auth import HTTPBasicAuth

app = Flask(__name__)

# ======================
# CONFIG
# ======================
TWILIO_NUMBER = "+19099705700"
TEAM_NUMBERS = ["+19097810829", "+19094377512", "+16502014457"]
AGENT_PIN = os.environ.get("AGENT_PIN", "4321")

TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN")
ROCKETCHAT_WEBHOOK_URL = os.environ.get("ROCKETCHAT_WEBHOOK_URL")
PUBLIC_BASE_URL = os.environ.get(
    "PUBLIC_BASE_URL", "https://twilio-call-server-completed-with.onrender.com"
)

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
# INCOMING CALL
# ======================
@app.route("/voice", methods=["POST"])
def voice():
    r = VoiceResponse()
    r.say(
        "This call may be recorded for quality and training purposes. "
        "If this is a medical emergency, please hang up and dial 9 1 1.",
        voice="alice",
    )
    r.redirect("/patient-entry")
    return Response(str(r), mimetype="text/xml")


# ======================
# PATIENT MENU
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
        voice="alice",
    )
    r.redirect("/voicemail")
    return Response(str(r), mimetype="text/xml")


@app.route("/handle-menu", methods=["POST"])
def handle_menu():
    r = VoiceResponse()
    choice = request.form.get("Digits")

    if choice == "1":
        d = Dial(
            callerId=TWILIO_NUMBER,
            record="record-from-answer",
            recordingStatusCallback="/recording-complete",
            recordingStatusCallbackMethod="POST",
        )
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
# STAFF OUTBOUND FLOW
# ======================
@app.route("/agent-ivr", methods=["POST"])
def agent_ivr():
    r = VoiceResponse()
    g = r.gather(finishOnKey="#", action="/confirm-number")
    g.say("Enter the patient phone number, followed by pound.", voice="alice")
    return Response(str(r), mimetype="text/xml")


@app.route("/confirm-number", methods=["POST"])
def confirm_number():
    r = VoiceResponse()
    number = request.form.get("Digits")
    if not is_valid_phone(number):
        r.say("Invalid number.", voice="alice")
        r.redirect("/agent-ivr")
        return Response(str(r), mimetype="text/xml")

    spoken = spell_out_digits(number)
    g = r.gather(num_digits=1, action=f"/dial-patient?num={number}")
    g.say(f"You entered {spoken}. Press 1 to confirm.", voice="alice")
    r.redirect("/agent-ivr")
    return Response(str(r), mimetype="text/xml")


@app.route("/dial-patient", methods=["POST"])
def dial_patient():
    r = VoiceResponse()
    num = request.args.get("num")
    d = Dial(
        callerId=TWILIO_NUMBER,
        record="record-from-answer",
        recordingStatusCallback="/recording-complete",
        recordingStatusCallbackMethod="POST",
    )
    d.number(num, url="/patient-recording-disclosure")
    r.append(d)
    return Response(str(r), mimetype="text/xml")


@app.route("/patient-recording-disclosure", methods=["POST"])
def patient_recording_disclosure():
    r = VoiceResponse()
    r.say("This call may be recorded.", voice="alice")
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
        transcribe=False,
        action="/voicemail-recording-ready",
    )
    return Response(str(r), mimetype="text/xml")


# ======================
# VOICEMAIL PROCESSING & ROCKET.CHAT
# ======================
@app.route("/voicemail-recording-ready", methods=["POST"])
def voicemail_recording_ready():
    recording_url = request.form.get("RecordingUrl")
    recording_sid = request.form.get("RecordingSid")
    duration = request.form.get("RecordingDuration", "unknown")

    filename = f"vm_{recording_sid}.mp3"
    filepath = os.path.join(VOICEMAIL_DIR, filename)

    # Download recording from Twilio
    audio = requests.get(
        recording_url + ".mp3",
        auth=HTTPBasicAuth(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN),
    )
    with open(filepath, "wb") as f:
        f.write(audio.content)

    # Public URL for Rocket.Chat
    public_url = f"{PUBLIC_BASE_URL}/voicemails/{filename}"

    # Send message to Rocket.Chat
    try:
        requests.post(
            ROCKETCHAT_WEBHOOK_URL,
            json={
                "text": (
                    "📞 **New Voicemail**\n\n"
                    f"Duration: {duration} seconds\n"
                    f"🔊 {public_url}"
                )
            },
            timeout=5,
        )
    except Exception as e:
        print("Failed to send Rocket.Chat message:", e)

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


# ======================
# START SERVER
# ======================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 3000)))

