"""
从最新 Decision Trace 生成周报 Markdown。
用法: python scripts/generate_report.py [trace路径]
不传参数时自动取今日最新 trace。
"""
import os
import sys

if __package__ in {None, ""}:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.report_data import PROJECT_ROOT, build_report_data, load_trace


TEMPLATE_PATH = os.path.join(PROJECT_ROOT, "templates", "weekly_report.md")


def main():
    try:
        trace_arg = sys.argv[1] if len(sys.argv) > 1 else None
        trace, trace_path, trace_dir = load_trace(trace_arg)
    except FileNotFoundError:
        print("未找到今日 trace，请指定路径: python scripts/generate_report.py <trace.json>")
        sys.exit(1)

    if not trace_arg:
        print(f"使用 trace: {trace_path}")

    data = build_report_data(trace)

    with open(TEMPLATE_PATH, "r", encoding="utf-8") as f:
        tpl = f.read()

    for k, v in data.items():
        tpl = tpl.replace("{{" + k + "}}", str(v))

    out_path = os.path.join(trace_dir, "weekly_report.md")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(tpl)

    print(f"\n报告已生成: {out_path}")
    print(f"报告周: {data.get('report_week', 'N/A')}")
    print(f"数据区间: {data.get('data_timestamp', 'N/A')}")


if __name__ == "__main__":
    main()
