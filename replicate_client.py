import os
import replicate
from dotenv import load_dotenv

load_dotenv()

REPLICATE_API_TOKEN = os.getenv("REPLICATE_API_TOKEN")

async def call_replicate(
    prompt: str,
    model: str = "prunaai/gpt-oss-120b-fast:e994aeeb46519a8ed196fe72650b4d522280dabd2b67129580d164088133f8ff",
    temperature: float = 0.7,
    max_tokens: int = 8000,
    system_prompt: str | None = None
) -> str | None:
    """
    Call Replicate's GPT-OSS-120B model for text generation.
    """
    
    if not REPLICATE_API_TOKEN:
        print("[REPLICATE ERROR] Missing REPLICATE_API_TOKEN in .env")
        return None
    
    try:
        os.environ["REPLICATE_API_TOKEN"] = REPLICATE_API_TOKEN
        
        input_data = {
            "prompt": prompt,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        
        if system_prompt:
            input_data["system_prompt"] = system_prompt
        
        print(f"[REPLICATE] Calling {model} with prompt: {prompt[:100]}...")
        
        output = replicate.run(model, input=input_data)
        
        if hasattr(output, '__iter__'):
            response = "".join(output)
        else:
            response = str(output)
        
        print(f"[REPLICATE] Response length: {len(response)} chars")
        return response.strip()
    
    except Exception as e:
        print(f"[REPLICATE ERROR] {e}")
        return None
