import os
from openai import OpenAI
from dotenv import load_dotenv
import httpx,truststore
from .configs import (
    SYSTEM_PROMPT, 
    OPENAI_MODEL, 
    OPENAI_TEMPERATURE, 
    OPENAI_MAX_TOKENS
)
from .logger import get_logger

logger = get_logger(__name__)

load_dotenv()
## For NETSKOPE ##
## TODO : Remove before going to PROD
# <--- 2. Create an SSL Context that uses your System/Corporate Certs
ssl_context = truststore.SSLContext(httpx.create_ssl_context().protocol)

# <--- 3. Create a custom HTTP client using that SSL context
http_client = httpx.Client(verify=ssl_context)

class OpenAIService:
    def __init__(self):
        self.client = OpenAI(
            api_key=os.getenv("OPENAI_API_KEY"),
            http_client=http_client
        )
        self.system_prompt = SYSTEM_PROMPT

    def generate_copy(self, product_name: str, category: str, japanese_description: str) -> str:
        user_content = f"""
        Product Name: {product_name}
        Category: {category}
        Original Japanese Text:
        {japanese_description}
        """
        
        logger.info(f"Rewriting description using AI for product: {product_name}")
        logger.debug(f"User Content: {user_content}")
        
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
