"""First Sarvam AI call: synthesize one teacher line and save it as a .wav.

Run:
    set -a && . ./.env && set +a && python3 tools/sarvam_tts_test.py
"""
import os
import sys

from sarvamai import SarvamAI
from sarvamai.play import save

API_KEY = os.environ.get("SARVAM_API_KEY")
if not API_KEY:
    sys.exit("SARVAM_API_KEY is not set (did you source .env?)")

client = SarvamAI(api_subscription_key=API_KEY)

response = client.text_to_speech.convert(
    text="Namaste! Yeh ExamTricks ka AI teacher bol raha hai. Chalo ek fast trick seekhte hain.",
    language_code="hi-IN",
    model="bulbul:v3",
    speaker="ritu",
)

out_path = os.path.join(os.path.dirname(__file__), "..", "sarvam_test_output.wav")
save(response, out_path)
print(f"request_id: {response.request_id}")
print(f"audio chunks: {len(response.audios)}")
print(f"saved: {os.path.abspath(out_path)}")
