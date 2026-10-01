/**
 * 业务缓存（`kj:cache.*` 命名空间）—— 离线只读的数据来源。
 *
 * 依据：
 *   - S1-D §5：本地缓存白名单 7 类 / **TTL 24h**（字典 7d）/ 四层淘汰；
 *   - S1-C §四 网络与离线行为矩阵：离线**命中缓存 → 展示 + 「离线数据 · 更新于 <时间>」**；
 *     未命中 → 空状态 + 离线标记；**绝不自动重放写操作**；
 *   - S1-B 第三批 §2.6：`kj:cache.*` 随「登出 / 注销 / 401 / 改密」四触发清除
 *     （前缀已在 `utils/storage.js` 的 `AUTH_SCOPED_PREFIXES` 中登记，无需在此重复声明）。
 *
 * 安全边界（S1-B 禁缓存 10 项）：
 *   只缓存**界面展示所需的聚合结果**；不缓存密码明文 / Token 明文 / `file_token` /
 *   `file_path` / 他人数据 / 已软删数据。健康数值属用户自有数据，仅落在设备私有存储，
 *   且在四触发时随 `kj:cache.*` 一并清除。
 *
 * 本模块是 `kj:cache.*` 的**唯一出入口**（与 `utils/storage.js` 的「唯一本地读写入口」分工：
 * storage 负责物理读写与命名空间，cache 负责 TTL 与信封结构）。
 */
import { readJson, writeJson, removeRaw } from './storage'
import { formatDate, pad2 } from './validate'

/** 已登记的缓存键（新增业务缓存时必须先在此登记） */
export const CACHE_KEYS = {
    /** S-01 首页概览（SC-06） */
    HOME_OVERVIEW: 'cache.home_overview',
    /** R-08 录入选项字典（SC-08）—— 静态枚举字典，**离线可填写**的依据（S1-D §5：字典 TTL 7d） */
    RECORD_OPTIONS: 'cache.record_options',
    /**
     * R-02 记录列表（SC-10）—— **按 metric_type 切分**为 `cache.record_list.<metric_type>`。
     *
     * 口径（S1-B 第三批 C1，S3-3 落地）：
     *   ① 每指标 **≤ 200 条** 且 **仅近 30 天**（取交集）；② TTL 24h（业务缓存默认值）；
     *   ③ 仅用于**离线只读**展示，**不做自动写回、不做自动重放**；
     *   ④ 命中 `cache.` 前缀 ⇒ 随「登出 / 注销 / 401 / 改密」四触发由
     *      `storage.js` 的前缀扫描自动清除，无需在此重复登记。
     */
    RECORD_LIST: 'cache.record_list',
    /**
     * S-02 / S-03 趋势与统计摘要（SC-11）—— **按「指标 + 窗口」切分**为
     * `cache.trend.<metric_type>.<window>`。
     *
     * 口径（S1-C SC-11 ⑭ / 状态矩阵 §四，S3-4 落地）：
     *   ① **TTL 24h**（业务缓存默认值，不登记到 `TTL_BY_KEY`）；
     *   ② 仅用于**离线只读**：离线时命中 → 只读渲染 + 「离线数据 · 更新于 <时间>」；
     *      未命中 → 该图表区 / 摘要区显示**离线未命中空状态**；
     *   ③ **不自动重放、不做写回**（本页本身无写操作）；
     *   ④ 命中 `cache.` 前缀 ⇒ 随「登出 / 注销 / 401 / 改密」四触发由
     *      `storage.js` 的前缀扫描自动清除，无需在此重复登记；
     *   ⑤ 体量可控：键 = 8 指标 × 3 窗口 = **至多 24 项**，每项 ≤ 90 个数据点（S-02 上限）。
     */
    TREND: 'cache.trend',
    /**
     * G-01 + G-07 目标列表与完成度（SC-12 目标页）—— 单键（**不按类型 / 窗口切分**）。
     *
     * 口径（S1-C SC-12 / 状态矩阵 §四，S3-5 落地）：
     *   ① **TTL 24h**（业务缓存默认值，不登记到 `TTL_BY_KEY`）；
     *   ② 仅用于**离线只读**：离线时命中 → 只读渲染 + 「离线数据 · 更新于 <时间>」；
     *      未命中 → 离线空态（**不得**把"无本地缓存"显示成「还没有设置目标」）；
     *   ③ **不自动重放、不做写回**：暂停 / 恢复 / 更新 / 删除在离线时一律禁用；
     *   ④ 命中 `cache.` 前缀 ⇒ 随「登出 / 注销 / 401 / 改密」四触发由
     *      `storage.js` 的前缀扫描自动清除，无需在此重复登记；
     *   ⑤ 体量可控：服务端保证「每用户每类型至多 1 条在用目标」⇒ 至多 4 条（含达标率），
     *      故**不设**裁剪上限。与 `cache.trend` 按「指标 + 窗口」切分的区别在于：
     *      本键的达标率窗口**固定为 7 天**（`api/goals.js::DEFAULT_RATE_WINDOW`），
     *      不存在"用另一个窗口的数据冒充当前窗口"的风险。
     */
    GOAL: 'cache.goal'
}

/** 记录列表缓存单指标最多保留条数（S1-B 第三批 C1：每指标 ≤ 200 条） */
export const RECORD_LIST_MAX_ITEMS = 200

/** 记录列表缓存只保留最近天数（S1-B 第三批 C1：仅近 30 天） */
export const RECORD_LIST_MAX_DAYS = 30

/**
 * 记录列表缓存键（按指标切分）。
 * @param {string} metricType 8 类指标之一
 * @returns {string} 如 `cache.record_list.weight`
 */
export function recordListKey(metricType) {
    return CACHE_KEYS.RECORD_LIST + '.' + String(metricType || '')
}

/** 趋势缓存单键最多保留的数据点数（S-02 冻结上限：90 天窗口 ≤ 90 点） */
export const TREND_MAX_POINTS = 90

/** 趋势页面支持的时间窗口（与后端 `stats_service.WINDOW_DAYS` 一致） */
export const TREND_WINDOWS = [7, 30, 90]

/**
 * 趋势缓存键（按「指标 + 窗口」切分）。
 *
 * ★ 为什么要带上窗口：同一指标在不同窗口下的图与摘要**数值不同**，
 *   若只按指标缓存，离线时会用 7 天的数据冒充 90 天 —— 属于"展示不实数据"。
 *
 * @param {string} metricType 8 类指标之一
 * @param {number|string} window 7 / 30 / 90（非法值 → 归一为 7，与 api/stats.js 同口径）
 * @returns {string} 如 `cache.trend.weight.30`
 */
export function trendKey(metricType, window) {
    const n = Number(window)
    const days = TREND_WINDOWS.indexOf(n) >= 0 ? n : TREND_WINDOWS[0]
    return CACHE_KEYS.TREND + '.' + String(metricType || '') + '.' + String(days)
}

/**
 * 趋势缓存内容裁剪：只保留**最近的** `TREND_MAX_POINTS` 个数据点。
 * 正常态下服务端已保证 ≤ 90 点；此处在写入前再兜一次，防止异常载荷撑大本地存储。
 * @param {object} payload S-02 的 `data`
 * @returns {object} 裁剪后的副本（不改原对象）
 */
export function trimTrendPayload(payload) {
    if (!payload || !payload.points || payload.points.length <= TREND_MAX_POINTS) {
        return payload
    }
    const copy = {}
    for (const key in payload) {
        if (Object.prototype.hasOwnProperty.call(payload, key)) {
            copy[key] = payload[key]
        }
    }
    copy.points = payload.points.slice(payload.points.length - TREND_MAX_POINTS)
    return copy
}

/** 缓存有效期（S1-D §5 冻结：业务缓存 TTL 24h） */
export const CACHE_TTL_MS = 24 * 60 * 60 * 1000

/** 字典缓存有效期（S1-D §5 冻结：静态字典 TTL 7 天） */
export const CACHE_TTL_DICT_MS = 7 * 24 * 60 * 60 * 1000

/**
 * 按键覆盖 TTL —— **未登记的键一律走 24h 默认值**（不改变既有行为）。
 * 登记口径：只有"服务端常量字典"才可放宽到 7d（S1-D §5 白名单），业务数据一律 24h。
 */
const TTL_BY_KEY = {
    [CACHE_KEYS.RECORD_OPTIONS]: CACHE_TTL_DICT_MS
}

/** Date → `YYYY-MM-DD HH:mm:ss`（本地墙上时间，S1-D D-4 口径） */
export function formatStamp(date) {
    return formatDate(date) + ' ' +
        pad2(date.getHours()) + ':' + pad2(date.getMinutes()) + ':' + pad2(date.getSeconds())
}

/**
 * 写入缓存（自动附带写入时刻，供「离线数据 · 更新于 <时间>」使用）。
 * @returns {boolean} 写入是否成功（失败不抛异常，不打断页面流程）
 */
export function saveCache(key, data) {
    if (!data) {
        return false
    }
    const now = new Date()
    return writeJson(key, {
        ts: now.getTime(),
        saved_at: formatStamp(now),
        data: data
    })
}

/**
 * 读取缓存。
 * @returns {{data: object, savedAt: string}|null} 不存在 / 已过期 / 结构损坏 → null
 *
 * 过期项顺手删除（避免陈旧数据长期占用「四层淘汰」配额）。
 */
export function loadCache(key) {
    const raw = readJson(key, null)
    if (!raw || typeof raw !== 'object' || !raw.data) {
        return null
    }
    const ts = Number(raw.ts)
    const ttl = TTL_BY_KEY[key] || CACHE_TTL_MS
    if (!ts || isNaN(ts) || Date.now() - ts > ttl) {
        removeRaw(key)
        return null
    }
    return {
        data: raw.data,
        savedAt: String(raw.saved_at || '')
    }
}

/** 删除单个缓存项 */
export function dropCache(key) {
    return removeRaw(key)
}
