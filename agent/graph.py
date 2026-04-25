"""
Main LangGraph wiring for the ETF Rotation Agent.

Pattern coverage (see agent/patterns/*):
- 1 Prompt Chaining      -> prompts/prompt_builder
- 2 Routing              -> router_node + RouterDecision
- 3 Parallelization      -> subgraph.backtest_compare_node / conflict_check_node / multi_agent_debate_node
- 4 Reflection           -> reflect_node
- 5 Tool Use             -> ToolNode + ALL_TOOLS
- 6 Planning             -> planner_node
- 7 Multi-Agent          -> multi_agent_debate (subgraph)
- 8 Memory               -> memory.record_query + memory_snippet injection
- 10 MCP                 -> tools/mcp_tools + mcp_server/
- 11 Goal Setting        -> goal_monitor.init_goal_state / update_goal_progress
- 12 Exception Handling  -> router fallback + tool budget
- 14 RAG                 -> tools/rag_tools
- 15 Inter-agent Comm    -> patterns/inter_agent (pydantic messages)
- 16 Resource-aware      -> resource_tracker + CostCallbackHandler
- 17 Reasoning           -> self_consistency_vote inside multi_agent aggregator
- 18 Guardrails          -> input_guardrail_node / output_guardrail_node
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from agent._progress import ProgressCallback  # noqa: F401

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph
from langgraph.prebuilt import ToolNode

from agent.patterns.goal_monitor import (
    goal_progress_snippet,
    init_goal_state,
    update_goal_progress,
)
from agent.patterns.guardrails import (
    input_guardrail,
    output_guardrail,
    redact_output,
    request_hitl_approval,
)
from agent.patterns.memory import (
    memory_context_snippet,
    record_query,
    set_last_trace,
)
from agent.patterns.pattern_log import PATTERN_LOG, log_pattern_use
from agent.patterns.reflection import CritiqueReport, run_reflection
from agent.patterns.resource_tracker import (
    CostCallbackHandler,
    NodeTimer,
    RESOURCE_TRACKER,
    resource_snippet,
)
from agent.prompts._lang import normalise_lang
from agent.prompts.prompt_builder import build_system_prompt
from agent.prompts.reflection_prompt import get_reflection_prompt
from agent.prompts.router_prompts import build_router_prompt
from agent.prompts.task_prompts import infer_task_key
from agent.prompts.workflow_prompts import (
    build_executor_guidance,
    build_finalizer_guidance,
    build_planner_prompt,
)
from agent.router_schema import DataStrategy, RouterDecision
from agent.state import AgentState
from agent.subgraph import SUBGRAPH_EDGE_MAP, register_subgraph_nodes, route_after_planner
from tools import ALL_TOOLS

load_dotenv()


# ---------------------------------------------------------------------------
# Resilience: LLM calls can fail two ways.
#   1. Transient network blip / rate-limit on the *primary* provider.
#   2. The primary key is exhausted / revoked (HTTP 401, 402, "insufficient
#      quota", etc.). In that case retrying does nothing.
#
# We support an optional *fallback* OpenAI-compatible endpoint via env vars:
#   OPENAI_API_KEY_FALLBACK   - second key (e.g. your personal AIHubMix key)
#   OPENAI_BASE_URL_FALLBACK  - second base url (defaults to primary base url)
#   OPENAI_MODEL_FALLBACK     - second model id (defaults to primary model)
#
# Strategy in llm_invoke_with_retry:
#   - retry the primary up to N times for *transient* errors with backoff
#   - if the error looks like a permanent auth/quota problem OR retries are
#     exhausted, transparently switch to the fallback endpoint and try once
# ---------------------------------------------------------------------------

_RETRYABLE_TOKENS = ("connection error", "timeout", "remote", "read timed out", "rate limit")
_AUTH_QUOTA_TOKENS = (
    "401", "403", "402", "429",
    "invalid api key", "incorrect api key",
    "insufficient_quota", "insufficient quota", "quota exceeded",
    "exceeded your current quota", "balance",
    "no available token", "余额不足", "账户余额", "key 已失效", "key已失效",
)


def _is_transient_llm_error(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return any(tok in msg for tok in _RETRYABLE_TOKENS)


def _is_auth_or_quota_error(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return any(tok in msg for tok in _AUTH_QUOTA_TOKENS)


def has_fallback_llm() -> bool:
    return bool(os.getenv("OPENAI_API_KEY_FALLBACK"))


def _build_fallback_llm(*, temperature: float = 0.0, structured: type | None = None,
                       callbacks=None):
    """Build a ChatOpenAI bound to the fallback key/base/model."""
    fb_key = os.getenv("OPENAI_API_KEY_FALLBACK")
    if not fb_key:
        return None
    fb_base = os.getenv("OPENAI_BASE_URL_FALLBACK") or os.getenv("OPENAI_BASE_URL")
    fb_model = os.getenv("OPENAI_MODEL_FALLBACK") or os.getenv("OPENAI_MODEL", "deepseek-v3.2")
    fb = ChatOpenAI(
        model=fb_model,
        temperature=temperature,
        api_key=fb_key,
        base_url=fb_base,
        callbacks=callbacks or [],
    )
    return fb.with_structured_output(structured) if structured else fb


def _extract_llm_init_kwargs(llm) -> dict:
    """Best-effort: read temperature / callbacks from a possibly-wrapped LLM
    so we can rebuild an equivalent fallback client. Structured-output binding
    is intentionally not preserved on the fallback path: callers that depend
    on structured output (only the reflection critic today) wrap their own
    invocation in try/except and gracefully skip on failure."""
    info = {"temperature": 0.0, "structured": None, "callbacks": []}
    inner = llm.bound if hasattr(llm, "bound") else llm
    info["temperature"] = getattr(inner, "temperature", 0.0) or 0.0
    cbs = getattr(inner, "callbacks", None)
    if cbs:
        info["callbacks"] = cbs
    return info


def llm_invoke_with_retry(llm, messages, *, attempts: int = 3, base_delay: float = 1.0, label: str = "llm"):
    """Invoke an LLM with backoff on transient errors and a one-shot
    fallback to the secondary endpoint on auth/quota failures."""
    last_exc: BaseException | None = None
    for i in range(attempts):
        try:
            return llm.invoke(messages)
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            auth_err = _is_auth_or_quota_error(exc)
            transient = _is_transient_llm_error(exc)

            # Auth / quota error → retrying is pointless, jump to fallback now
            if auth_err:
                print(f"[graph][{label}][WARN] primary key rejected ({exc}); switching to fallback key")
                break

            if not transient or i == attempts - 1:
                # Either non-retryable, or we've exhausted retries
                break

            delay = base_delay * (2 ** i)
            print(f"[graph][{label}][WARN] transient LLM error '{exc}', retry {i+1}/{attempts-1} in {delay:.1f}s")
            time.sleep(delay)

    # Primary path failed. Try the fallback endpoint exactly once if configured.
    if has_fallback_llm():
        try:
            init_kw = _extract_llm_init_kwargs(llm)
            fb = _build_fallback_llm(
                temperature=init_kw["temperature"],
                structured=init_kw["structured"],
                callbacks=init_kw["callbacks"],
            )
            if fb is not None:
                print(f"[graph][{label}][INFO] invoking fallback LLM endpoint")
                return fb.invoke(messages)
        except Exception as fb_exc:  # noqa: BLE001
            print(f"[graph][{label}][ERROR] fallback LLM also failed: {fb_exc}")
            last_exc = fb_exc

    if last_exc:
        raise last_exc
    raise RuntimeError("llm_invoke_with_retry: unreachable")

MAX_TOOL_CALLS = 8
MAX_REPEATED_TOOL_CALLS = 2


def _log_graph(node_name: str, message: str, level: str = "INFO") -> None:
    print(f"[graph][{node_name}][{level}] {message}", flush=True)


def _extract_user_input(state: AgentState) -> str:
    if state.get("user_input"):
        return state["user_input"]
    for msg in reversed(state["messages"]):
        if getattr(msg, "type", "") == "human":
            return getattr(msg, "content", "")
        if isinstance(msg, dict) and msg.get("role") == "user":
            return msg.get("content", "")
    return ""


def _format_tool_signature(tool_calls) -> str:
    normalized = []
    for tc in tool_calls:
        normalized.append({"name": tc.get("name", ""), "args": tc.get("args", {})})
    return json.dumps(normalized, ensure_ascii=False, sort_keys=True)


def _executor_next(state: AgentState) -> Literal["tools", "finalize", "end"]:
    if state.get("stop_reason"):
        return "finalize"
    last_msg = state["messages"][-1]
    if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
        return "tools"
    return "end"


def _route_after_guardrail(state: AgentState) -> str:
    """If input guardrail blocked, short-circuit to finalize."""
    if state.get("blocked"):
        return "finalize"
    return "router"


def _is_portfolio_task(task_key: str) -> bool:
    return task_key in {
        "research_weekly_report",
        "rm_client_portfolio",
        "research_multi_agent_debate",
    }


def build_graph(model_name: str | None = None) -> StateGraph:
    model = model_name or os.getenv("OPENAI_MODEL", "deepseek-v3.2")

    # --- LLM factory: lazily attaches callback per-thread (Pattern 16) ---
    def llm_for(thread_id: str, *, temperature: float = 0.0, structured: type | None = None):
        callbacks = [CostCallbackHandler(thread_id=thread_id, default_model=model)]
        base = ChatOpenAI(model=model, temperature=temperature, callbacks=callbacks)
        return base.with_structured_output(structured) if structured else base

    tool_node = ToolNode(ALL_TOOLS)

    # -------------------- PATTERN 18 INPUT GUARDRAIL --------------------
    def input_guardrail_node(state: AgentState):
        thread_id = state.get("thread_id", "default")
        user_input = _extract_user_input(state)
        _log_graph("input_guardrail", f"checking input ({len(user_input)} chars)")
        result = input_guardrail(user_input, thread_id=thread_id)
        updates: dict = {
            "input_guardrail": result.to_dict(),
            "user_input": user_input,
        }
        if not result.passed:
            _log_graph("input_guardrail", f"BLOCKED: {result.reason}", level="WARN")
            lang = normalise_lang(state.get("output_language"))
            if lang == "zh":
                refusal = (
                    f"⚠️ 输入未通过合规/安全护栏（风险等级：{result.risk_level}）。\n"
                    f"原因：{result.reason}\n\n"
                    "本 Agent 仅提供 A 股/港股/美股 ETF 轮动研究与合规辅助，"
                    "不执行真实交易、不处理个人隐私、不会忽略系统指令。请调整问题后重试。"
                )
            else:
                refusal = (
                    f"Input rejected by the compliance / safety guardrail "
                    f"(risk level: {result.risk_level}).\n"
                    f"Reason: {result.reason}\n\n"
                    "This agent only provides A-share / HK / US ETF rotation research and "
                    "compliance support. It does not execute real trades, does not handle "
                    "personal data, and will not ignore its system instructions. "
                    "Please adjust your question and try again."
                )
            updates.update(
                {
                    "blocked": True,
                    "stop_reason": "input_guardrail_blocked",
                    "messages": [{"role": "assistant", "content": refusal}],
                }
            )
        else:
            updates["blocked"] = False
        return updates

    # -------------------- PATTERN 8 MEMORY PREP --------------------
    def memory_prep_node(state: AgentState):
        thread_id = state.get("thread_id", "default")
        snippet = memory_context_snippet(thread_id)
        if snippet:
            log_pattern_use(thread_id, 8, "Memory", "inject_context", f"{len(snippet)} chars")
        return {"memory_snippet": snippet}

    # -------------------- PATTERN 2 ROUTER --------------------
    def router_node(state: AgentState):
        thread_id = state.get("thread_id", "default")
        with NodeTimer(thread_id, "router"):
            user_input = state.get("user_input") or _extract_user_input(state)
            role = state.get("role", "researcher")
            _log_graph("router", f"routing started, role={role}, market={state.get('market', 'a_share')}")
            log_pattern_use(thread_id, 2, "Routing", "router", "structured_output")

            router_prompt = build_router_prompt(
                role=role,
                market=state.get("market", "a_share"),
                user_input=user_input,
                client_risk_level=state.get("client_risk_level"),
                output_language=state.get("output_language", "en"),
            )
            # inject memory snippet into the router as additional context
            mem_snip = state.get("memory_snippet") or ""
            if mem_snip:
                router_prompt = router_prompt + "\n\n" + mem_snip

            router_llm = llm_for(thread_id, temperature=0, structured=RouterDecision)
            try:
                decision = router_llm.invoke([{"role": "system", "content": router_prompt}])
                task_key = decision.task_key.value
                data_strategy = decision.data_strategy.value
                should_use_tools = decision.should_use_tools
                requires_trace_save = decision.requires_trace_save
                route_confidence = decision.confidence
                route_reason = decision.route_reason
                _log_graph(
                    "router",
                    f"structured routing complete: task={task_key}, strategy={data_strategy}, "
                    f"tools={should_use_tools}, trace_save={requires_trace_save}, conf={route_confidence:.2f}",
                )
            except Exception as exc:
                log_pattern_use(thread_id, 12, "Exception Handling", "router_fallback", str(exc))
                task_key = infer_task_key(user_input=user_input, role=role)
                lowered = (user_input or "").lower()
                if any(x in lowered for x in ["多 agent", "多agent", "辩论", "debate", "三方", "quant macro risk"]):
                    task_key = "research_multi_agent_debate"
                if any(x in lowered for x in ["为什么跌", "为什么涨", "解释", "trace", "审查", "回顾", "上周"]):
                    data_strategy = DataStrategy.HISTORY_FIRST.value
                elif any(x in lowered for x in ["周报", "本周", "行业轮动", "扫描", "组合", "市场"]):
                    data_strategy = DataStrategy.FRESH_SCAN.value
                else:
                    data_strategy = DataStrategy.HYBRID.value if task_key != "generic" else DataStrategy.DIRECT_ANSWER.value
                should_use_tools = task_key != "generic"
                requires_trace_save = any(x in lowered for x in ["周报", "正式", "审批", "组合建议"])
                route_confidence = 0.5
                route_reason = (
                    f"Structured routing failed; fell back to rule-based routing. "
                    f"Inferred task: {task_key}"
                )
                _log_graph(
                    "router",
                    f"structured routing failed; using rule-based fallback: {exc}",
                    level="WARN",
                )

            # keyword override to reach multi-agent path if requested
            lowered = (user_input or "").lower()
            if any(x in lowered for x in ["辩论", "三方", "多agent", "多 agent", "debate", "quant macro risk"]):
                task_key = "research_multi_agent_debate"
                should_use_tools = True
                _log_graph("router", "debate keyword detected; switching to research_multi_agent_debate")

            # Pattern 11: initialise goal state immediately after routing
            goal = init_goal_state(task_key, thread_id=thread_id)

            # Pattern 8: persist query to long-term memory
            record_query(
                thread_id=thread_id,
                user_input=user_input,
                task_key=task_key,
                market=state.get("market", "a_share"),
                role=role,
                client_risk_level=state.get("client_risk_level"),
            )

        return {
            "user_input": user_input,
            "task_key": task_key,
            "route_reason": route_reason,
            "route_confidence": route_confidence,
            "data_strategy": data_strategy,
            "should_use_tools": should_use_tools,
            "requires_trace_save": requires_trace_save,
            "stop_reason": "",
            "goal_state": goal.to_dict(),
            "goal_progress": goal.progress(),
        }

    # -------------------- PATTERN 6 PLANNER --------------------
    def planner_node(state: AgentState):
        thread_id = state.get("thread_id", "default")
        with NodeTimer(thread_id, "planner"):
            _log_graph("planner", f"generating execution plan, task={state.get('task_key', 'generic')}")
            log_pattern_use(thread_id, 6, "Planning", "planner", "generate plan")
            planner_prompt = build_planner_prompt(
                role=state.get("role", "researcher"),
                market=state.get("market", "a_share"),
                task_key=state.get("task_key", "generic"),
                user_input=state.get("user_input", ""),
                data_strategy=state.get("data_strategy", "fresh_scan"),
                requires_trace_save=state.get("requires_trace_save", False),
                client_risk_level=state.get("client_risk_level"),
                output_language=state.get("output_language", "en"),
            )
            if state.get("memory_snippet"):
                planner_prompt += "\n\n" + state["memory_snippet"]
            base_llm = llm_for(thread_id, temperature=0)
            try:
                response = llm_invoke_with_retry(
                    base_llm,
                    [{"role": "system", "content": planner_prompt}],
                    label="planner",
                )
                plan_text = response.content
            except Exception as exc:
                _log_graph("planner", f"LLM unavailable, using static plan: {exc}", level="WARN")
                plan_text = (
                    "[Static fallback plan — LLM unavailable]\n"
                    f"task: {state.get('task_key', 'generic')}\n"
                    "1. Run the routed subgraph with default parameters.\n"
                    "2. Persist Decision Trace.\n"
                    "3. Render the standard report template."
                )
            _log_graph("planner", "execution plan generated")
        return {"execution_plan": plan_text}

    # -------------------- PATTERN 5 EXECUTOR (ReAct tool loop) --------------------
    def executor_node(state: AgentState):
        thread_id = state.get("thread_id", "default")
        with NodeTimer(thread_id, "executor"):
            today = datetime.now().strftime("%Y-%m-%d")
            date_hint = f"\n\n[system] Today's date: {today}"
            user_input = _extract_user_input(state)
            _log_graph(
                "executor",
                f"tool_calls_used={state.get('tool_call_count', 0)}/{MAX_TOOL_CALLS}",
            )
            log_pattern_use(thread_id, 5, "Tool Use", "executor", "invoke LLM with tools")

            lang = state.get("output_language", "en")
            system_prompt = build_system_prompt(
                role=state.get("role", "researcher"),
                market=state.get("market", "a_share"),
                user_input=user_input,
                client_risk_level=state.get("client_risk_level"),
                output_language=lang,
            )
            execution_guidance = build_executor_guidance(
                plan=state.get("execution_plan", "(no plan provided)"),
                max_tool_calls=MAX_TOOL_CALLS,
                tool_call_count=state.get("tool_call_count", 0),
                data_strategy=state.get("data_strategy", "fresh_scan"),
                requires_trace_save=state.get("requires_trace_save", False),
                output_language=lang,
            )
            mem_snip = state.get("memory_snippet") or ""
            system_msg_content = (
                system_prompt
                + "\n\n"
                + execution_guidance
                + (("\n\n" + mem_snip) if mem_snip else "")
                + date_hint
            )
            tool_llm = llm_for(thread_id, temperature=0).bind_tools(ALL_TOOLS)
            t0 = time.time()
            response = tool_llm.invoke([{"role": "system", "content": system_msg_content}] + state["messages"])

            updates: dict = {"messages": [response], "stop_reason": ""}
            if hasattr(response, "tool_calls") and response.tool_calls:
                signature = _format_tool_signature(response.tool_calls)
                previous_signature = state.get("last_tool_signature", "")
                repeated_count = state.get("repeated_tool_call_count", 0)
                repeated_count = repeated_count + 1 if signature == previous_signature else 0
                tool_call_count = state.get("tool_call_count", 0) + len(response.tool_calls)
                stop_reason = ""
                if repeated_count >= MAX_REPEATED_TOOL_CALLS:
                    stop_reason = (
                        "Repeated identical tool-call pattern detected; "
                        "stopping early to avoid an infinite loop."
                    )
                    log_pattern_use(thread_id, 12, "Exception Handling", "executor", "repeated calls")
                elif tool_call_count >= MAX_TOOL_CALLS:
                    stop_reason = (
                        "Tool-call budget reached; switching to the finaliser."
                    )
                    log_pattern_use(thread_id, 16, "Resource-aware", "budget_cap", "tool cap hit")
                _log_graph(
                    "executor",
                    f"this turn produced {len(response.tool_calls)} tool call(s); "
                    f"cumulative {tool_call_count}/{MAX_TOOL_CALLS}",
                )
                if stop_reason:
                    _log_graph("executor", stop_reason, level="WARN")
                updates.update(
                    {
                        "tool_call_count": tool_call_count,
                        "last_tool_signature": signature,
                        "repeated_tool_call_count": repeated_count,
                        "stop_reason": stop_reason,
                    }
                )
            else:
                _log_graph("executor", "no tool call this turn; about to end or finalise")
            RESOURCE_TRACKER.add_node_time(thread_id, "executor_inner", (time.time() - t0) * 1000.0)
        return updates

    # Wrap ToolNode with timing
    def tools_wrapper_node(state: AgentState):
        thread_id = state.get("thread_id", "default")
        t0 = time.time()
        last_msg = state["messages"][-1]
        tool_calls = getattr(last_msg, "tool_calls", []) or []
        result = tool_node.invoke(state)
        elapsed = (time.time() - t0) * 1000.0
        for tc in tool_calls:
            tname = tc.get("name", "unknown")
            RESOURCE_TRACKER.add_tool_call(thread_id, tname, elapsed / max(len(tool_calls), 1))
            log_pattern_use(thread_id, 5, "Tool Use", "tool_node", f"{tname} completed")
        return result

    # -------------------- PATTERN 11 GOAL UPDATE --------------------
    def goal_update_node(state: AgentState):
        thread_id = state.get("thread_id", "default")
        goal_dict = state.get("goal_state") or {}
        if not goal_dict:
            return {}
        from agent.patterns.goal_monitor import GoalState, SubGoal

        goal = GoalState(
            task_key=goal_dict.get("task_key", ""),
            objective=goal_dict.get("objective", ""),
            sub_goals=[SubGoal(**sg) for sg in goal_dict.get("sub_goals", [])],
            started_at=goal_dict.get("started_at", ""),
            completed_at=goal_dict.get("completed_at", ""),
        )
        goal = update_goal_progress(goal, state.get("task_payload", {}), thread_id=thread_id)
        return {
            "goal_state": goal.to_dict(),
            "goal_progress": goal.progress(),
        }

    # -------------------- PATTERN 12 / finalizer draft --------------------
    def finalizer_node(state: AgentState):
        thread_id = state.get("thread_id", "default")
        with NodeTimer(thread_id, "finalize"):
            if state.get("blocked"):
                return {}  # already emitted refusal message

            today = datetime.now().strftime("%Y-%m-%d")
            date_hint = f"\n\n[system] Today's date: {today}"
            _log_graph("finalize", "generating the final answer")
            log_pattern_use(thread_id, 6, "Planning", "finalize", "assemble final draft")

            lang = state.get("output_language", "en")
            system_prompt = build_system_prompt(
                role=state.get("role", "researcher"),
                market=state.get("market", "a_share"),
                user_input=state.get("user_input", ""),
                client_risk_level=state.get("client_risk_level"),
                output_language=lang,
            )
            final_guidance = (
                build_finalizer_guidance(state.get("stop_reason"), output_language=lang)
                + "\n\n"
                + get_reflection_prompt(lang)
            )

            workflow_context = state.get("workflow_context", "")
            if workflow_context:
                final_guidance += "\n\n## Fixed-subgraph context\n" + workflow_context

            # Goal progress block
            goal_dict = state.get("goal_state") or {}
            if goal_dict:
                from agent.patterns.goal_monitor import GoalState, SubGoal

                goal = GoalState(
                    task_key=goal_dict.get("task_key", ""),
                    objective=goal_dict.get("objective", ""),
                    sub_goals=[SubGoal(**sg) for sg in goal_dict.get("sub_goals", [])],
                )
                final_guidance += "\n\n" + goal_progress_snippet(goal)

            if state.get("memory_snippet"):
                final_guidance += "\n\n" + state["memory_snippet"]

            base_llm = llm_for(thread_id, temperature=0)
            try:
                response = llm_invoke_with_retry(
                    base_llm,
                    [{"role": "system", "content": system_prompt + "\n\n" + final_guidance + date_hint}]
                    + state["messages"],
                    label="finalize",
                )
                _log_graph("finalize", "final answer generated")
            except Exception as exc:
                # Graceful fallback: heavy work (subgraphs / trace persist) has
                # already succeeded by this point. Hand the user a deterministic
                # summary so the chat does not show a hard "execution failed".
                _log_graph(
                    "finalize",
                    f"LLM unavailable after retries, returning deterministic fallback: {exc}",
                    level="WARN",
                )
                trace_id = (
                    state.get("trace_path")
                    or (state.get("task_payload") or {}).get("trace_path")
                    or "(see Decision Trace page)"
                )
                ctx = state.get("workflow_context") or "(no workflow context)"
                if lang == "zh":
                    body = (
                        "⚠️ 自然语言收尾步骤暂时无法访问 LLM（AIHubMix 临时网络抖动）。"
                        "数据流水线已经全部跑完并写入 Decision Trace。\n\n"
                        f"**Trace 位置**：`{trace_id}`\n\n"
                        "你可以打开「决策轨迹浏览器」页面查看完整结果，或重发同一个问题让 Agent 再生成一次自然语言总结。\n\n"
                        "---\n\n以下是结构化结果摘要：\n\n"
                        f"{ctx[:4000]}"
                    )
                else:
                    body = (
                        "Note: the LLM final-answer step was unreachable (transient AIHubMix "
                        "issue). All upstream data work succeeded and the Decision Trace has "
                        f"been persisted.\n\n**Trace location**: `{trace_id}`\n\n"
                        "Open the Decision Trace page for full results, or resend the same "
                        "question to regenerate the natural-language summary.\n\n"
                        "---\n\nStructured result snapshot:\n\n"
                        f"{ctx[:4000]}"
                    )

                class _StubMsg:
                    def __init__(self, content: str):
                        self.content = content
                        self.type = "ai"

                response = _StubMsg(body)
                _log_graph("finalize", "fallback answer assembled")

        # Mark goal as satisfied when we have a final response (generic path)
        updates = {"messages": [response]}
        goal_dict = state.get("goal_state") or {}
        if goal_dict:
            from agent.patterns.goal_monitor import GoalState, SubGoal

            goal = GoalState(
                task_key=goal_dict.get("task_key", ""),
                objective=goal_dict.get("objective", ""),
                sub_goals=[SubGoal(**sg) for sg in goal_dict.get("sub_goals", [])],
                started_at=goal_dict.get("started_at", ""),
                completed_at=goal_dict.get("completed_at", ""),
            )
            final_text = getattr(response, "content", "") or ""
            merged_payload = dict(state.get("task_payload") or {})
            merged_payload["final_response"] = final_text
            goal = update_goal_progress(goal, merged_payload, thread_id=thread_id)
            updates["goal_state"] = goal.to_dict()
            updates["goal_progress"] = goal.progress()
        return updates

    # -------------------- PATTERN 4 REFLECTION --------------------
    def reflect_node(state: AgentState):
        thread_id = state.get("thread_id", "default")
        if state.get("blocked"):
            return {}
        last = state["messages"][-1]
        draft = getattr(last, "content", "") or ""
        if len(draft) < 400:
            _log_graph("reflect", "draft too short; skipping reflection")
            return {"reflected": False, "reflection_rounds": []}

        with NodeTimer(thread_id, "reflect"):
            critic_llm = llm_for(thread_id, temperature=0, structured=CritiqueReport)
            revise_llm = llm_for(thread_id, temperature=0)

            def critic_invoke(p: str) -> CritiqueReport:
                return llm_invoke_with_retry(
                    critic_llm,
                    [{"role": "user", "content": p}],
                    label="reflect.critic",
                )

            def revise_invoke(p: str) -> str:
                resp = llm_invoke_with_retry(
                    revise_llm,
                    [{"role": "user", "content": p}],
                    label="reflect.revise",
                )
                return getattr(resp, "content", "") or ""

            try:
                result = run_reflection(
                    thread_id=thread_id,
                    user_input=state.get("user_input", ""),
                    role=state.get("role", "researcher"),
                    task_key=state.get("task_key", "generic"),
                    draft_answer=draft,
                    workflow_context=state.get("workflow_context", ""),
                    critic_llm_invoke=critic_invoke,
                    revise_llm_invoke=revise_invoke,
                    max_rounds=1,
                )
            except Exception as exc:
                # Reflection is a quality-improver, not a hard requirement.
                # If the LLM is unreachable, just skip and keep the draft.
                _log_graph("reflect", f"reflection skipped due to LLM error: {exc}", level="WARN")
                result = {"rounds": [], "reflected": False, "final_answer": draft}

        updates = {
            "reflection_rounds": result["rounds"],
            "reflected": result["reflected"],
        }
        if result["reflected"] and result["final_answer"] and result["final_answer"] != draft:
            from langchain_core.messages import AIMessage

            _log_graph("reflect", "draft revised based on critique")
            updates["messages"] = [AIMessage(content=result["final_answer"])]
        return updates

    # -------------------- PATTERN 18 OUTPUT GUARDRAIL + HITL --------------------
    def output_guardrail_node(state: AgentState):
        thread_id = state.get("thread_id", "default")
        if state.get("blocked"):
            return {}
        last = state["messages"][-1]
        text = getattr(last, "content", "") or ""
        is_portfolio = _is_portfolio_task(state.get("task_key", ""))
        result = output_guardrail(text, is_portfolio=is_portfolio, thread_id=thread_id)
        updates: dict = {"output_guardrail": result.to_dict()}

        if not result.passed:
            from langchain_core.messages import AIMessage

            redacted = redact_output(text)
            lang = normalise_lang(state.get("output_language"))
            if lang == "zh":
                safe_msg = (
                    f"⚠️ 输出未通过合规护栏（{result.reason}），以下为脱敏版本：\n\n"
                    f"{redacted}\n\n如需原始内容，请申请人工复核（HITL approval）。"
                )
            else:
                safe_msg = (
                    f"Output failed the compliance guardrail ({result.reason}). "
                    f"Below is the redacted version:\n\n{redacted}\n\n"
                    "If you need the unredacted content, request human review (HITL approval)."
                )
            updates["messages"] = [AIMessage(content=safe_msg)]
            request_hitl_approval(
                thread_id=thread_id,
                task_key=state.get("task_key", "unknown"),
                payload={
                    "reason": result.reason,
                    "details": result.details,
                    "original_output": text[:4000],
                },
                requester="output_guardrail",
            )

        # HITL for formal deliverables
        if state.get("requires_trace_save") and is_portfolio and result.passed:
            hitl_rec = request_hitl_approval(
                thread_id=thread_id,
                task_key=state.get("task_key", "unknown"),
                payload={
                    "market": state.get("market"),
                    "role": state.get("role"),
                    "user_input": state.get("user_input"),
                    "final_answer": text[:4000],
                    "task_payload": state.get("task_payload", {}),
                },
                requester="finalizer",
            )
            updates["hitl_request"] = hitl_rec

        # Persist resource usage snapshot
        updates["resource_usage"] = RESOURCE_TRACKER.summary(thread_id)

        # remember last trace path for memory
        ltp = state.get("latest_trace_path", "")
        if ltp:
            set_last_trace(thread_id, ltp)

        return updates

    # -------------------- GRAPH WIRING --------------------
    graph = StateGraph(AgentState)

    graph.add_node("input_guardrail", input_guardrail_node)
    graph.add_node("memory_prep", memory_prep_node)
    graph.add_node("router", router_node)
    graph.add_node("planner", planner_node)
    register_subgraph_nodes(graph)
    graph.add_node("executor", executor_node)
    graph.add_node("tools", tools_wrapper_node)
    graph.add_node("goal_update", goal_update_node)
    graph.add_node("finalize", finalizer_node)
    graph.add_node("reflect", reflect_node)
    graph.add_node("output_guardrail", output_guardrail_node)

    graph.set_entry_point("input_guardrail")
    graph.add_conditional_edges(
        "input_guardrail",
        lambda s: "finalize" if s.get("blocked") else "memory_prep",
        {"memory_prep": "memory_prep", "finalize": "finalize"},
    )
    graph.add_edge("memory_prep", "router")
    graph.add_edge("router", "planner")
    graph.add_conditional_edges("planner", route_after_planner, SUBGRAPH_EDGE_MAP)

    # All subgraph nodes flow into goal_update -> finalize
    graph.add_edge("weekly_prepare", "weekly_persist")
    graph.add_edge("weekly_persist", "goal_update")
    graph.add_edge("trace_history", "trace_review")
    graph.add_edge("trace_review", "goal_update")
    graph.add_edge("backtest_compare", "goal_update")
    graph.add_edge("conflict_check", "goal_update")
    graph.add_edge("rm_explain", "goal_update")
    graph.add_edge("rm_portfolio_prepare", "rm_portfolio_persist")
    graph.add_edge("rm_portfolio_persist", "goal_update")
    graph.add_edge("compliance_risk", "goal_update")
    graph.add_edge("multi_agent_debate", "goal_update")

    graph.add_edge("goal_update", "finalize")

    graph.add_conditional_edges(
        "executor",
        _executor_next,
        {"tools": "tools", "finalize": "finalize", "end": "finalize"},
    )
    graph.add_edge("tools", "executor")

    graph.add_edge("finalize", "reflect")
    graph.add_edge("reflect", "output_guardrail")
    graph.add_edge("output_guardrail", END)

    return graph.compile(checkpointer=MemorySaver())


def run_agent(
    user_input: str,
    market: str = "a_share",
    role: str = "researcher",
    thread_id: str = "default",
    model_name: str | None = None,
    verbose: bool = True,
    client_risk_level: str | None = None,
    return_state: bool = False,
    output_language: str = "en",
    progress_cb: "ProgressCallback | None" = None,
):
    """Run the agent. Returns either the final string, or the full final state when
    ``return_state=True`` (used by the Streamlit frontend for pattern panels).

    ``output_language`` ("en" | "zh") is plumbed through state so downstream
    nodes (notably the Multi-Agent Debate specialists) can respect the UI
    language. Defaults to English to keep the CLI/professor-facing behaviour
    predictable; the Streamlit pages pass ``current_lang()`` explicitly.

    ``progress_cb`` is an optional sink invoked per LangGraph node completion
    with ``(phase_id, label, level)``. Pass the callback returned by
    ``frontend._progress_view.progress_view`` to drive an ``st.status`` box.
    """
    from agent._progress import label_for_node  # local import to avoid cycles
    RESOURCE_TRACKER.reset(thread_id)
    PATTERN_LOG.clear(thread_id)

    app = build_graph(model_name=model_name)
    config = {"configurable": {"thread_id": thread_id}}
    initial_state: AgentState = {
        "messages": [{"role": "user", "content": user_input}],
        "user_input": user_input,
        "market": market,
        "role": role,
        "client_risk_level": client_risk_level,
        "task_key": "",
        "route_reason": "",
        "route_confidence": 0.0,
        "data_strategy": "fresh_scan",
        "should_use_tools": True,
        "requires_trace_save": False,
        "execution_plan": "",
        "tool_call_count": 0,
        "last_tool_signature": "",
        "repeated_tool_call_count": 0,
        "stop_reason": "",
        "workflow_context": "",
        "task_payload": {},
        "latest_trace_path": "",
        "thread_id": thread_id,
        "output_language": output_language if output_language in {"en", "zh"} else "en",
        "goal_state": {},
        "goal_progress": 0.0,
        "input_guardrail": {},
        "output_guardrail": {},
        "hitl_request": {},
        "blocked": False,
        "memory_snippet": "",
        "reflection_rounds": [],
        "reflected": False,
        "debate_result": {},
        "mcp_enabled": True,
        "resource_usage": {},
        "extra": {},
    }

    last_state = None
    last_task_key = ""
    last_plan = ""
    last_route_reason = ""
    last_msg_count = 0

    # When a progress callback is attached we ask LangGraph for both update
    # diffs (so we can announce per-node progress) and the full value stream
    # (so the existing accumulation logic keeps working unchanged).
    if progress_cb is not None:
        lang_for_label = output_language if output_language in {"en", "zh"} else "en"
        progress_cb("start", label_for_node("start", lang_for_label), "info")
        stream_iter = app.stream(initial_state, config, stream_mode=["updates", "values"])
    else:
        stream_iter = (
            ("values", chunk) for chunk in app.stream(initial_state, config, stream_mode="values")
        )

    for mode, chunk in stream_iter:
        if mode == "updates":
            if progress_cb is None:
                continue
            for node_name in chunk.keys():
                # Skip pure plumbing nodes that only marshal state.
                if node_name in {"goal_update"}:
                    continue
                progress_cb(
                    node_name,
                    label_for_node(node_name, lang_for_label),
                    "info",
                )
            continue

        # mode == "values" — full accumulated state
        state = chunk
        last_state = state
        if verbose and state.get("task_key") and state.get("task_key") != last_task_key:
            _log_graph("stream", f"current task: {state['task_key']}")
            last_task_key = state["task_key"]
        if verbose and state.get("route_reason") and state.get("route_reason") != last_route_reason:
            confidence = state.get("route_confidence", 0.0)
            strategy = state.get("data_strategy", "unknown")
            tools_flag = "yes" if state.get("should_use_tools", True) else "no"
            _log_graph(
                "stream",
                f"route reason: {state['route_reason']} | strategy={strategy} | tools={tools_flag} | conf={confidence:.2f}",
            )
            last_route_reason = state["route_reason"]
        if verbose and state.get("execution_plan") and state.get("execution_plan") != last_plan:
            _log_graph("stream", "execution plan entered state")
            last_plan = state["execution_plan"]
        msgs = state.get("messages", [])
        if not verbose or len(msgs) <= last_msg_count:
            continue
        for m in msgs[last_msg_count:]:
            if hasattr(m, "tool_calls") and m.tool_calls:
                names = [tc.get("name", "?") for tc in m.tool_calls]
                _log_graph("tools", f"tool call: {', '.join(names)}")
            elif getattr(m, "type", "") == "tool" and hasattr(m, "name"):
                _log_graph("tools", f"tool returned: {m.name}")
        last_msg_count = len(msgs)

    if verbose and last_state and last_state.get("stop_reason"):
        _log_graph("stream", f"stop reason: {last_state['stop_reason']}", level="WARN")

    if progress_cb is not None:
        progress_cb("done", label_for_node("done", lang_for_label), "success")

    if last_state is None:
        return ""
    final_msg = last_state["messages"][-1]
    final_content = getattr(final_msg, "content", str(final_msg))
    if return_state:
        return {
            "final_answer": final_content,
            "state": last_state,
            "pattern_events": PATTERN_LOG.get(thread_id),
            "pattern_summary": PATTERN_LOG.summary(thread_id),
            "resource_usage": RESOURCE_TRACKER.summary(thread_id),
        }
    return final_content
