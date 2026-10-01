/**
 * 首页 / 统计 API（模块 S，本批仅使用 S-01）。
 *
 * 依据：《S1-B 第二批 API 接口设计文档》§九（后端实现：`app/api/v1/stats.py`）
 *
 * | API | Method / Path | 鉴权 | 对应 F |
 * |---|---|---|---|
 * | S-01 | `GET /api/v1/home/overview` | ✅ | F-010 / F-012 / F-013 |
 *
 * 契约要点（客户端必须遵守）：
 *   - **一次聚合**取回「今日概览 + 目标环 + 最近 10 条」，
 *     避免分多次请求造成口径不一致（S1-B §九「安全注意②」）；
 *   - `recent_records` **固定 10 条、不分页**（F-012 冻结）；
 *   - `reminder_fallback` 是「提醒兜底计数来自客户端本地」的**占位声明**，
 *     客户端**必须忽略**该字段（提醒模块无服务端表）；
 *   - 「今日」边界 = `[今日 00:00:00, 明日 00:00:00)`（半开区间）；
 *     客户端可传 `tz_offset_minutes` 让服务端按其本地日计算，缺省按服务器本地日；
 *   - `user_id` **只来自 Access Token**：请求中**绝不出现** `user_id`（出现即 400）。
 *
 * 幂等：GET，无写操作。
 */
import { get } from '../utils/request'

/**
 * 本机（客户端）时区偏移，单位分钟，符号遵循 `UTC + offset = 本地时间`。
 * 例：中国标准时间 UTC+8 → `-480`。
 */
export function localTzOffsetMinutes() {
    const offset = new Date().getTimezoneOffset()
    if (isNaN(offset)) {
        return null
    }
    return -offset
}

/**
 * S-01 首页概览。
 * @returns {Promise<object>} 统一响应体；`data` 含
 *   `{ date, today: { record_count, metric_types_recorded }, goals[], recent_records[], reminder_fallback }`
 */
export function fetchHomeOverview() {
    const params = {}
    const offset = localTzOffsetMinutes()
    if (offset !== null) {
        params.tz_offset_minutes = offset
    }
    return get('/home/overview', params, { auth: true })
}
