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
    response = VoiceResponse()

    dial = Dial(
        timeout=20,
        callerId=TWILIO_NUMBER,
        action="/voicemail",   # Twilio calls this if Dial ends
        method="POST"
    )

    for number in TEAM_NUMBERS:
        dial.number(number)

    response.append(dial)
    return Response(str(response), mimetype="text/xml")


# ======================
# VOICEMAIL
# ======================
@app.route("/voicemail", methods=["POST"])
def voicemail():
    response = VoiceResponse()

    response.say(
        "If this is a medical emergency, please hang up and dial 911. "
        "You have reached Doctor Daliva's office. "
        "Our office hours are Monday through Friday, 8 A M to 5 P M. "
        "Please leave a detailed message with your name and callback number after the beep.",
        voice="alice"
    )

    response.record(
        max_length=120,
        play_beep=True,
        recording_status_callback="/recording-status",
        recording_status_callback_method="POST"
    )

    response.say("Thank you. Goodbye.", voice="alice")
    response.hangup()
    return Response(str(response), mimetype="text/xml")


# ======================
# RECORDING STATUS CALLBACK
# ======================
@app.route("/recording-status", methods=["POST"])
def recording_status():
    recording_url = request.form.get("RecordingUrl")
    from_number = request.form.get("From")
    print(f"New voicemail from {from_number}: {recording_url}")
    # You can also store this in a database or send a notification
    return ("", 204)


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
