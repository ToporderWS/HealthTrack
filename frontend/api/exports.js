/**
 * 数据导出 API（模块 E）。
 *
 * 依据：《S1-B 第二批 API 接口设计文档》§十「数据导出 API（模块 E，4 个）」
 *       （后端实现：`app/api/v1/exports.py` ＋ `app/services/export_service.py`，**已封板**）
 *
 * | API | Method / Path | 鉴权 | 落地子项 / 用途 |
 * |---|---|---|---|
 * | E-01 | `POST /exports` | ✅ | **本子项 3.3**：SC-21 创建导出任务（**同步生成**，成功即 `ready`，HTTP **202**） |
 * | E-02 | `GET /exports/{id}` | ✅ | **本子项 3.3**：任务查询 —— **下载凭证 `file_token` 的唯一来源** |
 * | E-03 | `GET /exports/{id}/download?file_token=` | ✅ 双重校验 | **本子项 3.3**：下载（**文件流**，`id + user_id + file_token` 三条件） |
 * | E-04 | `GET /exports` | ✅ | **本子项 3.3**：历史任务列表（游标分页，`created_at DESC`） |
 *
 * 关键口径（**后端已封板，前端不得偏离**）：
 *   - **E-01 每次必二次验密，无豁免**（`S1-A §4`：不因数据少而豁免）；密码错 → `422 PASSWORD_INVALID`，
 *     同一会话连错 `VERIFY_MAX_EXPORT`(3) 次 → `429 SESSION_VERIFY_ABORTED`（**不纳入登录锁定**，
 *     计数在 `user_session.export_pwd_fail_count`），**验密成功即清零**；
 *   - **E-01 消费 `Idempotency-Key`**（`idempotency.lookup/remember`）⇒ 同一 key + 不同请求体 → `409 IDEMPOTENCY_CONFLICT`；
 *     ⇒ **每次生成各用一个全新 key**（`newIdempotencyKey()`），**不得复用**；
 *   - **E-01 请求体**：`format`（必填，`csv` / `json`）｜`metric_types`（**`null` = 全部指标**；
 *     数组则逐项须在 `METRIC_TYPES` 内；**空数组 → `400`**）｜`range_start` / `range_end`（**半开区间 `[start, end)`**，
 *     接受 `YYYY-MM-DD` 或 `YYYY-MM-DD HH:mm:ss`；`start >= end` → `400`；**不传 = 不限时间**）｜`password`（必填）；
 *   - **已有 `pending` / `ready` 任务 → `409 EXPORT_IN_PROGRESS`**（`expired` / `purged` 按当前时间动态判定，
 *     **窗口已过不再阻塞**新导出）；
 *   - **★ E-01 的响应 `data` 里「没有」 `file_token`**（`{export_id, format, status, record_count,
 *     download_expires_at, purge_at, created_at}`）⇒ **要下载必须先经 E-02 取凭证**，这不是可选步骤；
 *   - **★ E-03 返回文件流、不是 JSON 包装**（故后端不用 `api_response`）⇒ **不能走 `utils/request.js`**
 *     （它只解析 `{code, message, data}` 信封）⇒ 本模块只提供 **URL 构造函数** `exportDownloadUrl()`，
 *     由页面用 `uni.downloadFile`（可带 `Authorization` 头）取回 blob 后交给浏览器下载；
 *   - **★ `Content-Disposition` 不在 H5 开发期的 CORS 暴露名单内**
 *     （`backend/app/core/cors.py#DEV_CORS_EXPOSE_HEADERS` **只有 `X-Request-Id`**）
 *     ⇒ 前端**读不到服务端文件名** ⇒ 由 `exportFileName()` 按服务端 `export_service.download_filename`
 *     的**同一条规则**推导（`healthtrack_export_<YYYYMMDD>.<ext>`，不含用户名 / user_id）；
 *   - **★ E-04 的 `items[]` 不含 `file_token`，也不含任何 range 字段**
 *     （`export_service.job_view()` 只给 `export_id / format / status / record_count / file_size_bytes /
 *     download_expires_at / purge_at / downloaded_at / created_at`）⇒
 *     `S1-C SC-21 ⑨` 要求的「**范围**」列**没有数据来源**（登记 **G-11**，前端如实以「格式 · 条数」替代，
 *     **不臆造范围**、也不为此新增后端字段 —— `backend/` 本批零改动）；
 *   - **E-04 无 `total`**（游标分页）：`limit` 默认 20 / 上限 100；返回 `{items, next_cursor, has_more}`；
 *   - **有效期**：`download_expires_at` = 生成 + 10 分钟（可下载窗口）；`purge_at` = 生成 + 60 分钟；
 *     超窗 → `410 EXPORT_EXPIRED`；非本人 / token 不符 → `404 RESOURCE_NOT_FOUND`（**不暴露存在性**）；
 *   - **响应永不返回 `file_path`**；导出内容不含软删数据 / `user_id` / 数据库内部主键。
 *
 * ★ 安全红线（`S1-A §4/§8`，**与 SC-21 红线同源**）：`file_token` **用完即弃、不得持久缓存** ⇒
 *   本模块**只负责取得凭证**，**绝不**把它写进 `storage` / `cache`；凭证仅由页面在**内存**中短暂持有，
 *   下载结束即丢（页面 `data` 中也不保留）。本文件内不出现任何落盘调用。
 *
 * ★ 本文件只封装 E-01~E-04 四个接口（+1 个 URL 构造函数 +1 个文件名推导函数），
 *   **不新增任何接口、不预造无使用方的封装**；`E-01~E-04` 与 SC-21 同步落地。
 */
import { get, post } from '../utils/request'
import { API_BASE_URL } from '../utils/config'

/** 文件名前缀 —— 与后端 `export_service.EXPORT_FILENAME_PREFIX` **逐字同值** */
const EXPORT_FILENAME_PREFIX = 'healthtrack_export'

/** 允许的导出格式 —— 与后端 `export_service.ALLOWED_FORMATS` **同序同值** */
const ALLOWED_FORMATS = ['csv', 'json']

/** 两位补零 */
function pad2(value) {
    return value < 10 ? '0' + value : String(value)
}

/**
 * 把 `created_at`（`YYYY-MM-DD HH:mm:ss`）压成服务端同款的 8 位日期串。
 * 取不到时回落到**客户端当天**（与后端 `download_filename` 的 `now_local()` 回落同义）。
 */
function fileDay(createdAt) {
    const head = String(createdAt || '').slice(0, 10)
    const parts = head.split('-')
    if (parts.length === 3 && parts[0] && parts[1] && parts[2]) {
        return parts[0] + parts[1] + parts[2]
    }
    const now = new Date()
    return String(now.getFullYear()) + pad2(now.getMonth() + 1) + pad2(now.getDate())
}

/**
 * E-01 创建导出任务（**同步生成**；成功即 `ready`，HTTP **202**）。
 *
 * ★ 每次调用**必须传入一个全新的** `idempotencyKey`：该接口消费 `Idempotency-Key`，
 *   而同一 key 配不同请求体会被判 `409 IDEMPOTENCY_CONFLICT`（前端"重试"时尤其容易踩）。
 *
 * @param {object} payload `{ format, metric_types, range_start, range_end, password }`
 *        —— `metric_types` 传 `null` 表示**全部指标**（**不可传空数组**）；
 *           `range_start` / `range_end` 留空表示**不限时间**（「全部」）
 * @param {string} idempotencyKey 全新的幂等键（`newIdempotencyKey()`）
 * @returns {Promise<object>} 统一响应体；`data = {export_id, format, status, record_count,
 *          download_expires_at, purge_at, created_at}`（**不含 `file_token`**）
 */
export function createExport(payload, idempotencyKey) {
    return post('/exports', payload, { auth: true, idempotencyKey: idempotencyKey })
}

/**
 * E-02 导出任务查询 —— **下载凭证的唯一来源**。
 *
 * `data.file_token` **仅当任务当前可下载**（`ready` / `downloaded`）时给值，
 * 其余状态一律 `null`（后端缩小凭证暴露面）⇒ 前端据此判定「能不能下载」，
 * **不自行推断可用性**。
 *
 * @param {number|string} exportId 任务 ID
 * @returns {Promise<object>} 统一响应体；`data` 同 E-01 视图 + `file_size_bytes` /
 *          `downloaded_at`，**且含 `file_token`**（不可下载时为 `null`）
 */
export function fetchExport(exportId) {
    return get('/exports/' + exportId, null, { auth: true })
}

/**
 * E-04 导出任务列表（历史任务区块）。
 *
 * ★ 返回项**不含 `file_token`**、**不含任何 range 字段**（见本文件头注 G-11）
 *   ⇒ 列表行的「下载」必须先调 E-02 取凭证（懒取，缩小凭证暴露面）。
 *
 * @param {object} [params] `{ limit, cursor }` —— `limit` 默认 20 / 上限 100；`cursor` 取自上一页 `next_cursor`
 * @returns {Promise<object>} 统一响应体；`data = {items[], next_cursor, has_more}`
 */
export function fetchExports(params) {
    const query = {}
    const src = params || {}
    if (src.limit) {
        query.limit = src.limit
    }
    if (src.cursor) {
        query.cursor = src.cursor
    }
    return get('/exports', query, { auth: true })
}

/**
 * E-03 下载地址（**纯字符串构造，不发请求**）。
 *
 * 为什么放在 API 层：服务端下载是**文件流**，只能交给 `uni.downloadFile` 取回
 * （`utils/request.js` 只解析 JSON 信封，不适用）⇒ URL 的拼接规则属本模块的边界知识。
 * 调用方须自带 `Authorization` 头（`uni.downloadFile` 的 `header`）。
 *
 * @param {number|string} exportId 任务 ID
 * @param {string} fileToken E-02 返回的下载凭证（**仅内存持有**）
 * @returns {string} 完整 URL
 */
export function exportDownloadUrl(exportId, fileToken) {
    return API_BASE_URL + '/exports/' + exportId + '/download?file_token=' + encodeURIComponent(String(fileToken || ''))
}

/**
 * 推导下载文件名（**读不到 `Content-Disposition`**，故客户端按同规则生成）。
 *
 * 与后端 `export_service.download_filename()` **同一条规则**：
 *   - 前缀固定 `healthtrack_export`（**不含用户名 / user_id**）；
 *   - 日期取任务 `created_at` 的 `YYYYMMDD`；
 *   - 扩展名跟 `format`（`json` → `.json`，其余 → `.csv`）。
 *
 * @param {string} format `csv` / `json`
 * @param {string} createdAt 任务 `created_at`（`YYYY-MM-DD HH:mm:ss`）
 * @returns {string} 形如 `healthtrack_export_20260918.csv`
 */
export function exportFileName(format, createdAt) {
    const ext = String(format) === 'json' ? ALLOWED_FORMATS[1] : ALLOWED_FORMATS[0]
    return EXPORT_FILENAME_PREFIX + '_' + fileDay(createdAt) + '.' + ext
}
