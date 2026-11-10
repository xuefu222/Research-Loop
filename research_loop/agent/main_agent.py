"""组装 Deep Agent，运行提案或审查角色的一次会话。"""

import json
from threading import Lock

from deepagents import create_deep_agent
from deepagents.backends import StateBackend
from langchain.agents.middleware import wrap_model_call, wrap_tool_call
from langchain_core.messages import AIMessage, ToolMessage
from langsmith import tracing_context

from .prompts import AUTHOR_PROMPT, REVIEWER_PROMPT
from .tools import build_tools


MAX_MODEL_CALLS = 5
MAX_TOOL_CALLS = 8


def ask_agent(model, task, sources, event, *, reviewer=False):
    # 提案和审查分别进入这里，各自拥有一套对话和工具记录。
    submitted = []
    event.update(model_calls=0, evidence_reads=[], tool_calls=[])
    lock = Lock()
    tools = build_tools(sources, event, submitted, lock, reviewer=reviewer,
                        fixed_proposal=bool(task.get("locked_fields")))
    allowed = {item.name for item in tools}

    @wrap_model_call
    def limit_model(request, handler):
        if event["model_calls"] >= MAX_MODEL_CALLS:
            raise ValueError("Agent model-call budget exhausted")
        event["model_calls"] += 1
        return handler(request.override(
            tools=[item for item in request.tools if getattr(item, "name", None) in allowed]
        ))

    @wrap_tool_call
    def limit_tools(request, handler):
        call = request.tool_call
        name = call["name"]
        with lock:
            if name not in allowed or len(event["tool_calls"]) >= MAX_TOOL_CALLS:
                return ToolMessage(content="Tool unavailable or budget exhausted.", tool_call_id=call["id"],
                                   status="error")
            event["tool_calls"].append(name)
        return handler(request)

    # 与参考仓库的 main_agent.py 一样，这里把模型、提示词和工具组装成 Agent。
    with tracing_context(enabled=False):
        agent = create_deep_agent(
            name="proposal_reviewer" if reviewer else "proposal_author",
            model=model,
            system_prompt=REVIEWER_PROMPT if reviewer else AUTHOR_PROMPT,
            tools=tools,
            backend=StateBackend(),
            middleware=[limit_model, limit_tools],
        )
        metadata = [
            {key: row[key] for key in ("id", "title", "scope", "locator")}
            for row in sources
        ]
        content = json.dumps({**task, "sources": metadata}, ensure_ascii=False)
        config = {"recursion_limit": 18}
        result = agent.invoke(
            {"messages": [{"role": "user", "content": content}]},
            config=config,
        )
        messages = result["messages"]
        last = messages[-1]
        if (not submitted and isinstance(last, AIMessage) and not last.tool_calls
                and event["model_calls"] < MAX_MODEL_CALLS):
            # 模型有时把提案写成聊天回复。保留已读证据，请它用工具正式提交一次。
            submission_tool = "submit_audit" if reviewer else "submit_result"
            event["submission_reminder"] = True
            agent.invoke({"messages": [*messages, {
                "role": "user",
                "content": f"Your response has not been saved. Submit it now using the {submission_tool} tool.",
            }]}, config=config)

    if len(submitted) != 1:
        raise ValueError("Agent did not submit exactly one result")
    return submitted[0]
