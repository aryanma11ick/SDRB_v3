import json
import os
from openai import OpenAI
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()
OPENAPI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAPI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.2")
client = OpenAI(api_key=OPENAPI_API_KEY)

PROMPT_PATH = Path("src/prompts/email_preprocessor.txt")


def preprocess_email_llm(raw_email: dict) -> dict:
    prompt = PROMPT_PATH.read_text()

    filled_prompt = prompt.replace(
        "<<<EMAIL_JSON>>>",
        json.dumps(raw_email, indent=2)
    )

    response = client.chat.completions.create(
        model=OPENAPI_MODEL,
        messages=[{"role": "user", "content": filled_prompt}],
        temperature=0
    )

    content = response.choices[0].message.content
    if content is None:
        raise RuntimeError("LLM returned empty content")
    
    content = content.strip()

    try:
        return json.loads(content)
    except json.JSONDecodeError:
        raise RuntimeError("LLM returned invalid JSON")
