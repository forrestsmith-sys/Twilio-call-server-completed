import os
import requests
from flask import Flask, request, Response, abort
from twilio.twiml.voice_response import VoiceResponse
from twilio.rest import Client

app = Flask(__name__)

# ----------------------------
# Environment Variables (Render)
# ----------------------------
TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN")
ROCKETCHAT_WEBHOOK_URL = os.environ.get("ROCKETCHAT_WEBHOOK_URL")
BASE_URL = os.environ.get("BASE_URL")  # e.g. https://your-app.onrender.com

if not all([TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, ROCKETCHAT_WEBHOOK_URL, BASE_URL]):
    raise RuntimeError("Missing required environment variables")

twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

# ----------------------------
# Storage (Render-safe path)
# ----------------------------
VOICEMAIL_DIR = "/tmp/voicemails"
os.makedirs(VOICEMAIL_DIR, exist_ok=True)

# ----------------------------
# Twilio: Incoming Call
# ----------------------------
@app.route("/voice", methods=["POST"])
def voice():
    r = VoiceResponse()
    r.say("Please leave a message after the tone.", voice="alice")

    r.record(
        maxLength=180,
        playBeep=True,

        # ✅ REQUIRED
        recordingStatusCallback="/voicemail-recording-ready",
        recordingStatusCallbackMethod="POST",

        # optional
        transcribe=True,
        transcribeCallback="/voicemail-transcription"
    )

    return Response(str(r), mimetype="text/xml")


# ----------------------------
# Twilio: Recording Finished
# ----------------------------
@app.route("/voicemail-recording-ready", methods=["POST"])
def voicemail_recording_ready():
    recording_sid = request.form.get("RecordingSid")
    recording_url = request.form.get("RecordingUrl")
    call_sid = request.form.get("CallSid")

    if not recording_sid or not recording_url:
        abort(400)

    # Twilio recordings need auth + .mp3
    audio_url = f"{recording_url}.mp3"
    filename = f"{recording_sid}.mp3"
    filepath = os.path.join(VOICEMAIL_DIR, filename)

    # Download recording
    audio = requests.get(
        audio_url,
        auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN),
        timeout=15
    )

    if audio.status_code != 200:
        abort(500)

    with open(filepath, "wb") as f:
        f.write(audio.content)

    public_link = f"{BASE_URL}/voicemail/{filename}"

    # Send to Rocket.Chat
    payload = {
        "text": (
            "📞 **New Voicemail Received**\n\n"
            f"• Call SID: `{call_sid}`\n"
            f"• Recording: {public_link}"
        )
    }

    rc = requests.post(ROCKETCHAT_WEBHOOK_URL, json=payload, timeout=10)

    if rc.status_code not in (200, 204):
        abort(500)

    return ("", 204)


# ----------------------------
# Serve Voicemail Audio
# ----------------------------
@app.route("/voicemail/<filename>")
def serve_voicemail(filename):
    path = os.path.join(VOICEMAIL_DIR, filename)

    if not os.path.exists(path):
        abort(404)

    with open(path, "rb") as f:
        return Response(f.read(), mimetype="audio/mpeg")


# ----------------------------
# Optional: Transcription Callback
# ----------------------------
@app.route("/voicemail-transcription", methods=["POST"])
def voicemail_transcription():
    transcription = request.form.get("TranscriptionText", "")
    if transcription:
        requests.post(
            ROCKETCHAT_WEBHOOK_URL,
            json={"text": f"📝 **Voicemail Transcription**:\n{transcription}"}
        )
    return ("", 204)


# ----------------------------
# Health Check
# ----------------------------
@app.route("/")
def index():
    return "Twilio voicemail server running"

