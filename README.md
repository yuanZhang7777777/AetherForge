# AetherForge

电商详情页自动出图平台：FastAPI + Postgres + React/Vite，Docker Compose 部署。

## 主流程

1. ERP 或本地账号登录，前端通过 `/api/csrf/` 获取 CSRF token。
2. 创建项目，选择平台、国家、图片比例、分辨率和项目风格提示词。
3. 导入图片/文件夹或 ERP SKU；SKU 导入会用当前登录会话里的 ERP token 拉商品名和图片。
4. 预备生成：默认 legacy 链路保留 N1 可选视觉识别 + N2 分槽提示词；生产可切 `PROMPT_PIPELINE_MODE=gpt55_single`，用 APIMart GPT-5.5 单节点一次完成识别、身份锁、`style_brief` 和 9 张图提示词。
5. 正式生成：generation-worker 用 gpt-image-2 生图，用户改过中文策划的槽位会在提交前轻量重译英文 prompt；`DEEPSEEK_ENABLED=0` 时轻量文本 JSON 调用走 APIMart prompt 模型。
6. 结果页查看、双击放大、选择图片导出 ZIP；导出只包含当前项目 owner 的 completed 结果。

## 本地运行

```powershell
python -m pip install -r requirements.txt
cd frontend
npm install
npm run build
cd ..
python -m uvicorn backend.main:app --reload
```

本地默认使用 `sqlite:///./aetherforge.db`。真实 DeepSeek、APIMart、ERP、OSS 密钥只放 `.env`，不要提交。

## Docker 部署

Dockerfile 会把已构建的 `frontend/dist` 直接复制进镜像，所以前端改动必须先运行：

```powershell
cd frontend
npm run build
```

再部署：

```powershell
docker compose build web prompt-worker generation-worker
docker compose up -d
```

生产服务器目录是 `/opt/aetherforge`，对外端口默认 `18084`。

## 关键环境变量

- `PROMPT_PIPELINE_MODE=legacy|gpt55_single`：`gpt55_single` 用 APIMart GPT-5.5 一次完成识别+提示词。
- `DEEPSEEK_ENABLED=1|0`：关闭后不再调用 DeepSeek，文本 JSON 兜底走 APIMart。
- `DEEPSEEK_API_KEY` / `DEEPSEEK_BASE_URL` / `DEEPSEEK_PROMPT_MODEL`
- `REASONING_EFFORT_PROMPTS=low`：N2 分槽提示词生成档位。
- `REASONING_EFFORT_DEEP=high`：N2 并行失败后旧单次兜底路径使用。
- `MAX_TOKENS_PROMPTS=49152`：旧单次 9 槽兜底输出空间。
- `MAX_TOKENS_COMPILE=8192`：单槽提示词和生成前重译使用。
- `APIMART_API_KEY` / `APIMART_PROMPT_MODEL` / `APIMART_IMAGE_MODEL`
- `ERP_LOGIN_URL` / `PLATFORM_ADMIN_ERP_USERS`
- `CATALOG_QUERY_URL` / `CATALOG_ALLOWED_IMAGE_HOSTS`
- `DATABASE_URL` / `POSTGRES_PASSWORD`
- `SESSION_SECRET`
- `MAX_CONCURRENT_PREPARES` / `MAX_ACTIVE_GENERATIONS`

## 新增账号提示词模板

每个账号可以保存自己的项目风格提示词模板。数据表：

- `user_prompt_templates`
- 唯一约束：`(user_id, name)`

API：

- `GET /api/prompt-templates/`
- `POST /api/prompt-templates/`，body: `{ "name": "...", "content": "..." }`
- `DELETE /api/prompt-templates/{template_id}/`

模板按 `user_id` 隔离；同名保存会更新当前账号自己的模板，不影响其他账号。

## 验证

```powershell
python scripts\test_n_prompts_parallel.py
python scripts\test_prompt_templates.py
python scripts\test_persist_direct.py
cd frontend
npm test
npm run build
```

真实 DeepSeek 分槽验证：

```powershell
python scripts\test_n_prompts.py
```

该脚本需要有效的 `DEEPSEEK_API_KEY`。
