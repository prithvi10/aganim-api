import os
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from openai import OpenAI
from dotenv import load_dotenv
try:
    import truststore
    truststore.inject_into_ssl() # to connect through venv/proxy
except ImportError:
    pass # truststore not installed or not needed
except Exception as e:
    print(f"Warning: Truststore injection failed: {e}")



# 1. Setup
load_dotenv() # Load your .env file with API keys
app = FastAPI()

# Initialize OpenAI Client
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# 2. Define the Data Model
# This ensures the frontend sends exactly what we need
class RewriteRequest(BaseModel):
    product_name: str
    japanese_description: str
    category: str = "General Goods" # e.g., "Kitchenware", "Apparel"

# 3. The "System Prompt" (Your Secret Sauce)
SYSTEM_PROMPT = """
You are an expert American Direct-Response Copywriter.
Your goal is to take a factual Japanese product description and rewrite it 
into compelling, benefit-driven English marketing copy for a US Shopify store.

RULES:
- Tone: Sophisticated, warm, storytelling.
- Structure: 
  1. Catchy Headline (Under 10 words)
  2. The Story (Evoke emotion/origin)
  3. Key Features (Converted to Benefits)
  4. Care Instructions (If mentioned, make them friendly)
- NO "Japanglish" (awkward phrasing).
- NO made-up facts. Only use the info provided, but dramatize the value.
"""

# 4. The API Endpoint
@app.post("/api/generate-copy")
async def generate_copy(request: RewriteRequest):
    try:
        # Construct the user message
        user_content = f"""
        Product Name: {request.product_name}
        Category: {request.category}
        Original Japanese Text:
        {request.japanese_description}
        """
        print("User Content: ", user_content)
        # Call OpenAI (GPT-4o or GPT-4o-mini for speed/cost)
        response = client.chat.completions.create(
            model="gpt-4o-mini", 
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_content}
            ],
            temperature=0.7, # A little creative, but not hallucinating
            max_tokens=500
        )

        # Extract the text
        english_copy = response.choices[0].message.content

        return {
            "status": "success",
            "english_copy": english_copy
        }

    except Exception as e:
        print(f"Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# To run this: uvicorn main:app --reload