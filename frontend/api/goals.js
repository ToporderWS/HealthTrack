/**
 * 健康目标 API（模块 G）。
 *
 * 依据：《S1-B 第二批 API 接口设计文档》§八（后端实现：`app/api/v1/goals.py`）
 *
 * | API | Method / Path | 鉴权 | 用途 |
 * |---|---|---|---|
 * | G-01 | `GET /api/v1/goals` | ✅ | SC-12 目标列表（目标本体：类型 / 目标值 / 状态 / 周期） |
 * | G-02 | `POST /api/v1/goals` | ✅ | SC-05 建档写目标 ／ SC-13 新建目标 |
 * | G-03 | `PATCH /api/v1/goals/{id}` | ✅ | SC-13 修改目标（**局部更新**：省略字段 = 不修改） |
 * | G-04 | `POST /api/v1/goals/{id}/pause` | ✅ | SC-13 暂停 |
 * | G-05 | `POST /api/v1/goals/{id}/resume` | ✅ | SC-13 恢复 |
 * | G-06 | `DELETE /api/v1/goals/{id}` | ✅ | SC-13 删除（**软删三件事齐全**） |
 * | G-07 | `GET /api/v1/goals/progress` | ✅ | SC-12 完成度 + 达标率 |
 *
 * 落地分期（如实登记）：S3-1 只使用 **G-02**（SC-05 建档第 4 步「目标（可跳过）」）；
 *   **S3-5 补齐 G-01 / G-03 / G-04 / G-05 / G-06 / G-07**（SC-12 目标页 + SC-13 目标编辑页）。
 *
 * 服务端强制口径（客户端传值必须一致，否则 422）：
 *   - `period_type`：weight→`once` / water→`daily` / sport→`weekly` / sleep→`daily`；
 *   - `unit`：weight→`kg` / water→`ml` / sleep→`hour` / sport 随 `attr_1`
 *     （`min`→`min`、`count`→`count`）；
 *   - `attr_1`：**仅 sport**，且必填（`count` = 周次数 / `min` = 周分钟）；
 *   - `start_weight_kg`：**仅 weight**（起始快照，**创建后不可改** —— PATCH 出现即 422）；
 *   - `target_date`：**仅 weight 可填**（其他类型传值 → 422）；
 *   - 目标值有「硬拦截区间」（超出即 422）与「软提示区间」（HTTP 200 `SOFT_WARNING`，
 *     **本次不写入**，用户确认后原样重发并带 `acknowledge_warnings: true`）——
 *     **两套区间都不在客户端复制**，一律以服务端判定为准；
 *   - 同类型在用目标已存在 → `409 GOAL_TYPE_EXISTS`。
 *
 * 幂等说明：G 模块**明确不接入** `Idempotency-Key`（后端 `app/api/v1/goals.py` 模块注释），
 * 因此本批不发送该头，以「按钮立即 disabled + loading」防重复提交。
 *
 * 本文件是「目标体重」的**唯一合法写入通道**（DESIGN.md §14.8 / S1-D D-1：
 * 目标体重唯一数据源 = `health_goal(goal_type='weight')`，档案接口不承载该字段）。
 */
import { get, post, request } from '../utils/request'

/** `goal_type` → 服务端强制的 `period_type`（客户端传值必须与服务端一致） */
export const GOAL_PERIOD = {
    weight: 'once',
    water: 'daily',
    sport: 'weekly',
    sleep: 'daily'
}

/**
 * `goal_type` → 服务端填充的 `unit`。
 *
 * ⚠️ `sport` 的取值**随 `attr_1` 变化**（`min` = 周分钟 / `count` = 周次数）：
 *    本表给出的是**默认值**（`attr_1` 缺省时）。组装请求体请统一走 `unitOf()`，
 *    否则「周次数」目标会因 `unit` 与 `attr_1` 不一致被判 422。
 */
export const GOAL_UNIT = {
    weight: 'kg',
    water: 'ml',
    sleep: 'hour',
    sport: 'min'
}

/** 4 类目标的**展示顺序**（S1-C SC-12 原型顺序：体重 → 饮水 → 运动 → 睡眠） */
export const GOAL_TYPE_ORDER = ['weight', 'water', 'sport', 'sleep']

/** `sport` 的计量方式（与后端 `goal_service.SPORT_ATTRS` 一致；**单选**） */
export const SPORT_ATTRS = ['count', 'min']

/** 达标率窗口（与后端 `goal_progress.WINDOW_DAYS` 一致；其他值 → 400 INVALID_PARAM） */
export const RATE_WINDOWS = [7, 30, 90]

/** 默认达标率窗口（S3-5 裁定：SC-12 使用「近 7 天」口径） */
export const DEFAULT_RATE_WINDOW = 7

/**
 * 按 `goal_type` + `attr_1` 解析服务端期望的 `unit`（本模块**唯一出口**，勿在别处硬编码）。
 * @param {string} goalType 4 类之一
 * @param {string} [attr1] 仅 sport 使用（`count` / `min`）
 * @returns {string} 与后端 `goal_service.unit_for()` 同口径
 */
export function unitOf(goalType, attr1) {
    if (goalType === 'sport') {
        return attr1 === 'count' ? 'count' : 'min'
    }
    return GOAL_UNIT[goalType] || ''
}

/**
 * G-01 目标列表（**不分页**）。
 *
 * 契约要点：
 *   - **不传 `include_paused`**：服务端默认 `true`（结果**含已暂停目标**）——
 *     SC-12 需要把「已暂停」显示出来，故本模块不暴露该参数；
 *   - `include_history` 本批**不使用**（已软删历史行的只读展示属后续批次）；
 *   - 排序由服务端固定为 `goal_type ASC, id ASC`（字母序）；
 *     **展示顺序由页面按 `GOAL_TYPE_ORDER` 重排**；
 *   - 元素**主键字段名是 `id`**（注意与 G-07 的 `goal_id` 不同）。
 *
 * @param {object} [params] `{ goal_type?, include_history? }`
 * @returns {Promise<object>} `data = { items: [...] }`
 */
export function fetchGoals(params) {
    const src = params || {}
    const query = {}
    if (src.goal_type) {
        query.goal_type = src.goal_type
    }
    if (src.include_history === true) {
        query.include_history = true
    }
    return get('/goals', query, { auth: true })
}

/**
 * G-07 目标完成度（**不分页**；派生值实时计算、**不落库**）。
 *
 * 契约要点：
 *   - `rate_window` 仅允许 **7 / 30 / 90**（服务端默认 30；其他值 → 400）；
 *   - 元素**主键字段名是 `goal_id`**（注意与 G-01 的 `id` 不同）；
 *   - `weight` 目标的 `rate` **恒为 `null`**（无每日 / 每周周期，不计算达标率）；
 *   - `days_recorded = 0` → `reached_rate_percent = null`（不除零、**不补零**）；
 *   - 保护口径：无可用数据时 `progress_percent` / `remaining_value` / `remaining_text`
 *     均为 `null` —— 客户端**不得**把 `null` 显示成 `0`。
 *
 * @param {number|string} [rateWindow] 7 / 30 / 90（非法值归一为默认窗口 7）
 * @returns {Promise<object>} `data = { items: [...] }`
 */
export function fetchGoalsProgress(rateWindow) {
    const n = Number(rateWindow)
    const days = RATE_WINDOWS.indexOf(n) >= 0 ? n : DEFAULT_RATE_WINDOW
    return get('/goals/progress', { rate_window: days }, { auth: true })
}

/**
 * G-02 创建目标。
 *
 * @param {object} payload
 *   `{ goal_type, target_value, attr_1?(仅 sport), target_date?(仅 weight),
 *      start_date?, start_weight_kg?, auto_start_weight?, acknowledge_warnings? }`
 *   - **`auto_start_weight: true`**（仅 weight）：由服务端取「最近一条体重记录」作为起始体重
 *     （**无记录 → 422，不估算**）—— SC-13 采用该口径，因此页面**不设**「起始体重」输入框；
 *   - 若同时显式给出 `start_weight_kg`，则按显式值提交（SC-05 建档沿用的旧口径，**行为未变**）。
 * @returns {Promise<object>} 成功 `code = 'OK'`（HTTP 201），`data = { goal, warnings }`；
 *   软提示 `code = 'SOFT_WARNING'`（**本次未写入**），`data` 含 `requires_confirm` / `warnings[]`
 */
export function createGoal(payload) {
    const type = payload.goal_type
    // sport 的计量方式先定，unit 必须与之一致（否则 422「单位与计量方式不一致」）
    const attr1 = type === 'sport' ? (payload.attr_1 || SPORT_ATTRS[1]) : null
    const body = {
        goal_type: type,
        // 与服务端强制值保持一致（避免"周期不匹配"的 422）
        period_type: GOAL_PERIOD[type],
        target_value: payload.target_value,
        unit: unitOf(type, attr1),
        acknowledge_warnings: payload.acknowledge_warnings === true
    }
    if (type === 'sport') {
        body.attr_1 = attr1
    }
    if (payload.start_date) {
        body.start_date = payload.start_date
    }
    if (type === 'weight') {
        // 仅 weight 可填目标日期（其他类型传值 → 422）
        if (payload.target_date) {
            body.target_date = payload.target_date
        }
        // 起始体重：优先显式值（SC-05 口径）；否则按需请求服务端自动取最近一条记录（SC-13 口径）
        if (payload.start_weight_kg !== undefined && payload.start_weight_kg !== null) {
            body.start_weight_kg = payload.start_weight_kg
        } else if (payload.auto_start_weight === true) {
            body.auto_start_weight = true
        }
    }
    return post('/goals', body, { auth: true })
}

/**
 * G-03 修改目标（**真正的局部更新**：未出现的字段保持原值）。
 *
 * 契约要点：
 *   - **`goal_type` 不得出现**（即使值相同也 422 —— 类型不同即"另一个目标"）；
 *   - **`start_weight_kg` 不得出现**（起始快照一经创建即冻结）；
 *   - 允许字段：`target_value` / `unit` / `attr_1` / `start_date` / `target_date` /
 *     `acknowledge_warnings`；
 *   - 校验规则与 G-02 **完全一致**（硬拦截 422 / 软提示 `SOFT_WARNING`）。
 *
 * 说明：`utils/request.js` 的通用 `request()` 已支持 `PATCH`（**写类不自动重试**），
 * 故此处不新增薄封装。
 *
 * @param {number|string} id 目标 id（G-01 的 `id`）
 * @param {object} payload 可修改字段子集（可含 `acknowledge_warnings`）
 * @returns {Promise<object>} `data = { goal, warnings }`
 */
export function updateGoal(id, payload) {
    return request({
        url: '/goals/' + encodeURIComponent(String(id)),
        method: 'PATCH',
        data: payload === undefined ? null : payload,
        auth: true
    })
}

/**
 * G-04 暂停目标（**已暂停再调 → `changed: false`，不报错**）。
 * @param {number|string} id 目标 id
 * @returns {Promise<object>} `data = { id, status, changed }`
 */
export function pauseGoal(id) {
    return post('/goals/' + encodeURIComponent(String(id)) + '/pause', null, { auth: true })
}

/**
 * G-05 恢复目标（已进行中再调 → `changed: false`；
 * 同类型已有**另一条**在用目标 → `409 GOAL_TYPE_EXISTS`，不得产生两个在用目标）。
 * @param {number|string} id 目标 id
 * @returns {Promise<object>} `data = { id, status, changed }`
 */
export function resumeGoal(id) {
    return post('/goals/' + encodeURIComponent(String(id)) + '/resume', null, { auth: true })
}

/**
 * G-06 删除目标（**软删**；二次确认由客户端弹窗完成 —— 冻结口径：单条不需密码）。
 *
 * 契约要点：软删三件事齐全（`is_deleted` + `deleted_at` + `deleted_marker`），
 * 物理行保留；**重复删除 → 404**（客户端须统一处理为「目标不存在」）。
 *
 * @param {number|string} id 目标 id
 * @returns {Promise<object>} `data = { deleted_count }`
 */
export function deleteGoal(id) {
    return request({
        url: '/goals/' + encodeURIComponent(String(id)),
        method: 'DELETE',
        data: null,
        auth: true
    })
}
