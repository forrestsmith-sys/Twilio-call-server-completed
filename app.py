from flask import Flask, Response, request
from twilio.twiml.voice_response import VoiceResponse, Dial
from twilio.twiml.messaging_response import MessagingResponse
import os

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
        action="/voicemail",   # Always goes to voicemail if Dial ends
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

    # Always go to voicemail after Dial
    response.say(
        "If this is a medical emergency, please hang up and dial 911. "
        "You have reached Doctor Daliva's office. "
        "Our office hours are Monday through Friday, 8 AM to 5 PM. "
        "Please leave a detailed message with your name and callback number.",
        voice="alice"
    )

    response.record(
        maxLength=120,
        playBeep=True,
        action="/voicemail-complete",
        method="POST"
    )

    response.say("Thank you. Goodbye.", voice="alice")
    response.hangup()

    return Response(str(response), mimetype="text/xml")


@app.route("/voicemail-complete", methods=["POST"])
def voicemail_complete():
    response = VoiceResponse()
    response.say("Your message has been recorded. Goodbye.", voice="alice")
    response.hangup()
    return Response(str(response), mimetype="text/xml")


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
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 3000))
    app.run(host="0.0.0.0", port=port)

