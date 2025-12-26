import os
from openai import OpenAI
from dotenv import load_dotenv
import httpx,truststore
from src.main.config.configs import (
    SYSTEM_PROMPT, 
    OPENAI_MODEL, 
    OPENAI_TEMPERATURE, 
    OPENAI_MAX_TOKENS
)
from src.main.logging.logger import get_logger

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

    def generate_copy(self, product_name: str, category: str, japanese_description: str, system_prompt: str | None = None) -> object:
        user_content = f"""
        Product Name: {product_name}
        Category: {category}
        The following Japanese text is pre-labeled with [Section] tags. Translate and beautify EACH section individually, preserving order and structure. Use the Architectural Rules from the system prompt.
        Pre-labeled Japanese Text:
        {japanese_description}
        """
        
        logger.info(f"Rewriting description using AI for product: {product_name}")
        logger.debug(f"User Content: {user_content}")

        prompt_to_use = system_prompt or self.system_prompt
        
        # Non-streaming call
        response = self.client.chat.completions.create(
            model=OPENAI_MODEL, 
            messages=[
                {"role": "system", "content": prompt_to_use},
                {"role": "user", "content": user_content}
            ],
            temperature=OPENAI_TEMPERATURE,
            max_tokens=OPENAI_MAX_TOKENS
        )
        
        return response # Return full object to access usage stats

    def generate_copy_stream(self, product_name: str, category: str, japanese_description: str, system_prompt: str | None = None):
        """
        Returns a generator (stream) from OpenAI.
        """
        user_content = f"""
        Product Name: {product_name}
        Category: {category}
        Original Japanese Text:
        {japanese_description}
        """
        
        logger.info(f"Stream-Rewriting description for product: {product_name}")
        
        prompt_to_use = system_prompt or self.system_prompt

        # Streaming call
        stream = self.client.chat.completions.create(
            model=OPENAI_MODEL, 
            messages=[
                {"role": "system", "content": prompt_to_use},
                {"role": "user", "content": user_content}
            ],
            temperature=OPENAI_TEMPERATURE,
            max_tokens=OPENAI_MAX_TOKENS,
            stream=True,
            stream_options={"include_usage": True} # Critical for accurate billing in streams
        )
        
        return stream
