import os
from openai import OpenAI
from dotenv import load_dotenv
from .configs import (
    SYSTEM_PROMPT, 
    OPENAI_MODEL, 
    OPENAI_TEMPERATURE, 
    OPENAI_MAX_TOKENS
)

load_dotenv()

class OpenAIService:
    def __init__(self):
        self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        self.system_prompt = SYSTEM_PROMPT

    def generate_copy(self, product_name: str, category: str, japanese_description: str) -> str:
        user_content = f"""
        Product Name: {product_name}
        Category: {category}
        Original Japanese Text:
        {japanese_description}
        """
        
        print("User Content: ", user_content)
        
        response = self.client.chat.completions.create(
            model=OPENAI_MODEL, 
            messages=[
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": user_content}
            ],
            temperature=OPENAI_TEMPERATURE,
            max_tokens=OPENAI_MAX_TOKENS
        )
        
        return response.choices[0].message.content
