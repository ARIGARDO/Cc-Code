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


@pytest.mark.asyncio
async def test_anthropic_stream_timeout_is_reported_without_hidden_retries():
    class TimedOutStream:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): return False
        def __aiter__(self): return self
        async def __anext__(self): raise httpx.ReadTimeout('stalled')

    client = AnthropicClient(ProviderConfig(api_key='test', thinking=False))
    real_client = client._client
    assert real_client.max_retries == 0
    assert real_client.timeout.read == 60
    client._client = SimpleNamespace(messages=SimpleNamespace(stream=lambda **kwargs: TimedOutStream()))
    conversation = ConversationManager()
    conversation.add_user_message('hello')
    try:
        with pytest.raises(NetworkError, match='超时'):
            _ = [event async for event in client.stream(conversation, None, None)]
    finally:
        await real_client.close()
