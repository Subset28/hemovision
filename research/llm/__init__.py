"""LLM abstraction layer. See research/llm/base.py for the provider interface,
research/llm/openrouter.py for the concrete client, research/llm/router.py
for role-based model routing. No real API key is assumed to exist in this
environment — every code path here must fail gracefully, never crash the
orchestrator/CLI, when OPENROUTER_API_KEY is unset."""
