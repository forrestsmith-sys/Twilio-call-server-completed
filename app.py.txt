from flask import Flask, Response, request
from twilio.twiml.voice_response import VoiceResponse, Dial
from twilio.twiml.messaging_response import MessagingResponse

app = Flask(__name__)

# ===== CONFIG =====
TWILIO_NUMBER = "+19099705700"

TEAM_NUMBERS = [
    "+19097810829",   # Diane
    "+19094377512",   # Amy
    "+16502014457",   # Mariza
]
# ==================


# ======================
# INBOUND VOICE CALLS
# ======================
@app.route("/voice", methods=["POST"])
def voice():
    """
    First step: ring the team.
    After Dial finishes (no answer, busy, etc.), Twilio POSTs to /voicemail.
    """
    response = VoiceResponse()

    dial = Dial(
        timeout=20,
        callerId=TWILIO_NUMBER,
        action="/voicemail",   # Twilio will request this URL when Dial ends
        method="POST"
    )

    for number in TEAM_NUMBERS:
        dial.number(number)

    response.append(dial)

    return Response(str(response), mimetype="text/xml")


@app.route("/voicemail", methods=["POST"])
def voicemail():
    """
    Second step: this runs AFTER the Dial.
    Plays your message and records voicemail.
    """
    dial_status = request.form.get("DialCallStatus", "")

    # Optional: only go to voicemail on specific statuses
    # common: no-answer, busy, failed, canceled
    # If you want *always* voicemail after Dial, you can skip this if.
    if dial_status not in ("no-answer", "busy", "failed", "canceled", ""):
        # If someone actually answered and then hung up, just end the call.
        response = VoiceResponse()
        response.hangup()
        return Response(str(response), mimetype="text/xml")

    response = VoiceResponse()

    response.say(
        "If this is a medical emergency, please hang up and dial 9 1 1. "
        "You have reached Doctor Daliva's office. "
        "Our office hours are Monday through Friday, 8 A M to 5 P M. "
        "Please leave a detailed message with your name and callback number.",
        voice="alice"
    )

    # Record up to 120 seconds with a beep
    response.record(
        maxLength=120,
        playBeep=True
        # You can also add:
        # recordingStatusCallback="/recording-status",
        # recordingStatusCallbackMethod="POST"
    )

    response.say("Thank you. Goodbye.", voice="alice")
    response.hangup()

    return Response(str(response), mimetype="text/xml")


# Optional: handle recording callback if you want to log or notify
# @app.route("/recording-status", methods=["POST"])
# def recording_status():
#     # recording_url = request.form.get("RecordingUrl")
#     # from_number = request.form.get("From")
#     # Do something with the recording (store, notify, etc.)
#     return ("", 204)


# ======================
# SMS TEXT MESSAGES
# ======================
@app.route("/sms", methods=["POST"])
def sms():
    response = MessagingResponse()

    response.message(
        "Thanks for texting Align Medicine! We received your message and will respond shortly."
    )

    return Response(str(response), mimetype="text/xml")


# ======================
# START SERVER
# ======================
import os

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 3000))
    app.run(host="0.0.0.0", port=port)