/**
 * 客户端即时校验（**前端提示，服务端裁决为唯一权威**）。
 *
 * 依据：《S1-B 第二批 API 接口设计文档》A-01 / A-02 / P-02 校验规则
 *   - 用户名：4–20 位；**字母开头**；仅字母 / 数字 / 下划线（服务端统一转小写存储）；
 *   - 密码：8–64 位；**必须同时包含字母与数字**；去首尾空格；**不得与用户名相同**（不区分大小写）；
 *   - 昵称：≤20 字；出生日期：`YYYY-MM-DD`，不得晚于今天、不早于 `1900-01-01`；
 *   - 身高：一位小数，**录入合理性区间 50–250**（超区间 → 软提示）；
 *   - 初始体重：一位小数，**录入合理性区间 20–300**（超区间 → 软提示）。
 *
 * 文案红线（DESIGN.md §12）：
 *   - **数值越界统一只写「数值超出常见范围，请确认是否输错」**（软提示可继续保存；硬拦截阻止保存）；
 *   - 不得出现任何医学正常值 / 参考范围 / 风险等级表述。
 */

/** 统一数值越界文案（DESIGN.md §12 固定值，不得改写） */
export const RANGE_TEXT = '数值超出常见范围，请确认是否输错'

const USERNAME_PATTERN = /^[A-Za-z][A-Za-z0-9_]{3,19}$/
const HAS_LETTER = /[A-Za-z]/
const HAS_DIGIT = /[0-9]/

/**
 * 用户名格式校验（非空 → 格式提示；返回 null 表示通过）。
 * @param {string} value 原始输入
 * @param {boolean} required 是否必填
 */
export function checkUsername(value, required) {
    const v = (value === null || value === undefined) ? '' : String(value).trim()
    if (!v) {
        return required ? '请输入用户名' : null
    }
    if (v.length < 4 || v.length > 20) {
        return '用户名需 4–20 位'
    }
    if (!/^[A-Za-z]/.test(v)) {
        return '用户名需以字母开头'
    }
    if (!USERNAME_PATTERN.test(v)) {
        return '只能包含字母、数字与下划线'
    }
    return null
}

/**
 * 密码强度校验。
 * @param {string} value 原始输入
 * @param {string} username 已填用户名（用于"不得与用户名相同"判定）
 * @param {boolean} required 是否必填
 */
export function checkPassword(value, username, required) {
    const raw = (value === null || value === undefined) ? '' : String(value)
    const v = raw.replace(/^\s+|\s+$/g, '')
    if (!v) {
        return required ? '请输入密码' : null
    }
    if (v.length < 8 || v.length > 64) {
        return '密码需 8–64 位'
    }
    if (!HAS_LETTER.test(v) || !HAS_DIGIT.test(v)) {
        return '密码需同时包含字母和数字'
    }
    const un = (username === null || username === undefined) ? '' : String(username).trim()
    if (un && v.toLowerCase() === un.toLowerCase()) {
        return '密码不能与用户名相同'
    }
    return null
}

/** 确认密码一致性校验 */
export function checkConfirmPassword(password, confirm, required) {
    if (!confirm) {
        return required ? '请再次输入密码' : null
    }
    if (String(password).replace(/^\s+|\s+$/g, '') !== String(confirm).replace(/^\s+|\s+$/g, '')) {
        return '两次输入的密码不一致'
    }
    return null
}

/** 昵称校验（≤20 字） */
export function checkNickname(value, required) {
    const v = (value === null || value === undefined) ? '' : String(value).trim()
    if (!v) {
        return required ? '请输入昵称' : null
    }
    if (v.length > 20) {
        return '昵称不超过 20 个字'
    }
    return null
}

/**
 * 出生日期校验（`YYYY-MM-DD`；不得晚于今天、不早于 1900-01-01）。
 * @returns {string|null} 错误文案
 */
export function checkBirthDate(value, required) {
    const v = (value === null || value === undefined) ? '' : String(value).trim()
    if (!v) {
        return required ? '请选择出生日期' : null
    }
    if (!/^\d{4}-\d{2}-\d{2}$/.test(v)) {
        return '出生日期格式不正确'
    }
    const today = todayString()
    if (v > today) {
        return '出生日期不能晚于今天'
    }
    if (v < '1900-01-01') {
        return '出生日期不能早于 1900-01-01'
    }
    return null
}

/** 今天的本地日期字符串 `YYYY-MM-DD`（口径：本地墙上时间，S1-D D-4） */
export function todayString() {
    const d = new Date()
    return formatDate(d)
}

/** Date → `YYYY-MM-DD`（本地时区） */
export function formatDate(date) {
    const y = date.getFullYear()
    const m = date.getMonth() + 1
    const day = date.getDate()
    return String(y) + '-' + pad2(m) + '-' + pad2(day)
}

/** 数字补零 */
export function pad2(n) {
    return n < 10 ? '0' + n : String(n)
}

/** 解析数字输入；非法 → null */
export function toNumber(value) {
    const v = (value === null || value === undefined) ? '' : String(value).trim()
    if (!v) {
        return null
    }
    if (!/^-?\d+(\.\d+)?$/.test(v)) {
        return null
    }
    const n = Number(v)
    return isNaN(n) ? null : n
}

/**
 * 通用「合理性区间」判定（仅识别异常输入，**不是医学参考范围**）。
 * @param {number} value 数值
 * @param {object} range { min, max }（含边界）
 * @returns {boolean} true = 落在范围内
 */
export function inRange(value, range) {
    if (value === null || value === undefined || isNaN(value)) {
        return false
    }
    if (range.min !== null && range.min !== undefined && value < range.min) {
        return false
    }
    if (range.max !== null && range.max !== undefined && value > range.max) {
        return false
    }
    return true
}

/**
 * 一位小数精度校验（仅识别异常输入）。
 * @returns {boolean} true = 小数位超限
 */
export function tooManyDecimals(value, allowed) {
    if (value === null || value === undefined || isNaN(value)) {
        return false
    }
    const s = String(value)
    const dot = s.indexOf('.')
    if (dot < 0) {
        return false
    }
    const decimals = s.length - dot - 1
    return decimals > allowed
}
