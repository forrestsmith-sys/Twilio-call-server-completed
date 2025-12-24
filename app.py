from flask import Flask, Response, request
from twilio.twiml.voice_response import VoiceResponse, Dial
from twilio.twiml.messaging_response import MessagingResponse
from datetime import datetime
from zoneinfo import ZoneInfo
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
# BUSINESS + HOLIDAY HOURS CHECK (PST, DST-SAFE)
# ======================
def is_business_hours():
    pacific = ZoneInfo("America/Los_Angeles")
    now = datetime.now(pacific)

    weekday = now.weekday()  # Monday=0, Sunday=6
    hour = now.hour
    month = now.month
    day = now.day

    # Weekend
    if weekday >= 5:
        return False

    # ---- CHRISTMAS HOLIDAYS ----

    # Christmas Eve – Dec 24 (closed after 2 PM)
    if month == 12 and day == 24:
        return hour < 14

    # Christmas Day – Dec 25 (closed all day)
    if month == 12 and day == 25:
        return False

    # Day after Christmas – Dec 26 (closed after 2 PM)
    if month == 12 and day == 26:
        return hour < 14

    # ---- NORMAL BUSINESS HOURS ----
    return 8 <= hour < 17


# ======================
# MAIN PHONE ENTRY
# ======================
@app.route("/voice", methods=["POST"])
def voice_menu():
    response = VoiceResponse()

    if not is_business_hours():
        response.say(
            "If this is a emergency please call 911 or go to the emergency room. You have reached Doctor Daliva's office. "
            "Our office hours are Monday through Friday, 8 A M to 5 P M Pacific Time. "
            "We are currently closed for after hours or a holiday. "
            "Please leave a message and we will return your call on the next business day.",
            voice="alice"
        )
        response.redirect("/voicemail")
        return Response(str(response), mimetype="text/xml")

    # Business hours → menu
    gather = response.gather(
        num_digits=1,
        action="/handle-menu",
        method="POST",
        timeout=5
    )

    gather.say(
        "Thank you for calling Doctor Daliva's office. "
        "Our office hours are Monday through Friday, 8 A M to 5 P M Pacific Time. "
        "If you are an existing patient, a pharmacist, or calling from a provider's office, press 1. "
        "If you are a prospective patient, press 2.",
        voice="alice"
    )

    response.redirect("/voicemail")
    return Response(str(response), mimetype="text/xml")


# ======================
# HANDLE MENU SELECTION
# ======================
@app.route("/handle-menu", methods=["POST"])
def handle_menu():
    response = VoiceResponse()
    choice = request.form.get("Digits")

    if choice == "1":
        dial = Dial(
            timeout=20,
            callerId=TWILIO_NUMBER,
            action="/voicemail",
            method="POST"
        )

        for number in TEAM_NUMBERS:
            dial.number(number)

        response.append(dial)

    elif choice == "2":
        response.redirect("/voicemail")

    else:
        response.say("Invalid selection.", voice="alice")
        response.redirect("/voice")

    return Response(str(response), mimetype="text/xml")


# ======================
# VOICEMAIL
# ======================
@app.route("/voicemail", methods=["POST"])
def voicemail():
    response = VoiceResponse()
    dial_status = request.form.get("DialCallStatus", "")

    if dial_status in ("no-answer", "busy", "failed", "canceled", ""):
        response.say(
            "If this is a medical emergency, please hang up and dial 9 1 1. "
            "You have reached Doctor Daliva's office. "
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
    else:
        response.hangup()

    return Response(str(response), mimetype="text/xml")


@app.route("/voicemail-complete", methods=["POST"])
def voicemail_complete():
    response = VoiceResponse()
    response.say("Thank you. Goodbye.", voice="alice")
    response.hangup()
    return Response(str(response), mimetype="text/xml")


# ======================
# SMS
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

