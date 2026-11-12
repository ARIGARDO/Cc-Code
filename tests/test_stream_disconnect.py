from types import SimpleNamespace

import httpx
import pytest

from cccode.client import AnthropicClient, NetworkError
from cccode.config import ProviderConfig
from cccode.conversation import ConversationManager


@pytest.mark.asyncio
async def test_anthropic_stream_transport_error_is_reported():
    class BrokenStream:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            return False
        def __aiter__(self):
            return self
        async def __anext__(self):
            raise httpx.RemoteProtocolError("incomplete chunked read")

    client = AnthropicClient(ProviderConfig(api_key="test", thinking=False))
    real_client = client._client
    client._client = SimpleNamespace(messages=SimpleNamespace(stream=lambda **kwargs: BrokenStream()))
    conversation = ConversationManager()
    conversation.add_user_message("hello")
    try:
        with pytest.raises(NetworkError, match="流式连接中断"):
            _ = [event async for event in client.stream(conversation, None, None)]
    finally:
        await real_client.close()
