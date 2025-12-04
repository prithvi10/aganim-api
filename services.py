import os
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

class OpenAIService:
    def __init__(self):
        self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        self.system_prompt = """
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

    def generate_copy(self, product_name: str, category: str, japanese_description: str) -> str:
        user_content = f"""
        Product Name: {product_name}
        Category: {category}
        Original Japanese Text:
        {japanese_description}
        """
        
        print("User Content: ", user_content)
        
        response = self.client.chat.completions.create(
            model="gpt-4o-mini", 
            messages=[
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": user_content}
            ],
            temperature=0.7,
            max_tokens=500
        )
        
        return response.choices[0].message.content

