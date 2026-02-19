# STRM Webhook 生成服务

接收 CloudSaver 等外部服务的 webhook 回调，自动生成 STRM 文件。

## 快速开始

### Docker 部署（推荐）

```bash
# 1. 编辑配置
vim config.yaml

# 2. 构建并启动
docker-compose up -d

# 3. 查看日志
docker logs -f strm-webhook
```

### 裸机运行

```bash
pip install -r requirements.txt
python strm_webhook.py --config config.yaml
```

## 配置说明

编辑 `config.yaml` 或通过环境变量设置：

| 配置项 | 环境变量 | 说明 |
|---|---|---|
| `alist_url` | `ALIST_URL` | AList 服务地址 |
| `alist_token` | `ALIST_TOKEN` | AList API Token（可选） |
| `strm_server` | `STRM_SERVER` | STRM 内容链接前缀 |
| `strm_save_dir` | `STRM_SAVE_DIR` | STRM 文件保存目录 |
| `strm_replace_path` | `STRM_REPLACE_PATH` | 替换路径前缀（可选） |

## API 接口

### `POST /webhook/strm` — 主接口

接收目录路径，递归列出文件并生成 STRM。

```bash
curl -X POST http://localhost:9527/webhook/strm \
  -H "Content-Type: application/json" \
  -d '{"path": "/115/电影/xxx"}'
```

### `POST /webhook/strm/direct` — 直传模式

直接传入文件路径列表。

```bash
curl -X POST http://localhost:9527/webhook/strm/direct \
  -H "Content-Type: application/json" \
  -d '{"files": ["/115/电影/xxx/movie.mkv"]}'
```

### `GET /health` — 健康检查

### `GET /config` — 查看当前配置

## CloudSaver 配置

| 字段 | 值 |
|---|---|
| URL | `http://<webhook服务IP>:9527/webhook/strm` |
| Method | `POST` |
| Headers | `Content-Type: application/json` |
| Data | `{"path": "{保存资源的完整路径}"}` |
