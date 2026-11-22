"""Opt-in OpenAI-compatible chat adapter. Never called in scripted mode."""

import json
import os

import httpx


async def complete(messages):
    key = os.environ["LLM_API_KEY"]
    model = os.environ["LLM_MODEL"]
    base = os.environ["LLM_BASE_URL"].rstrip("/")
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            base + "/chat/completions",
            headers={"Authorization": f"Bearer {key}"},
            json={
                "model": model,
                "messages": messages,
                "temperature": 0,
                "response_format": {"type": "json_object"},
            },
        )
        response.raise_for_status()
        return json.loads(response.json()["choices"][0]["message"]["content"])


async def user_turn(spec, transcript):
    response = await complete(
        [
            {
                "role": "system",
                "content": "Simulate an employee. Return JSON with a message string. Persona: "
                + spec.persona
                + " Goal: "
                + spec.goal,
            },
            {"role": "user", "content": json.dumps(transcript)},
        ]
    )
    if not isinstance(response.get("message"), str):
        raise ValueError("invalid simulator output")
    return response["message"]


async def agent_turn(message, transcript, contracts):
    return await complete(
        [
            {
                "role": "system",
                "content": "Act as an IT assistant. Return JSON: {tool: name, arguments: object, idempotency_key: string}. Use a unique stable key for each mutation. Available tools: "
                + json.dumps(contracts),
            },
            {"role": "user", "content": json.dumps({"message": message, "history": transcript})},
        ]
    )
