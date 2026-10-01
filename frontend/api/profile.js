/**
 * 健康档案 API（模块 P，2 个）。
 *
 * 依据：《S1-B 第二批 API 接口设计文档》§六（后端实现：`app/api/v1/profile.py`）
 *
 * | API | Method / Path | 鉴权 | 本批用途 |
 * |---|---|---|---|
 * | P-01 | `GET /profile` | ✅ | SC-05 建档引导：读取已有档案以续填（未初始化 → **全 null 对象**，不是 404） |
 * | P-02 | `PUT /profile` | ✅ | SC-05 提交建档（UPSERT；**整体替换语义：省略即置空**） |
 *
 * 关键口径：
 *   - `PUT` 为**整体替换**：未提交的字段会被置空 → 前端必须一次性提交完整档案对象；
 *   - **不接受 `target_weight`**（D-1：目标体重唯一数据源 = `health_goal`，见 `api/goals.js`）；
 *   - 超出「录入合理性区间」→ **HTTP 200 + `SOFT_WARNING`，本次不写入**，
 *     需原样重发并置 `acknowledge_warnings = true`（S1-B §3.14）。
 */
import { get, put } from '../utils/request'

/** P-01 获取当前用户档案 */
export function getProfile() {
    return get('/profile', null, { auth: true })
}

/**
 * P-02 提交档案（整体替换）。
 * @param {object} body 完整档案对象（见 utils/validate.js 与 DESIGN.md 字段口径）
 * @param {boolean} acknowledgeWarnings 软提示确认后置 true（原样重发）
 */
export function updateProfile(body, acknowledgeWarnings) {
    const payload = {}
    const fields = [
        'nickname', 'gender', 'birth_date', 'height_cm',
        'initial_weight_kg', 'blood_type',
        'medical_history', 'allergy_history', 'medication_notes'
    ]
    fields.forEach(function (key) {
        payload[key] = body && body[key] !== undefined ? body[key] : null
    })
    payload.acknowledge_warnings = acknowledgeWarnings === true
    return put('/profile', payload, { auth: true })
}
