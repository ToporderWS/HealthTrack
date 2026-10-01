/**
 * 统计 / 趋势 API（模块 S：S-02 趋势数据 · S-03 统计摘要）
 *
 * 依据：
 *   - 《S1-B 第二批 API 接口设计文档》§九；
 *   - 《S1-C 页面流程与状态矩阵》§五「页面 × API 矩阵」：`S-02` → SC-11、`S-03` → SC-11；
 *   - 后端实现：`backend/app/api/v1/stats.py`（`@bp.get('/stats/trend')` / `@bp.get('/stats/summary')`，
 *     均 `@require_auth`，**无请求体、不分页**）。
 *
 * | API | Method / Path | 鉴权 | 对应 F |
 * |---|---|---|---|
 * | S-02 | `GET /api/v1/stats/trend`   | ✅ | F-031～F-034 / F-036 |
 * | S-03 | `GET /api/v1/stats/summary` | ✅ | F-035 / F-046 |
 *
 * 契约要点（客户端必须遵守，逐条对应后端实现）：
 *   - `metric_type` **必填**，只能是 8 类指标之一（`weight` / `bp` / `heart` / `glucose` /
 *     `sleep` / `water` / `sport` / `mood`）；非法值 → `400 INVALID_PARAM`。
 *     ★ 后端不存在 `blood_pressure` / `heart_rate` 这类别名，客户端**不得**自行转换。
 *   - `window` 只能是 `7` / `30` / `90`（缺省 7）；窗口口径 `start = end - (days - 1)`，
 *     即**含今天在内的 N 天**（半开区间 `[start 00:00, end+1 00:00)`），
 *     由**服务端**计算并在响应 `window` 中回传 —— 客户端**不拼窗口**。
 *   - `end` 未传时由服务端取本地今天；本页不需要自定义区间（SC-10 才需要），故**不传 `end`**。
 *   - `group_by` 仅对 `glucose`（`timing`）/ `mood`（`tag`）有意义，属 S3-5/S3-8 范围，本批**不传**。
 *   - `user_id` **只来自 Access Token**：请求中**绝不出现** `user_id`（出现即 400）。
 *   - `tz_offset_minutes` **仅 S-01 使用**（后端 `_parse_tz` 只被 `home_overview` 消费）；
 *     S-02 / S-03 的日边界固定按服务器本地日，故本模块**不传**该参数。
 *
 * 幂等：GET，无写操作（因此统一请求层对 GET 的"失败重试 1 次"策略在此适用）。
 */
import { get } from '../utils/request'

/** 允许的时间窗口（与后端 `stats_service.WINDOW_DAYS` 逐字一致） */
export const TREND_WINDOWS = [7, 30, 90]

/** 缺省时间窗口（与后端 `stats_service.DEFAULT_WINDOW` 一致） */
export const DEFAULT_TREND_WINDOW = 7

/**
 * 归一化窗口值：非 7 / 30 / 90 → 回退缺省值 7。
 * 目的是**绝不给服务端发送非法参数**（避免无意义的 400）。
 * @param {number|string} window
 * @returns {number}
 */
export function normalizeWindow(window) {
    const n = Number(window)
    return TREND_WINDOWS.indexOf(n) >= 0 ? n : DEFAULT_TREND_WINDOW
}

/**
 * S-02 趋势数据。
 * @param {string} metricType 8 类指标之一
 * @param {number} window 7 / 30 / 90
 * @returns {Promise<object>} 统一响应体；`data` 含
 *   `{ metric_type, unit, window:{days,start,end}, chart:'line'|'bar', insufficient_data, points[],
 *      target_line?, groups?, weekly?, tag_distribution? }`
 *   ★ `points[]` **只含有记录的日期**（缺失日期不补零）——由服务端保证，客户端不得补点。
 */
export function fetchTrend(metricType, window) {
    return get('/stats/trend', {
        metric_type: String(metricType || ''),
        window: normalizeWindow(window)
    }, { auth: true })
}

/**
 * S-03 统计摘要（窗口规则与 S-02 **完全一致**，故必须传同一个 `window`）。
 * @param {string} metricType 8 类指标之一
 * @param {number} window 7 / 30 / 90
 * @returns {Promise<object>} 统一响应体；`data` 含
 *   `{ metric_type, unit, window, summary:{ average, change:{from,to,delta,from_date,to_date},
 *      max, min, reached_rate_percent, recorded_days:{recorded,total,percent}, ...各指标差异字段 } }`
 *   ★ 无记录时 `summary` 各项为 `null`、`recorded_days = {recorded:0,total:days,percent:0.0}`。
 */
export function fetchSummary(metricType, window) {
    return get('/stats/summary', {
        metric_type: String(metricType || ''),
        window: normalizeWindow(window)
    }, { auth: true })
}
