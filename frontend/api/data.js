/**
 * 数据管理 API（模块 D）。
 *
 * 依据：《S1-B 第二批 API 接口设计文档》§十一「数据管理 API（模块 D，2 个）」
 *       （后端实现：`app/api/v1/data.py` ＋ `app/services/data_service.py`，**已封板**）
 *
 * | API | Method / Path | 鉴权 | 落地子项 / 用途 |
 * |---|---|---|---|
 * | D-01 | `GET /me/data/summary` | ✅ | **本子项 3.1**：SC-20 数据总览（各指标条数 + 最早 / 最晚记录时间 + 合计） |
 * | D-02 | `POST /me/data/clear` | ✅ | **本子项 3.2**：SC-22 清空全部数据（**破坏性写**） |
 *
 * 关键口径（**后端已封板，前端不得偏离**）：
 *   - `D-01` **只返回条数与时间范围**，不含任何数值统计（数值统计属趋势页 S-03）；
 *   - `by_metric` 按后端 `metric_rules.METRIC_TYPES` **固定顺序**输出、且**只含有数据的指标**
 *     ⇒ 无数据时 `total_records = 0` / `by_metric = []`（**不是 404、不逐类返回 0 行**）；
 *   - `first_recorded_at` / `last_recorded_at` 为 `YYYY-MM-DD HH:mm:ss`；
 *   - 软删数据（`is_deleted = 1`）一律不计入；
 *   - `goals` = `{active_count, paused_count}`；`profile` = `{health_fields_filled, health_fields_total: 6}`。
 *
 * ★ **接口不返回「总量级」时间范围**：合计行的「时间范围 <起> ~ <止>」必须由**前端**从
 *   `by_metric` 的 `first_recorded_at` / `last_recorded_at` 逐项**聚合 min / max** 得到
 *   （S3-8 开工前只读预检报告 §6.1 G-8，已登记）。**不为此新增后端字段** —— `backend/` 本批零改动。
 *
 * ★ 本文件只封装 D-01 / D-02 两个接口；**不新增任何接口、不预造无使用方的封装**
 *   （两个函数分别与 SC-20 / SC-22 同步落地）。
 */
import { get, post } from '../utils/request'

/**
 * D-01 数据总览（SC-20）。
 * @returns {Promise<object>} 统一响应体；`data` 结构见本文件头注
 */
export function fetchDataSummary() {
    return get('/me/data/summary', null, { auth: true })
}

/**
 * D-02 清空全部数据（SC-22 区块 B，**破坏性写**）。
 *
 * 契约要点（`data_service.clear_all_data`，封板实现，前端不得偏离）：
 *   - 请求体为**三重确认**：`confirm_text` 必须逐字「确认删除」（`data_service.CONFIRM_TEXT`）、
 *     `acknowledge_irreversible` 必须**布尔 `true`**（字符串 `'true'` 不算已确认）、`password` 非空；
 *   - 服务端执行范围为**固定 4 项**（`health_records` / `record_tags` / `goals` /
 *     `profile_health_fields`，响应 `scope[]` 逐字回显）；
 *     **保留**：账号行、档案行（含昵称 / 性别 / 出生日期）、会话、登录失败状态、导出任务与既有导出文件；
 *   - **单事务**，任一步失败整体回滚（`500 INTERNAL_ERROR`，**不得出现"清一半"**）；
 *   - 失败码：`422 VALIDATION_FAILED`（带字段级 `errors[]`）｜`422 PASSWORD_INVALID`
 *     （★ 密码错**不累计失败次数、不触发锁定、不返回 429**）｜`500 INTERNAL_ERROR`；
 *   - 成功 `data = { deleted_records, deleted_tags, deleted_goals,
 *     profile_health_fields_cleared, account_kept, scope[] }`；
 *   - ★ **不接受任何范围扩展参数**：`include_profile_row` / `delete_account` 等**契约未定义、
 *     服务端一律无效果** ⇒ 本函数**不提供**相应入参（与 S1-C SC-22 ⑰ / 区分红线一致）。
 *   - 本接口**不消费** `Idempotency-Key`（`api/v1/data.py` 未读取该头）⇒ 本函数不传幂等键，
 *     不制造"看起来有防重、实际无效"的假保护。
 *
 * @param {object} payload `{ confirm_text, acknowledge_irreversible, password }`
 * @returns {Promise<object>} 统一响应体；`data` 结构见上
 */
export function clearAllData(payload) {
    return post('/me/data/clear', payload, { auth: true })
}
