/**
 * 表单草稿（`kj:draft.*` 命名空间）—— SC-08 通用录入页专用。
 *
 * 依据：
 *   - S1-C §SC-08 ⑭③④：「点保存不发请求 → 提示『当前网络不可用，请联网后保存』+ **保留已填内容**
 *     + **写入草稿**」；「联网后**不自动重放**，仅在再次进入本页时提示
 *     『有未提交内容，是否继续？』（**仅回填，不自动提交**）」；
 *   - S1-C §SC-08 ⑬：未登录 → 重定向 SC-03 前**已填内容写入草稿**；
 *   - S1-B C6：**表单草稿（≤5 份、7 天）**；
 *   - S1-D §5：`kj:draft.*` 属登录态域，随「登出 / 注销 / 401 / 改密」四触发清除
 *     （前缀已在 `utils/storage.js` 的 `AUTH_SCOPED_PREFIXES` 登记，本模块无需重复声明）。
 *
 * ★ 红线（不得放宽）：
 *   草稿**只回填、绝不自动提交**；草稿内容不含任何医学判断，只有用户自己填的原始字段。
 *   草稿物理读写一律经 `utils/storage.js`（唯一本地读写入口）。
 */
import { readJson, writeJson, removeRaw, listKeys } from './storage'
import { formatStamp } from './cache'

/** 草稿键前缀（8 类指标各一份 ⇒ 键形如 `draft.record_weight`） */
export const DRAFT_PREFIX = 'draft.record_'

/** 草稿份数上限（S1-B C6 冻结：≤5 份） */
export const DRAFT_MAX = 5

/** 草稿有效期（S1-B C6 冻结：7 天） */
export const DRAFT_TTL_MS = 7 * 24 * 60 * 60 * 1000

/** 指标 → 草稿键 */
export function draftKey(metricType) {
    return DRAFT_PREFIX + String(metricType || '')
}

/**
 * 淘汰过期与超额草稿（写入 / 读取前调用）。
 * 规则：① 超过 7 天 → 删除；② 仍超过 5 份 → 按写入时刻淘汰最旧的。
 */
export function pruneDrafts() {
    const alive = []
    listKeys().forEach(function (key) {
        if (key.indexOf(DRAFT_PREFIX) !== 0) {
            return
        }
        const raw = readJson(key, null)
        const ts = raw && Number(raw.ts)
        if (!raw || !raw.form || !ts || Date.now() - ts > DRAFT_TTL_MS) {
            removeRaw(key)
            return
        }
        alive.push({ key: key, ts: ts })
    })
    if (alive.length > DRAFT_MAX) {
        alive.sort(function (a, b) { return a.ts - b.ts })
        alive.slice(0, alive.length - DRAFT_MAX).forEach(function (item) {
            removeRaw(item.key)
        })
    }
    return alive.length
}

/**
 * 写入草稿（不抛异常，失败不打断页面流程）。
 * @param {string} metricType 指标类型
 * @param {object} form 表单快照（只存用户已填字段）
 * @returns {boolean} 是否写入成功
 */
export function saveDraft(metricType, form) {
    if (!metricType || !form || typeof form !== 'object') {
        return false
    }
    const now = new Date()
    const ok = writeJson(draftKey(metricType), {
        ts: now.getTime(),
        saved_at: formatStamp(now),
        form: form
    })
    pruneDrafts()
    return ok
}

/**
 * 读取草稿。
 * @returns {{form: object, savedAt: string}|null} 不存在 / 已过期 → null
 */
export function loadDraft(metricType) {
    pruneDrafts()
    const raw = readJson(draftKey(metricType), null)
    if (!raw || !raw.form || typeof raw.form !== 'object') {
        return null
    }
    return {
        form: raw.form,
        savedAt: String(raw.saved_at || '')
    }
}

/** 删除草稿（保存成功后调用） */
export function dropDraft(metricType) {
    if (!metricType) {
        return false
    }
    return removeRaw(draftKey(metricType))
}
