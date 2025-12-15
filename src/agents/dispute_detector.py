import json
from pathlib import Path
from openai import OpenAI

client = OpenAI()

PROMPT_PATH = Path("src/prompts/dispute_detection.txt")


def detect_dispute(preprocessed_email: dict) -> dict:
    """
    Returns:
    {
      email_id,
      classification,
      confidence,
      reason
    }
    """

    prompt = PROMPT_PATH.read_text()

    filled_prompt = prompt.replace(
        "<<<EMAIL_JSON>>>",
        json.dumps(preprocessed_email, indent=2)
    )

    response = client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[{"role": "user", "content": filled_prompt}],
        temperature=0
    )

    content = response.choices[0].message.content.strip()

    try:
        result = json.loads(content)
    except json.JSONDecodeError:
        raise RuntimeError("Dispute detector returned invalid JSON")

    return {
        "email_id": preprocessed_email.get("email_id"),
        "classification": result["classification"],
        "confidence": result["confidence"],
        "reason": result["reason"]
    }
