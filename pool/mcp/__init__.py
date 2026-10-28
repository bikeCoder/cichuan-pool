"""MCP server（阶段C-01 / 路线图 D3）：CLI 的薄封装，主力 agent 接入层。

- 只做协议适配（JSON-RPC 2.0 over stdio，newline 分帧），不另起任何池逻辑；
  四工具内部直接调用 ``pool.cli.main`` 的命令函数，错误码与 CLI 完全一致；
- 权限分离：每个工具显式声明 access（read/write），``--read-only`` /
  ``POOL_MCP_READ_ONLY=1`` 闸在 tools/list 过滤写工具、在 tools/call 拒绝写调用；
- 本传输为 stdio：不打开任何 socket、不涉网络（tests 钉死）；远程传输/鉴权
  属阶段 D 托管范畴，明确不做。
"""
