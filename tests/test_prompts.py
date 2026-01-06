"""Unit tests for prompt management tools."""

from __future__ import annotations

import asyncio

import pytest

from tests.fakes import FakeContext, FakeLangfuse


@pytest.fixture()
def state(tmp_path):
    """Return an MCPState instance using the fake client."""
    from langfuse_mcp.__main__ import MCPState

    return MCPState(langfuse_client=FakeLangfuse(), dump_dir=str(tmp_path))


def test_create_text_prompt(state):
    """create_text_prompt should create a text prompt version."""
    from langfuse_mcp.__main__ import create_text_prompt

    ctx = FakeContext(state)
    result = asyncio.run(
        create_text_prompt(
            ctx,
            name="greeting",
            prompt="Hello {{name}}",
            labels=["production"],
            config={"model": "gpt-4"},
            tags=["v1"],
        )
    )
    data = result["data"]
    assert data["name"] == "greeting"
    assert data["type"] == "text"
    assert data["prompt"] == "Hello {{name}}"
    assert data["labels"] == ["production"]
    assert data["config"]["model"] == "gpt-4"
    assert state.langfuse_client.last_create_kwargs["type"] == "text"


def test_create_chat_prompt(state):
    """create_chat_prompt should create a chat prompt version."""
    from langfuse_mcp.__main__ import create_chat_prompt

    ctx = FakeContext(state)
    messages = [
        {"role": "system", "content": "You are helpful"},
        {"role": "user", "content": "Hi"},
    ]
    result = asyncio.run(
        create_chat_prompt(
            ctx,
            name="chatty",
            prompt=messages,
            labels=["staging"],
        )
    )
    data = result["data"]
    assert data["name"] == "chatty"
    assert data["type"] == "chat"
    assert data["prompt"] == messages
    assert data["labels"] == ["staging"]
    assert state.langfuse_client.last_create_kwargs["type"] == "chat"


def test_update_prompt_labels(state):
    """update_prompt_labels should add labels for a prompt version."""
    from langfuse_mcp.__main__ import create_text_prompt, update_prompt_labels

    ctx = FakeContext(state)
    asyncio.run(create_text_prompt(ctx, name="greeting", prompt="Hello", labels=["staging"]))

    result = asyncio.run(update_prompt_labels(ctx, name="greeting", version=1, labels=["production"]))
    data = result["data"]
    assert data["name"] == "greeting"
    assert data["version"] == 1
    assert data["labels"] == ["production", "staging"]
    assert state.langfuse_client.last_update_kwargs["new_labels"] == ["production"]
