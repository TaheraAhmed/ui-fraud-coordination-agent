"""Gemini agent orchestrator: wires tools and system prompt into a runnable agent.

This is the entry point for invoking the UI Fraud Coordination Agent. The
orchestrator builds a Gemini client configured with our four tools and the
system prompt, then exposes a simple invoke() function for callers.

The agent runs a tool-use loop: it calls tools as needed, observes results,
and continues reasoning until it has a final response for the investigator.
"""

import json
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from google import genai
from google.genai import types

from src.agent.tools.tool_schemas import ALL_TOOL_SCHEMAS
from src.agent.tools.federation_query import query_federation
from src.agent.tools.legacy_reader import read_legacy_source
from src.agent.tools.local_lookup import request_local_details
from src.agent.tools.modern_reader import search_modern_source_by_hash
from src.agent.tools.modern_reader import read_modern_source
from src.agent.tools.modern_reader import search_modern_source_by_hash

from src.observability.arize_setup import setup_arize_tracing


load_dotenv()


SYSTEM_PROMPT_PATH = Path("src/agent/prompts/system_prompt.md")
MAX_AGENT_TURNS = 15  # Safety limit on tool-call loops


# Map tool names to actual Python callables. This is the dispatch table the
# orchestrator uses when Gemini asks to call a tool.
TOOL_REGISTRY = {
    "read_legacy_source": read_legacy_source,
    "read_modern_source": read_modern_source,
    "search_modern_source_by_hash": search_modern_source_by_hash,
    "query_federation": query_federation,
    "request_local_details": request_local_details,
}


def _load_system_prompt() -> str:
    return SYSTEM_PROMPT_PATH.read_text()


def _execute_tool_call(function_call: types.FunctionCall) -> dict[str, Any]:
    """Execute a single tool call requested by the agent.

    Returns a JSON-serializable dict containing the tool's output, or an
    error description if the tool raised.
    """
    tool_name = function_call.name
    arguments = dict(function_call.args) if function_call.args else {}

    if tool_name not in TOOL_REGISTRY:
        return {"error": f"Unknown tool: {tool_name}"}

    tool_fn = TOOL_REGISTRY[tool_name]

    try:
        result = tool_fn(**arguments)
        # Tool results may be lists, dicts, or scalars; wrap consistently
        if isinstance(result, list):
            # Truncate large lists to keep context window manageable
            display = result[:20]
            return {"result": display, "total_count": len(result), "truncated": len(result) > 20}
        return {"result": result}
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}


def invoke_agent(
    user_query: str,
    investigator_id: str = "demo_investigator",
    model_name: str = "gemini-2.5-flash",
    verbose: bool = True,
) -> str:
    """Run the agent on a user query and return its final response.

    Args:
        user_query: The investigator's natural-language question or instruction.
        investigator_id: Identity to use for audit logging.
        model_name: Gemini model to invoke.
        verbose: If True, print each tool call and result as the agent runs.

    Returns:
        The agent's final text response to the user.
    """
    setup_arize_tracing()  # No-op after first call
    
    project_id = os.environ.get("GCP_PROJECT_ID")
    location = os.environ.get("GCP_LOCATION", "us-central1")

    client = genai.Client(vertexai=True, project=project_id, location=location)

    system_prompt = _load_system_prompt()

    # Prepend investigator context to the user's query so the agent has it
    framed_query = (
        f"Investigator identity: {investigator_id}\n\n"
        f"Investigator request: {user_query}"
    )

    tools_config = types.Tool(function_declarations=ALL_TOOL_SCHEMAS)
    config = types.GenerateContentConfig(
        system_instruction=system_prompt,
        tools=[tools_config],
        temperature=0.2,  # Lower temperature for more disciplined tool use
    )

    contents: list[types.Content] = [
        types.Content(role="user", parts=[types.Part(text=framed_query)])
    ]

    for turn in range(MAX_AGENT_TURNS):
        response = client.models.generate_content(
            model=model_name,
            contents=contents,
            config=config,
        )

        candidate = response.candidates[0]
        contents.append(candidate.content)

        # Check whether the agent wants to call tools or has a final response
        function_calls = []
        text_parts = []
        for part in candidate.content.parts:
            if part.function_call:
                function_calls.append(part.function_call)
            elif part.text:
                text_parts.append(part.text)

        if not function_calls:
            # No more tool calls — this is the final response
            final_text = "".join(text_parts)
            if verbose:
                print(f"\n=== AGENT FINAL RESPONSE (turn {turn + 1}) ===\n{final_text}")
            return final_text

        # Execute each tool call and append results
        tool_response_parts = []
        for fc in function_calls:
            if verbose:
                args_summary = {k: (v[:30] + "..." if isinstance(v, str) and len(v) > 30 else v)
                                for k, v in (dict(fc.args) if fc.args else {}).items()}
                print(f"\n--- TURN {turn + 1}: Agent calls {fc.name}({args_summary}) ---")

            result = _execute_tool_call(fc)

            if verbose:
                result_preview = json.dumps(result, default=str)[:300]
                print(f"--- Result: {result_preview}{'...' if len(result_preview) >= 300 else ''}")

            tool_response_parts.append(
                types.Part(
                    function_response=types.FunctionResponse(
                        name=fc.name,
                        response=result,
                    )
                )
            )

        contents.append(types.Content(role="user", parts=tool_response_parts))

    raise RuntimeError(
        f"Agent did not produce a final response within {MAX_AGENT_TURNS} turns. "
        "Consider raising the limit or simplifying the query."
    )


if __name__ == "__main__":
    # First end-to-end agent run: investigate a seeded cross-state fraud pair.
    import json as _json

    with open("data/ground_truth.json") as f:
        gt = _json.load(f)

    seeded_pair = gt["pattern_1_ssn_reuse"][0]
    a_id = seeded_pair["claim_ids"][0]

    query = (
        f"Please investigate claim {a_id} for possible cross-state unemployment "
        f"insurance fraud. Check whether any of its identifiers match claims in "
        f"the other state, and if so, construct a due-process explanation."
    )

    print(f"User query: {query}\n")
    print("=" * 70)
    invoke_agent(query, investigator_id="demo_investigator_v1")