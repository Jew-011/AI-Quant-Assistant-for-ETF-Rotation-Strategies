"""
AI Quant Assistant for ETF Rotation Strategies — Entry Point

Usage:
    python main.py                          # Interactive CLI mode
    python main.py --query "生成本周周报"    # Single query mode
    streamlit run frontend/app.py           # Web UI mode
"""
import argparse
import os
import sys
from dotenv import load_dotenv

load_dotenv()
# Fall back to repo-bundled demo credentials when no .env is present, so
# a fresh clone is runnable with zero configuration.
try:
    from config._demo_keys import apply_demo_keys
    apply_demo_keys()
except Exception:
    pass

def _save_agent_response(content: str):
    """保存 Agent 回复到 traces/日期/agent_response.txt"""
    from datetime import datetime
    trace_dir = os.path.join(os.path.dirname(__file__), "traces")
    date_folder = datetime.now().strftime("%Y-%m-%d")
    folder = os.path.join(trace_dir, date_folder)
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, "agent_response.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path

def main():
    parser = argparse.ArgumentParser(description="AI Quant Assistant for ETF Rotation Strategies")
    parser.add_argument("--query", type=str, default=None, help="Single query to run")
    parser.add_argument("--report", action="store_true", help="从最新 trace 生成周报文件（HTML/DOCX/PDF）")
    parser.add_argument("--market", type=str, default="a_share", choices=["a_share", "hk", "us"])
    parser.add_argument("--role", type=str, default="researcher", choices=["researcher", "rm", "compliance"])
    parser.add_argument("--model", type=str, default=None, help="LLM model name (default: env OPENAI_MODEL or deepseek-v3.2)")
    args = parser.parse_args()

    from agent.graph import run_agent

    if args.report:
        from scripts.generate_report_html import main as gen_report
        gen_report([])  # 避免 --report 传入子脚本的 argparse
        return

    if args.query:
        model = args.model or os.getenv("OPENAI_MODEL", "deepseek-v3.2")
        print(f"\nMarket: {args.market} | Role: {args.role} | Model: {model}\n")
        print("Agent 启动中...（首次响应约 10–30 秒）", flush=True)
        result = run_agent(args.query, market=args.market, role=args.role, model_name=args.model)
        # 保存 Agent 回复，供报告生成使用
        _save_agent_response(result)
        print("\n" + "=" * 40 + "\n", flush=True)
        print(result)
        return

    # Interactive mode
    print("=" * 60)
    print("  AI Quant Assistant for ETF Rotation Strategies")
    print(f"  Market: {args.market} | Role: {args.role}")
    print("  Type 'quit' to exit")
    print("=" * 60)

    thread_id = "interactive_session"
    while True:
        try:
            user_input = input("\nYou: ").strip()
            if user_input.lower() in ("quit", "exit", "q"):
                print("Goodbye!")
                break
            if not user_input:
                continue

            print("\nAssistant: ", end="", flush=True)
            result = run_agent(user_input, market=args.market, role=args.role, thread_id=thread_id, model_name=args.model)
            print(result)
        except KeyboardInterrupt:
            print("\nGoodbye!")
            break
        except Exception as e:
            print(f"\nError: {e}")

if __name__ == "__main__":
    main()
