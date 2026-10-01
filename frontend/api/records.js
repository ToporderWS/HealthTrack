/**
 * 健康记录 API（模块 R）。
 *
 * 依据：《S1-B 第二批 API 接口设计文档》§七（后端实现：`app/api/v1/records.py` / `record_service.py`）
 *
 * | API | Method / Path | 鉴权 | 用途 |
 * |---|---|---|---|
 * | R-01 | `POST /api/v1/records` | ✅ | SC-08 保存一条记录（**带 `Idempotency-Key`**） |
 * | R-02 | `GET /api/v1/records` | ✅ | SC-10 历史列表（游标分页 + 半开区间筛选，**不返回 total**） |
 * | R-03 | `GET /api/v1/records/{id}` | ✅ | SC-09 详情 / SC-08 编辑模式预填 |
 * | R-04 | `PATCH /api/v1/records/{id}` | ✅ | SC-08 编辑模式保存（**不带 `metric_type`**） |
 * | R-05 | `DELETE /api/v1/records/{id}` | ✅ | SC-09 单条删除（软删；重复删除 → 404） |
 * | R-06 | `POST /api/v1/records/batch-delete` | ✅ | **S3-8 子项 3.2**：SC-22 批量删除（**破坏性写**） |
 * | R-07 | `GET /api/v1/records/count` | ✅ | **S3-8 子项 3.2**：SC-22「预览条数」（只读） |
 * | R-08 | `GET /api/v1/records/options` | ✅ | SC-08 录入选项字典（单位 / 枚举 / 饮水快捷值） |
 *
 * ★ 接口分期（如实登记）：S3-2 第二批只落地 **R-01 / R-08**；**R-02 ~ R-05 在 S3-3 落地**；
 *   **R-06 / R-07 于 S3-8 子项 3.2 落地**（SC-22 数据删除页）⇒ 至此本模块 8 个接口**全部有使用方**。
 *
 * 契约要点（客户端必须遵守）：
 *   - `user_id` **只来自 Access Token**：请求体中**绝不出现** `user_id`（出现即 400）；
 *   - `unit` **由服务端按指标自动填充**，客户端**不提交** `unit`
 *     （提交且与指标不一致 → 422「单位与指标不一致」）；
 *   - 录入合理性校验：**软提示 = HTTP 200 + `code = 'SOFT_WARNING'`**（当次**不写入**），
 *     客户端展示确认后「**原样重发同一请求 + `acknowledge_warnings: true`**」（S1-B §3.14）；
 *   - 硬拦截 / 字段矛盾 / 枚举非法 → **422 `VALIDATION_FAILED`** + 顶层 `errors[]`，**不写入**；
 *   - 幂等（§3.11）：**同 key + 同请求体 → 回放首次结果**；**同 key + 不同请求体 → 409 `IDEMPOTENCY_CONFLICT`**，
 *     窗口 10 分钟；服务端**只登记真正写入成功**的请求 ⇒ 软提示那一次**不占用** key，
 *     因此「确认后重发」**沿用同一 key 是安全的**（不会 409），且能继续防连击；
 *   - `recorded_at` 不得晚于当前时间（未来时间 → 422）。
 *
 * 写操作一律**不自动重试**（`utils/request.js` 已保证）。
 */
import { get, post, request } from '../utils/request'

/**
 * R-08 录入选项字典（静态常量，**不访问数据库**）。
 * @returns {Promise<object>} `data = { metric_types[], enums{}, water_quick_add[] }`
 *   - `metric_types[]`：`{ value, label, unit }`
 *   - `enums{}`：`bp_timing` / `heart_state` / `glucose_timing` / `sport_type` / `sport_intensity` / `mood_tags`
 *   - `water_quick_add[]`：如 `[200, 250, 500]`
 */
export function fetchRecordOptions() {
    return get('/records/options', null, { auth: true })
}

/**
 * R-01 新增一条健康记录。
 * @param {object} payload 记录字段（见 `utils/recordForm.js` 的字段矩阵），可含 `acknowledge_warnings`
 * @param {string} idempotencyKey `Idempotency-Key`（8–128 字符）
 * @returns {Promise<object>} 成功 `code = 'OK'`，`data = { record, derived, warnings }`；
 *   软提示 `code = 'SOFT_WARNING'`，`data = { requires_confirm, warnings[] }`
 */
export function createRecord(payload, idempotencyKey) {
    return post('/records', payload, { auth: true, idempotencyKey: idempotencyKey })
}

/**
 * R-02 记录列表（**游标分页 + 筛选**，S3-3 起用于 SC-10）。
 *
 * 契约要点（S1-B 第二批 §七 R-02）：
 *   - `limit` **默认 20，仅允许 20 / 50 / 100**；排序**固定** `recorded_at DESC, id DESC`；
 *   - 时间范围为**半开区间 `[start, end)`**（`start` 含、`end` 不含）；
 *   - 返回 `{ items[], next_cursor, has_more }` —— **不返回 `total`**；
 *   - 非法 / 伪造 `cursor` → **400**（不得回退为"从头发"）；
 *   - 软删数据永不返回。
 *
 * @param {object} params `{ metric_type?, start?, end?, limit?, cursor? }`
 * @returns {Promise<object>} `data = { items, next_cursor, has_more }`
 */
export function listRecords(params) {
    const query = {}
    const src = params || {}
    if (src.metric_type) {
        query.metric_type = src.metric_type
    }
    if (src.start) {
        query.start = src.start
    }
    if (src.end) {
        query.end = src.end
    }
    if (src.limit) {
        query.limit = src.limit
    }
    if (src.cursor) {
        query.cursor = src.cursor
    }
    return get('/records', query, { auth: true })
}

/**
 * R-03 记录详情（SC-09 / SC-08 编辑模式预填）。
 *
 * 契约要点：跨用户 `id` / 不存在 `id` / 已软删 `id` → **一律 404 `RESOURCE_NOT_FOUND`**
 * （不暴露"存在但无权"）。
 *
 * @param {number|string} id 记录 id
 * @returns {Promise<object>} `data = { record, derived }`
 */
export function getRecord(id) {
    return get('/records/' + encodeURIComponent(String(id)), null, { auth: true })
}

/**
 * R-04 修改记录（SC-08 编辑模式保存）。
 *
 * 契约要点（S1-B 第二批 §七 R-04）：
 *   - 请求体为 R-01 的**可编辑字段子集**（`value_1/2/3`、`attr_1/attr_2`、`recorded_at`、
 *     `time_start`、`tags`、`note`、`acknowledge_warnings`）；
 *   - **`metric_type` 不得出现**（传值 → 422，传相同值也拒绝）—— 故本函数**不接收**该字段；
 *   - 校验规则与 R-01 **完全一致**（软提示 / 硬拦截同口径）；
 *   - 404（不存在 / 非本人 / 已软删）/ 422（校验失败）。
 *
 * 说明：后端 `utils/request.js` 的通用 `request()` 已支持 `PATCH`（**写类不自动重试**），
 * 故此处不新增薄封装；`idempotencyKey` 为可选，仅在提供时附带请求头。
 *
 * @param {number|string} id 记录 id
 * @param {object} payload 可编辑字段子集（可含 `acknowledge_warnings`）
 * @param {string} [idempotencyKey] 幂等键（可选）
 * @returns {Promise<object>} `data = { record, derived, warnings }`
 */
export function updateRecord(id, payload, idempotencyKey) {
    return request({
        url: '/records/' + encodeURIComponent(String(id)),
        method: 'PATCH',
        data: payload === undefined ? null : payload,
        auth: true,
        idempotencyKey: idempotencyKey || null
    })
}

/**
 * R-05 单条删除（**软删**，二次确认由客户端弹窗完成 —— 冻结口径：单条不需密码）。
 *
 * 契约要点：**重复删除 → 404**（已不可见）。客户端须把 404 统一处理为「记录不存在」。
 *
 * @param {number|string} id 记录 id
 * @returns {Promise<object>} `data = { deleted_count }`
 */
export function deleteRecord(id) {
    return request({
        url: '/records/' + encodeURIComponent(String(id)),
        method: 'DELETE',
        data: null,
        auth: true
    })
}

/**
 * R-07 记录条数统计（SC-22「预览条数」）。
 *
 * 契约要点（`record_service.count_records`，已封板）：
 *   - **只返回条数**：`data = { count }`；软删数据不计入；
 *   - 筛选口径与 R-02 **完全一致**（时间范围为**半开区间 `[start, end)`**）；
 *   - `metric_type` **缺省 / 空串 = 不限指标**（即全部指标合计）；非枚举值 → `400 INVALID_PARAM`；
 *   - 本接口**不返回明细**（列表属 R-02）⇒ 仅用于「将删除 N 条记录」的预览。
 *
 * ★ 登记（S3-8 子项 3.2 发现的契约缺口，编号 **G-10**）：`metric_type` 为**单个字符串**
 *   ⇒ SC-22 的「指标多选」只能**逐指标各调一次**本接口再求和；全选 8 类时省略该参数走**单次**调用。
 *   本函数**只做单指标封装**，多目标编排在页面层（不在此制造隐性循环请求）。
 *
 * @param {object} params `{ metric_type?, start?, end? }`
 * @returns {Promise<object>} `data = { count }`
 */
export function countRecords(params) {
    const query = {}
    const src = params || {}
    if (src.metric_type) {
        query.metric_type = src.metric_type
    }
    if (src.start) {
        query.start = src.start
    }
    if (src.end) {
        query.end = src.end
    }
    return get('/records/count', query, { auth: true })
}

/**
 * R-06 批量删除（**软删**；SC-22 区块 A，属破坏性写）。
 *
 * 契约要点（`record_service.batch_delete`，封板实现，前端不得偏离）：
 *   - 请求体：`metric_type?` / `start?` / `end?` / **`password`（必填）** /
 *     `expected_count?` / `confirm_text?`（`acknowledge_warnings` 为录入软提示专用，本页不用）；
 *   - **服务端 COUNT 为准**，不采信客户端传值；`expected_count` 与实际不符 →
 *     `409 COUNT_MISMATCH`（`data = { expected_count, actual_count }`）**且不执行删除**；
 *   - 实际条数 ≥ `record_service.CONFIRM_THRESHOLD`（500）时，`confirm_text` 必须逐字「确认删除」，
 *     否则 `422 VALIDATION_FAILED`（字段级 `confirm_text`）；
 *   - **实际条数为 0 → 直接返回 `{ deleted_count: 0 }`**（属正常返回，**不是错误**）；
 *   - 密码错误 → `422 PASSWORD_INVALID`；★ 该验密**不累计登录失败次数、不触发锁定、不返回 429**
 *     （与登录锁定 / 导出验密计数完全无关）；
 *   - 幂等：消费 `Idempotency-Key`，**同 key + 同请求体回放首次结果；同 key + 不同请求体 → `409`
 *     `IDEMPOTENCY_CONFLICT`** ⇒ 多指标逐个删除时**每个请求必须各用一个新 key**。
 *
 * @param {object} payload `{ metric_type?, start?, end?, password, expected_count?, confirm_text? }`
 * @param {string} idempotencyKey `Idempotency-Key`（8–128 字符，**每次请求都要新的**）
 * @returns {Promise<object>} `data = { deleted_count }`
 */
export function batchDeleteRecords(payload, idempotencyKey) {
    return post('/records/batch-delete', payload, { auth: true, idempotencyKey: idempotencyKey })
}
