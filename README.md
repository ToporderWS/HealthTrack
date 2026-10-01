# 康迹 HealthTrack

> 个人健康管理系统（V1.0）—— 用于记录与管理个人健康数据的移动端应用。
>
> **本项目不是医疗器械、不提供医疗诊断或医学建议。** 系统仅对用户自填数据进行**存储、展示与统计**，
> 不输出疾病诊断、医学结论、医学正常值/参考范围、用药建议或剂量建议。

---

## 一、项目状态

| 阶段 | 名称 | 状态 |
|---|---|---|
| S0 | 产品规划 | SEALED |
| S1-A | 需求与规则冻结 | SEALED |
| S1-B | 数据库 / API / 离线与隐私（三批） | SEALED |
| S1-C | UI/UX 低保真原型 | SEALED |
| S1-D | 技术方案最终冻结与环境实施准备 | SEALED |
| **S2** | **编码实施** | **进行中（第一批：工程骨架）** |

---

## 二、技术栈（S1-D 冻结）

| 层 | 选型 |
|---|---|
| 移动端 | UniApp + Vue3（JS）+ Pinia |
| 后端 | Python 3.11+ / Flask 3.x / SQLAlchemy 2.x / Marshmallow / Alembic |
| 数据库 | MySQL 8.0（InnoDB / utf8mb4 / utf8mb4_0900_ai_ci） |
| API | RESTful，Base 路径 `/api/v1` |
| 认证 | Access Token（JWT，2h）+ Refresh Token（30d，单次使用） |
| 开发工具 | HBuilderX（前端）+ WorkBuddy |

---

## 三、目录结构

```
.
├─ frontend/      UniApp + Vue3 移动端工程（HBuilderX 原生布局，S1-D §7 冻结）
│  ├─ pages/      页面（当前仅启动占位页 pages/index/index）
│  ├─ components/ 统一组件 G1～G15（占位）
│  ├─ api/        接口封装（占位）
│  ├─ store/      Pinia 实例
│  ├─ utils/      工具（占位）
│  ├─ static/     静态资源（占位）
│  ├─ App.vue / main.js / pages.json / manifest.json
│  └─ package.json                   仅声明前端第三方依赖（Pinia）
├─ backend/       Flask 后端应用
│  ├─ app/
│  │  ├─ api/v1/  路由层（Blueprint，当前仅 Y-01 健康检查）
│  │  ├─ models/  SQLAlchemy ORM 模型（8 张表）
│  │  ├─ schemas/ Marshmallow 序列化 / 校验（占位）
│  │  ├─ services/ 业务服务层（占位）
│  │  ├─ core/    配置 / 数据库 / 响应 / 错误 / 日志 / request_id
│  │  └─ tasks/   定时任务（占位）
│  ├─ migrations/ Alembic 迁移（0001_initial_schema）
│  ├─ tests/      后端测试
│  ├─ storage/    运行期临时文件（已 gitignore）
│  ├─ logs/       运行日志（已 gitignore）
│  ├─ .env.example / .env.development / .env.test / .env.production
│  ├─ requirements.txt
│  └─ wsgi.py
├─ database/
│  ├─ schema.sql  Alembic 离线生成的全量建表 DDL（8 表 / 17 索引）
│  └─ seeds/      字典 / 测试数据（占位）
├─ docs/          项目说明与操作手册
├─ scripts/
│  ├─ init_db_dev.sql        创建开发库与开发账号（密码占位符）
│  └─ verify_s2_batch1.py    S2 第一批骨架核验脚本（只读）
├─ tests/         端到端与验收脚本
├─ README.md
└─ .gitignore
```

---

## 四、环境要求

| 项 | 版本要求 | 本机实测 |
|---|---|---|
| Python | **3.11+** | 3.11.15 |
| Node.js | 18+ | 22.22.2 |
| npm | 随 Node | 10.9.7 |
| MySQL | 8.0 | 8.0.33（3306） |
| Git | 2.x | 2.53.0 |
| HBuilderX | 用于 UniApp 前端 | 5.24.2026081301 |

---

## 五、快速开始

### 5.1 后端

> 本机虚拟环境**已创建**：`backend\.venv`（Python **3.11.15**），依赖**已安装**。
> 以下步骤供换机 / 重建环境时使用。

```bash
cd backend

# 1) 创建虚拟环境（必须 Python 3.11+）
#    注意：本机系统 Python 3.7.8 不满足要求，须使用 3.11+
<PYTHON311>\python.exe -m venv .venv
# Windows 激活：.venv\Scripts\activate

# 2) 安装依赖
.venv\Scripts\python.exe -m pip install -r requirements.txt

# 3) 配置环境变量
#    复制 .env.example 为 .env.development，并填入本机 MYSQL_USER / MYSQL_PASSWORD
#    ⚠ 真实密钥只能写 .env*（已 gitignore），严禁写入代码 / 文档 / 日志

# 4) 创建数据库（先用管理员账号在 MySQL 客户端执行，并替换其中的占位密码）
#    scripts\init_db_dev.sql

# 5) 执行数据库迁移（建 8 张表 + 17 个索引）
.venv\Scripts\python.exe -m alembic upgrade head

# 6) 启动开发服务器
.venv\Scripts\python.exe wsgi.py        # 默认 127.0.0.1:5000
```

健康检查（Y-01）：`GET http://127.0.0.1:5000/api/v1/health` → `{"code":"OK","data":{"status":"up"},...}`

### 5.2 前端

本工程为 **HBuilderX 原生布局**（`pages.json` / `manifest.json` / `App.vue` / `main.js` 位于工程根），
uni-app 运行时与编译器由 HBuilderX 内置工具链提供，**不使用 `npm run dev:*` CLI 脚本**。

```bash
# 1) 安装前端第三方依赖（仅 Pinia 等，非 uni-app 工具链）
cd frontend
npm install
```

2) **用 HBuilderX 打开 `frontend/` 目录**（文件 → 打开目录），然后：
   - 运行 → 运行到浏览器 → Chrome（H5 验证）
   - 运行 → 运行到手机或模拟器（真机运行需手机开启 USB 调试）

> 前端 `package.json` **不声明** `@dcloudio/*` 构建工具链 —— 这是 HBuilderX 路线下的有意设计，
> 避免与 HBuilderX 内置编译器版本冲突。

### 5.3 一键核验（只读）

```bash
# 仅骨架（不连库，随时可跑）
backend\.venv\Scripts\python.exe scripts\verify_s2_batch1.py

# 追加数据库只读核验（需先在 backend\.env.development 填好 MYSQL_USER / MYSQL_PASSWORD）
backend\.venv\Scripts\python.exe scripts\verify_s2_batch1.py --db
```

脚本**只读**，不创建 / 修改 / 删除任何数据库对象与文件，不打印任何密码或令牌。

---

## 六、安全约定（强制）

1. **真实密钥只写 `backend/.env*`**（已 gitignore）；仓库只提交 `.env.example`（全占位符）。
2. 禁止把数据库密码、JWT 密钥、API Key 写入代码、文档、注释、日志或测试用例。
3. `user_id` **只能由服务端从认证上下文解析**，绝不信任客户端传参。
4. 任何跨用户资源访问统一按 **404** 处理。
5. 日志**不得**记录完整用户名、`user_id`、密码、Token、数据库密码或可识别个人信息的真实路径。

---

## 七、医疗安全红线（强制）

- ❌ 不诊断疾病、不判断病情、不输出医学结论
- ❌ 不提供医学风险判断、医学正常值 / 参考范围结论
- ❌ 不提供用药建议、剂量建议，不指导调整处方
- ✅ 「用药记录」仅为用户自填文本的**存储与展示**，不做任何医学解读
- ✅ 输入校验文案统一为中性提示（如「请确认是否输错」）

---

## 八、许可

内部项目，未发布。
