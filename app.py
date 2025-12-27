from flask import Flask, Response, request
from twilio.twiml.voice_response import VoiceResponse, Dial
from twilio.twiml.messaging_response import MessagingResponse
from datetime import datetime
from zoneinfo import ZoneInfo
import os

app = Flask(__name__)

# ======================
# CONFIG
# ======================
TWILIO_NUMBER = "+19099705700"

TEAM_NUMBERS = [
    "+19097810829",   # Diane
    "+19094377512",   # Amy
    "+16502014457",   # Mariza
]

AGENT_PIN = "4321"  # move to env/db later


# ======================
# BUSINESS + HOLIDAY HOURS
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
# MAIN ENTRY (AGENT / PATIENT ROUTING)
# ======================
@app.route("/voice", methods=["POST"])
def voice():
    response = VoiceResponse()
    from_number = request.form.get("From")

    # Known agent → no PIN
    if from_number in TEAM_NUMBERS:
        response.redirect("/agent-ivr")
        return Response(str(response), mimetype="text/xml")

    # Unknown number → optional staff PIN
    gather = response.gather(
        num_digits=4,
        action="/verify-agent-pin",
        method="POST",
        timeout=5
    )
    gather.say(
        "If you are a staff member, please enter your four digit pin now. "
        "Otherwise, please stay on the line.",
        voice="alice"
    )

    response.redirect("/patient-entry")
    return Response(str(response), mimetype="text/xml")


# ======================
# VERIFY AGENT PIN
# ======================
@app.route("/verify-agent-pin", methods=["POST"])
def verify_agent_pin():
    response = VoiceResponse()
    pin = request.form.get("Digits")

    if pin == AGENT_PIN:
        response.redirect("/agent-ivr")
    else:
        response.say("Invalid pin. Goodbye.", voice="alice")
        response.hangup()

    return Response(str(response), mimetype="text/xml")


# ======================
# PATIENT ENTRY (EXISTING LOGIC)
# ======================
@app.route("/patient-entry", methods=["POST"])
def patient_entry():
    response = VoiceResponse()

    if not is_business_hours():
        response.say(
            "If this is an emergency please call 9 1 1 or go to the emergency room. "
            "You have reached Doctor Daliva's office. "
            "We are currently closed. Please leave a message.",
            voice="alice"
        )
        response.redirect("/voicemail")
        return Response(str(response), mimetype="text/xml")

    gather = response.gather(
        num_digits=1,
        action="/handle-menu",
        method="POST",
        timeout=5
    )
    gather.say(
        "Thank you for calling Doctor Daliva's office. "
        "If you are an existing patient, a pharmacist, or calling from a provider's office, press 1. "
        "If you are a prospective patient, press 2.",
        voice="alice"
    )

    response.redirect("/voicemail")
    return Response(str(response), mimetype="text/xml")


# ======================
# PATIENT MENU
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
# AGENT IVR → PATIENT ID
# ======================
@app.route("/agent-ivr", methods=["POST"])
def agent_ivr():
    response = VoiceResponse()
    gather = response.gather(
        finishOnKey="#",
        action="/dial-patient",
        method="POST"
    )
    gather.say(
        "Please enter the patient I D followed by the pound key.",
        voice="alice"
    )
    return Response(str(response), mimetype="text/xml")


# ======================
# DIAL PATIENT (RECORDED)
# ======================
@app.route("/dial-patient", methods=["POST"])
def dial_patient():
    response = VoiceResponse()
    patient_id = request.form.get("Digits")

    # TODO: Replace with real lookup
    patient_phone = "+15551234567"

    dial = Dial(
        callerId=TWILIO_NUMBER,
        record="record-from-answer",
        recordingStatusCallback="/recording-complete"
    )

    # Patient-only disclosure
    dial.number(
        patient_phone,
        url="/patient-recording-disclosure"
    )

    response.append(dial)
    return Response(str(response), mimetype="text/xml")


# ======================
# PATIENT RECORDING DISCLOSURE
# ======================
@app.route("/patient-recording-disclosure", methods=["POST"])
def patient_recording_disclosure():
    response = VoiceResponse()
    response.say(
        "This call may be recorded for quality and training purposes.",
        voice="alice"
    )
    return Response(str(response), mimetype="text/xml")


# ======================
# RECORDING CALLBACK
# ======================
@app.route("/recording-complete", methods=["POST"])
def recording_complete():
    # Save RecordingSid, CallSid, Duration, etc.
    return ("", 204)


# ======================
# VOICEMAIL
# ======================
@app.route("/voicemail", methods=["POST"])
def voicemail():
    response = VoiceResponse()
    response.say(
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


