#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
STRM Webhook 生成服务
接收 CloudSaver 等外部服务的 webhook 回调，自动生成 STRM 文件

用法:
    python strm_webhook.py
    python strm_webhook.py --config /path/to/config.yaml
"""

import os
import sys
import yaml
import logging
import argparse
import requests
from flask import Flask, request, jsonify
from urllib.parse import quote

# ============================================================
# 日志配置
# ============================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("strm_webhook")

# ============================================================
# 默认配置
# ============================================================
DEFAULT_CONFIG = {
    "alist_url": "http://192.168.70.138:5244",
    "alist_token": "",
    "strm_server": "http://192.168.70.138:5244/d",
    "strm_save_dir": "/data/strm",
    "strm_replace_path": "",
    "host": "0.0.0.0",
    "port": 9527,
    "video_exts": ["mp4", "mkv", "flv", "mov", "m4v", "avi", "webm", "wmv", "ts", "rmvb"],
}


def load_config(config_path=None):
    """加载配置：config.yaml → 环境变量 → 默认值"""
    config = DEFAULT_CONFIG.copy()

    # 1. 从 YAML 文件加载
    if config_path and os.path.exists(config_path):
        with open(config_path, "r", encoding="utf-8") as f:
            file_config = yaml.safe_load(f) or {}
            config.update({k: v for k, v in file_config.items() if v is not None})
        logger.info(f"已加载配置文件: {config_path}")

    # 2. 环境变量覆盖（优先级最高）
    env_mapping = {
        "ALIST_URL": "alist_url",
        "ALIST_TOKEN": "alist_token",
        "STRM_SERVER": "strm_server",
        "STRM_SAVE_DIR": "strm_save_dir",
        "STRM_REPLACE_PATH": "strm_replace_path",
        "WEBHOOK_HOST": "host",
        "WEBHOOK_PORT": "port",
    }
    for env_key, config_key in env_mapping.items():
        env_val = os.environ.get(env_key)
        if env_val is not None:
            if config_key == "port":
                config[config_key] = int(env_val)
            else:
                config[config_key] = env_val

    # 确保 strm_server 格式正确
    if not config["strm_server"].startswith("http"):
        config["strm_server"] = f"http://{config['strm_server']}"
    config["strm_server"] = config["strm_server"].rstrip("/")
    if not config["strm_server"].endswith("/d"):
        config["strm_server"] += "/d"

    return config


# ============================================================
# AList API 交互
# ============================================================
class AListClient:
    """轻量 AList API 客户端"""

    def __init__(self, url, token=""):
        self.url = url.rstrip("/")
        self.headers = {}
        if token:
            self.headers["Authorization"] = token

    def list_dir(self, path, refresh=False):
        """
        列出 AList 目录内容
        refresh=True 时强制刷新缓存（115 新转存的文件可能需要）
        """
        api_url = f"{self.url}/api/fs/list"
        payload = {
            "path": path,
            "refresh": refresh,
            "password": "",
            "page": 1,
            "per_page": 0,
        }
        try:
            resp = requests.post(api_url, headers=self.headers, json=payload, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            if data.get("code") == 200:
                return data.get("data", {}).get("content") or []
            else:
                logger.error(f"AList list_dir 失败: {data.get('message')} (path={path})")
                return None
        except Exception as e:
            logger.error(f"AList list_dir 出错: {e} (path={path})")
            return None


# ============================================================
# STRM 生成器
# ============================================================
class StrmGenerator:
    """STRM 文件生成器"""

    def __init__(self, config):
        self.config = config
        self.alist = AListClient(config["alist_url"], config["alist_token"])
        self.video_exts = set(config["video_exts"])
        self.strm_server = config["strm_server"]
        self.strm_save_dir = config["strm_save_dir"]
        self.strm_replace_path = config.get("strm_replace_path", "")

    def generate_for_path(self, alist_path):
        """
        对指定 AList 路径生成 STRM 文件
        如果是目录则递归遍历，如果是文件则直接处理
        返回: {"created": [...], "skipped": [...], "errors": [...]}
        """
        result = {"created": [], "skipped": [], "errors": []}
        self._process_dir(alist_path, result, refresh=True)
        return result

    def _process_dir(self, dir_path, result, refresh=False):
        """递归处理目录"""
        items = self.alist.list_dir(dir_path, refresh=refresh)
        if items is None:
            result["errors"].append(f"无法列出目录: {dir_path}")
            return

        for item in items:
            item_name = item.get("name", "")
            item_path = f"{dir_path}/{item_name}".replace("//", "/")

            if item.get("is_dir"):
                # 递归处理子目录
                self._process_dir(item_path, result)
            else:
                # 处理文件
                self._process_file(item_path, result)

    def _process_file(self, file_path, result):
        """处理单个文件，判断是否为视频并生成 STRM"""
        ext = file_path.rsplit(".", 1)[-1].lower() if "." in file_path else ""
        if ext not in self.video_exts:
            return

        # 构造 STRM 保存路径
        strm_path = os.path.splitext(file_path)[0] + ".strm"
        strm_full_path = f"{self.strm_save_dir}{strm_path}".replace("//", "/")

        # 如果已存在则跳过
        if os.path.exists(strm_full_path):
            result["skipped"].append(strm_full_path)
            return

        # 创建目录
        strm_dir = os.path.dirname(strm_full_path)
        if not os.path.exists(strm_dir):
            os.makedirs(strm_dir, exist_ok=True)

        # 路径替换（可选）
        strm_file_path = file_path
        if self.strm_replace_path:
            # 替换第一段路径前缀
            parts = file_path.split("/", 2)  # ['', 'mount_path', 'rest...']
            if len(parts) >= 3:
                strm_file_path = f"{self.strm_replace_path}/{parts[2]}"

        # URL 编码路径
        strm_file_path = quote(strm_file_path, safe="/")

        # 写入 STRM
        strm_content = f"{self.strm_server}{strm_file_path}"
        try:
            with open(strm_full_path, "w", encoding="utf-8") as f:
                f.write(strm_content)
            result["created"].append(strm_full_path)
            logger.info(f"📺 STRM 生成成功 ✅ {strm_full_path}")
        except Exception as e:
            result["errors"].append(f"写入失败: {strm_full_path} ({e})")
            logger.error(f"📺 STRM 写入失败 ❌ {strm_full_path}: {e}")


# ============================================================
# Flask 应用
# ============================================================
def create_app(config):
    app = Flask(__name__)
    generator = StrmGenerator(config)

    @app.route("/webhook/strm", methods=["POST"])
    def webhook_strm():
        """
        主 webhook 接口 —— 接收 CloudSaver 的回调

        请求体示例:
            {"path": "/115/电影/xxx"}
            {"path": "/115/电影/xxx", "title": "电影名"}

        CloudSaver 占位符映射:
            path = 保存资源的完整路径 或 保存的资源文件夹名称
        """
        data = request.get_json(silent=True) or {}

        # 兼容多种参数名
        path = (
            data.get("path")
            or data.get("full_path")
            or data.get("folder_name")
            or data.get("savepath")
        )

        if not path:
            logger.warning(f"收到请求但缺少 path 参数，原始数据: {data}")
            return jsonify({
                "code": 400,
                "message": "缺少 path 参数",
                "hint": "请在请求体中包含 path 字段，值为 AList 上的目录路径",
                "received_data": data,
            }), 400

        # 确保路径以 / 开头
        if not path.startswith("/"):
            path = "/" + path

        logger.info(f"📥 收到 webhook 请求: path={path}")
        logger.info(f"   原始请求数据: {data}")

        try:
            result = generator.generate_for_path(path)

            summary = {
                "code": 200,
                "message": "STRM 生成完成",
                "path": path,
                "created_count": len(result["created"]),
                "skipped_count": len(result["skipped"]),
                "error_count": len(result["errors"]),
                "details": result,
            }
            logger.info(
                f"📊 生成结果: 新建={len(result['created'])}, "
                f"跳过={len(result['skipped'])}, "
                f"错误={len(result['errors'])}"
            )
            return jsonify(summary)

        except Exception as e:
            logger.exception(f"处理请求时出错: {e}")
            return jsonify({"code": 500, "message": f"服务内部错误: {e}"}), 500

    @app.route("/webhook/strm/direct", methods=["POST"])
    def webhook_strm_direct():
        """
        直传模式 —— 直接传入文件路径列表，不调用 AList API

        请求体示例:
            {"files": ["/115/电影/xxx/movie.mkv", "/115/电影/xxx/movie2.mp4"]}
        """
        data = request.get_json(silent=True) or {}
        files = data.get("files", [])

        if not files:
            return jsonify({"code": 400, "message": "缺少 files 参数"}), 400

        result = {"created": [], "skipped": [], "errors": []}
        for file_path in files:
            if not file_path.startswith("/"):
                file_path = "/" + file_path
            try:
                generator._process_file(file_path, result)
            except Exception as e:
                result["errors"].append(f"处理失败: {file_path} ({e})")

        return jsonify({
            "code": 200,
            "message": "STRM 直传生成完成",
            "created_count": len(result["created"]),
            "skipped_count": len(result["skipped"]),
            "error_count": len(result["errors"]),
            "details": result,
        })

    @app.route("/health", methods=["GET"])
    def health():
        """健康检查"""
        return jsonify({
            "status": "ok",
            "alist_url": config["alist_url"],
            "strm_save_dir": config["strm_save_dir"],
        })

    @app.route("/config", methods=["GET"])
    def show_config():
        """查看当前配置（隐藏 token）"""
        safe_config = config.copy()
        if safe_config.get("alist_token"):
            safe_config["alist_token"] = "***"
        return jsonify(safe_config)

    return app


# ============================================================
# 入口
# ============================================================
def main():
    parser = argparse.ArgumentParser(description="STRM Webhook 生成服务")
    parser.add_argument(
        "--config", "-c",
        default="config.yaml",
        help="配置文件路径 (默认: config.yaml)",
    )
    args = parser.parse_args()

    config = load_config(args.config)

    # 打印启动信息
    logger.info("=" * 50)
    logger.info("  STRM Webhook 生成服务")
    logger.info("=" * 50)
    logger.info(f"  AList 地址:  {config['alist_url']}")
    logger.info(f"  STRM 前缀:  {config['strm_server']}")
    logger.info(f"  保存目录:   {config['strm_save_dir']}")
    if config["strm_replace_path"]:
        logger.info(f"  路径替换:   → {config['strm_replace_path']}")
    logger.info(f"  监听地址:   {config['host']}:{config['port']}")
    logger.info("=" * 50)

    app = create_app(config)
    app.run(
        host=config["host"],
        port=config["port"],
        debug=False,
    )


if __name__ == "__main__":
    main()
