import asyncio
import logging
from typing import Dict, List, Optional

from smolagents import ChatMessage, Model, TokenUsage
from smolagents.tools import Tool

logger = logging.getLogger(__name__)


class AsyncOpenAIModel(Model):
    """Async version of
    [OpenAIServerModel](https://github.com/huggingface/smolagents/blob/93c433c81f781f64454f8d3450ce7d52dc5d35a3/src/smolagents/models.py#L707)
    using AsyncOpenAI client.  The logic is roughly identical, except that it
    runs async so we need to asyncio.run_coroutine_threadsafe to allow
    `__call__` to remain synchronous.
    """

    def __init__(
        self,
        async_loop: asyncio.AbstractEventLoop,
        model_id: str,
        api_base: Optional[str] = None,
        api_key: Optional[str] = None,
        custom_role_conversions: Optional[Dict[str, str]] = None,
        # smolagents internally sets default `max_tokens` to 4096, which would
        # override the `inspect_ai` model settings.  It also causes issues for
        # Anthropic reasoning mode, which needs `max_tokens > reasoning tokens`
        max_tokens=None,
        prune_stop_sequences: bool = False,
        **kwargs,
    ):
        """
        Initialize an AsyncOpenAIModel.

        Args:
            async_loop (asyncio.AbstractEventLoop): The event loop to run async operations.
            model_id (str): The model identifier to use (e.g., "gpt-4", "gpt-5", etc.).
            api_base (Optional[str]): The base URL for the OpenAI API.
            api_key (Optional[str]): The API key for authentication.
            custom_role_conversions (Optional[Dict[str, str]]): Custom role conversions for chat messages.
            max_tokens: Maximum number of tokens to generate.
            prune_stop_sequences (bool): If True, removes the "stop" parameter from the completion arguments.
                This is necessary for certain models (notably GPT-5 and O-series models) that do not support
                the "stop" parameter or may produce errors if it is present. Set this to True when using
                GPT-5 or O-series models, or any model where stop sequences should not be sent to the API.
            **kwargs: Additional keyword arguments.
        """
        super().__init__(max_tokens=max_tokens, **kwargs)
        try:
            from openai import AsyncOpenAI
        except ModuleNotFoundError:
            raise ModuleNotFoundError(
                "Please install 'openai' to use AsyncOpenAIModel: `pip install openai`"
            ) from None

        self.model_id = model_id
        self.client = AsyncOpenAI(
            base_url=api_base,
            api_key=api_key,
        )
        self.custom_role_conversions = custom_role_conversions
        self.loop = async_loop
        self.prune_stop_sequences = prune_stop_sequences

    async def acall(
        self,
        messages: List[Dict[str, str]],
        stop_sequences: Optional[List[str]] = None,
        tools_to_call_from: Optional[List[Tool]] = None,
        **kwargs,
    ) -> ChatMessage:
        """Async version of the original `generate` method."""
        try:
            # Reuse _prepare_completion_kwargs from OpenAIServerModel
            completion_kwargs = self._prepare_completion_kwargs(
                messages=messages,
                stop_sequences=stop_sequences,
                tools_to_call_from=tools_to_call_from,
                model=self.model_id,
                custom_role_conversions=self.custom_role_conversions,
                **kwargs,
            )

            if "stop" in completion_kwargs and self.prune_stop_sequences:
                del completion_kwargs["stop"]

            response = await self.client.chat.completions.create(**completion_kwargs)
            self._last_input_token_count = response.usage.prompt_tokens
            self._last_output_token_count = response.usage.completion_tokens

            return ChatMessage.from_dict(
                response.choices[0].message.model_dump(
                    include={"role", "content", "tool_calls"}
                ),
                raw=response,
                token_usage=TokenUsage(
                    input_tokens=response.usage.prompt_tokens,
                    output_tokens=response.usage.completion_tokens,
                ),
            )
        except Exception:
            logger.exception(f"Error in AsyncOpenAIModel wrapper:")
            raise

    def generate(self, *args, **kwargs):
        coro = self.acall(*args, **kwargs)
        future = asyncio.run_coroutine_threadsafe(coro, self.loop)
        return future.result()
