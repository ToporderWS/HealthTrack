# -*- coding: utf-8 -*-
"""WSGI 入口 / 本地开发启动器。

用法：
- 本地开发：``python wsgi.py``（读取 ``APP_ENV``，默认 development）
- 生产（**V1.0 未部署**）：预留 WSGI 服务器入口，不在本批配置

⚠️ 本文件**不包含任何业务逻辑**。
"""
from __future__ import annotations

from app import create_app

app = create_app()

if __name__ == "__main__":
    # 仅本机开发使用；生产部署留待后续批次（V1.0 不上架）
    #
    # S3-9 子项 3.3 第 1 步「真机网络前置」（授权变更，2026-09-19）：
    # 原绑定 127.0.0.1 仅回环可达，局域网真机访问 http://192.168.1.8:5000
    # 会 ERR_CONNECTION_REFUSED（本机已复现），改为 0.0.0.0 使手机可达。
    # 0.0.0.0 同时包含回环地址，故本机 localhost / 127.0.0.1 行为不变；
    # 本入口仅用于本地开发联调，生产部署走 WSGI 服务器（见文件头说明），
    # 不改任何 API、数据库与业务逻辑。
    app.run(
        host="0.0.0.0",
        port=5000,
        debug=bool(app.config.get("DEBUG")),
    )
