import os
from google import genai

api_key = os.environ.get("GOOGLE_API_KEY")
client = genai.Client(api_key=api_key)

print("Available Models:")
for m in client.models.list():
    if "gemini" in m.name.lower() and "vision" not in m.name.lower():
        print(f"- {m.name}")
