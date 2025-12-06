import json
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from datetime import date

from .services import OpenAIService
from .db_transactions import update_token_usage
from .logger import get_logger

logger = get_logger(__name__)

async def stream_openai_response(
    openai_service: OpenAIService,
    product_name: str,
    category: str,
    japanese_description: str,
    db: Session,
    api_key_id: int,
    billing_cycle_start: date
):
    """
    Generator function that:
    1. Streams chunks from OpenAI.
    2. Calculates total token usage (approximate for stream).
    3. Updates usage in DB after stream completes.
    4. Yields data to the client.
    """
    
    # 1. Call OpenAI in streaming mode
    # Note: We need to modify OpenAIService to expose a streaming method 
    # or call the client directly here. For better separation, let's assume
    # we add a method `generate_copy_stream` to OpenAIService.
    
    stream = openai_service.generate_copy_stream(
        product_name=product_name,
        category=category,
        japanese_description=japanese_description
    )

    # Accumulate content to count tokens (or use stream usage if available in future SDKs)
    # Currently, OpenAI streaming response doesn't always give total usage easily 
    # without "stream_options={'include_usage': True}".
    full_content = ""
    total_usage = 0
    
    try:
        for chunk in stream:
            # Ensure we have content to yield
            if chunk.choices and chunk.choices[0].delta.content:
                content = chunk.choices[0].delta.content
                full_content += content
                yield content

            # Check for usage stats if provided (OpenAI updated this recently)
            if hasattr(chunk, 'usage') and chunk.usage:
                total_usage = chunk.usage.total_tokens

        # If usage wasn't in the chunks, estimate it or use a fallback
        # (Standard tokenizer estimation would be better here, but for now we rely on the chunk metadata if present)
        if total_usage == 0 and full_content:
             # Fallback: Simple estimation (e.g. 1 token ~= 4 chars) + prompt estimate
             # Ideally, use tiktoken library for accuracy.
             total_usage = len(full_content) // 4 + 100 # +100 for prompt overhead approximation

        # 2. Atomic DB Update after stream ends
        if total_usage > 0:
            logger.info(f"📝 Stream complete. Updating usage: {total_usage} tokens.")
            update_token_usage(db, api_key_id, total_usage, billing_cycle_start)
            
    except Exception as e:
        logger.error(f"❌ Error during streaming: {e}")
        # In a stream, we can't easily change the HTTP status code once started,
        # but we can yield an error message or stop.
        yield f"\n[Error generating response: {str(e)}]"

def create_streaming_response(
    openai_service: OpenAIService,
    product_name: str,
    category: str,
    japanese_description: str,
    db: Session,
    api_key_id: int,
    billing_cycle_start: date
):
    return StreamingResponse(
        stream_openai_response(
            openai_service, 
            product_name, 
            category, 
            japanese_description, 
            db, 
            api_key_id, 
            billing_cycle_start
        ),
        media_type="text/event-stream" 
    )

