from google import genai
from dotenv import load_dotenv
import os

load_dotenv()

client = genai.Client(api_key=os.getenv("OPENAI_API_KEY"))

response = client.models.generate_content(
    model="gemini-2.5-flash",
    contents="Say exactly this: LLM connection successful."
)

print(response.text)