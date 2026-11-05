"""设备端MCP工具模块"""

from .mcp_client import MCPClient
from .mcp_handler import (
    send_mcp_message,
    handle_mcp_message,
    send_mcp_initialize_message,
    send_mcp_tools_list_request,
    call_mcp_tool,
)
from .mcp_executor import DeviceMCPExecutor
# 天气响应函数由 mcp_weather_handler 直接管理，此处仅导出供外部调用
from core.handle.mcp_weather_handler import send_weather_response


__all__ = [
    "MCPClient",
    "send_mcp_message",
    "handle_mcp_message",
    "send_mcp_initialize_message",
    "send_mcp_tools_list_request",
    "call_mcp_tool",
    "DeviceMCPExecutor",
    "send_weather_response",
]
