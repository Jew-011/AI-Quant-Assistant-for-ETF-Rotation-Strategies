from .data_tools import get_market_data, get_etf_flow_detail
from .factor_tools import calc_factors
from .scoring_tools import score_quadrant
from .filter_tools import get_ic_overlay_config
from .mapping_tools import map_etf
from .backtest_tools import run_backtest
from .news_tools import search_news, search_news_cn, get_macro_events
from .trace_tools import save_decision_trace, get_decision_history
from .report_tools import generate_report
from .rag_tools import search_research_library
from .mcp_tools import mcp_search_news_cn, mcp_get_macro_events, mcp_search_global_news

ALL_TOOLS = [
    get_market_data, get_etf_flow_detail,
    calc_factors, score_quadrant,
    get_ic_overlay_config, map_etf,
    run_backtest,
    search_news, search_news_cn, get_macro_events,
    save_decision_trace, get_decision_history,
    generate_report,
    search_research_library,
    mcp_search_news_cn, mcp_get_macro_events, mcp_search_global_news,
]
