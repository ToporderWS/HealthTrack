/**
 * 本地提醒**数据层**（S3-6 · SC-14 / SC-15）。
 *
 * 权威依据（逐条对齐，**不在客户端发明口径**）：
 *   - `S1-C §二 SC-14`（列表页：权限条 / A-11 兜底区块 / 全局总开关 / 提醒项列表 / 底部说明）；
 *   - `S1-C §二 SC-15`（编辑页：5 类类型 / 多时间点 / 重复规则 / 类型专属 / 保存 / 删除）；
 *   - `S1-A-P0需求冻结清单` F-049 ~ F-057（喝水 / 运动 / 测量 / 睡眠 / 自定义、单条开关、
 *     全局总开关、编辑与删除、权限引导与状态检测）；
 *   - `S1-C §五 API 矩阵`：**提醒模块 0 个接口**（S1-D 三重复核「提醒表 0 张 / 无提醒接口」）
 *     ⇒ 本层是**纯本地能力**，不发任何请求、不写服务端。
 *
 * 存储命名空间（裁定 ③）：`kj:reminder.*`
 *   ★ 为什么**不能**放 `kj:cache.*`：`utils/cache.js` 的缓存有 **TTL 24h**，而提醒配置是
 *     **用户本地配置**（不是服务端数据的缓存），放进去会在 24 小时后**凭空消失** —— 属功能缺陷。
 *
 * 分层的职责边界（不得越界）：
 *   - 本层：本地配置 CRUD + 兜底确认状态 + 触发时机计算（"哪天到点""是否已确认"）；
 *   - `utils/notify.js`：系统通知**能力**（能否通知 / 注册 / 取消 / 去设置）；
 *   - 页面：只做展示与交互编排，不自行计算到点逻辑、不直接读写存储。
 *
 * 红线（DESIGN.md §12）：本层不产出评价性文案；提醒文案只允许「尽量提醒」，不承诺准时。
 */

import { KEYS, readJson, writeJson } from './storage'
import { metricLabel } from './metrics'

/* ══════════════════ 冻结字典 ══════════════════ */

/** 提醒 5 类（S1-C SC-15 ② 冻结：喝水 / 运动 / 测量 / 睡眠 / 自定义） */
export const REMINDER_TYPES = ['water', 'sport', 'measure', 'sleep', 'custom']

/** 类型 → 中文名（列表主文案） */
export const REMINDER_TYPE_LABEL = {
    water: '喝水提醒',
    sport: '运动提醒',
    measure: '测量提醒',
    sleep: '睡眠提醒',
    custom: '自定义提醒'
}

/** 类型 → 短名（类型选择行 / 副标题用） */
export const REMINDER_TYPE_SHORT = {
    water: '喝水',
    sport: '运动',
    measure: '测量',
    sleep: '睡眠',
    custom: '自定义'
}

/** 重复规则（S1-C SC-15 ④ 冻结：每天 / 工作日 / 自定义） */
export const REPEAT_OPTIONS = [
    { value: 'daily', label: '每天' },
    { value: 'workday', label: '工作日' },
    { value: 'custom', label: '自定义' }
]

/** 周几（ISO 口径：1 = 周一 … 7 = 周日） */
export const WEEKDAYS = [1, 2, 3, 4, 5, 6, 7]

export const WEEKDAY_LABEL = {
    1: '一',
    2: '二',
    3: '三',
    4: '四',
    5: '五',
    6: '六',
    7: '日'
}

/**
 * 单条提醒的时间点上限（裁定 ⑤：**最多 5 个**）。
 * S1-C 未规定上限；无上限会让列表行与编辑页被撑爆，故按裁定取 5。
 */
export const MAX_TIMES = 5

/** 测量类可绑定的指标（正文口径：血压 / 血糖 / 体重；后端可记录的 type 亦仅此 3 个） */
export const MEASURE_METRICS = ['bp', 'glucose', 'weight']

export const MEASURE_METRIC_LABEL = {
    bp: '血压',
    glucose: '血糖',
    weight: '体重'
}

/** 睡眠类「睡前 N 分钟」可选值（S1-C 未枚举 ⇒ 取三个常用档，非推荐值、非医学建议） */
export const SLEEP_BEFORE_OPTIONS = [15, 30, 60]

/** 兜底确认记录的保留天数（超出即剪枝，避免本地键无界增长） */
const CONFIRM_KEEP_DAYS = 7

/** 「近 3 日错过」的窗口（S1-C SC-14 ③ 冻结：近 3 日） */
const MISSED_WINDOW_DAYS = 3

/** 兜底区块最多展示条数（S1-C SC-14 ③ 冻结：最多 5 条） */
export const MAX_FALLBACK_ROWS = 5

/**
 * 提醒排程的**滚动窗口**（S3-9 第 11 步 · H-28 定档：**24 小时**）。
 * ★ 语义 ＝「**尽力而为的排程上限**」，**不是送达保证** —— 超窗口不排程、进程被划掉不补发。
 */
export const REMINDER_WINDOW_MS = 24 * 60 * 60 * 1000

/**
 * 通知栏文案（S3-9 第 11 步 · **H-25 定档：逐字采用，不得润色、不得扩写**）。
 * 自定义类的标题取**用户填写的 title**（见 `notifyTitle`）；测量类的标题为**「测量提醒」**、内容按 `metric` 分支。
 * 红线：不含"准时"承诺、不含医疗评价词。
 */
const NOTIFY_TEXT = {
    water: { title: '喝水提醒', content: '该喝水了' },
    sport: { title: '运动提醒', content: '该运动了' },
    /* H-25 已裁定：测量类**标题固定「测量提醒」**；正文由 `notifyContent` 的 metric 分支产出，
       故此处 content 留空且不会被读取（H-33 裁定 (a) 修正，2026-09-19）。 */
    measure: { title: '测量提醒', content: '' },
    sleep: { title: '睡眠提醒', content: '该准备休息了' },
    custom: { title: '', content: '记得处理这条提醒' }
}

/* ══════════════════ 日期 / 时间工具（纯本地，不引第三方日期库） ══════════════════ */

function pad2(n) {
    return n < 10 ? '0' + n : String(n)
}

/** `Date` → `YYYY-MM-DD`（**本地墙上时间**，与全工程时间口径一致，不做时区换算） */
export function dayString(date) {
    const d = date || new Date()
    return d.getFullYear() + '-' + pad2(d.getMonth() + 1) + '-' + pad2(d.getDate())
}

/** `Date` → `HH:mm` */
export function timeString(date) {
    const d = date || new Date()
    return pad2(d.getHours()) + ':' + pad2(d.getMinutes())
}

/** `YYYY-MM-DD` → `Date`（**手动解析**：`new Date('YYYY-MM-DD')` 会按 UTC 解释，导致差一天） */
export function parseDay(dayStr) {
    const parts = String(dayStr || '').split('-')
    if (parts.length !== 3) {
        return new Date()
    }
    const y = Number(parts[0])
    const m = Number(parts[1])
    const d = Number(parts[2])
    if (isNaN(y) || isNaN(m) || isNaN(d)) {
        return new Date()
    }
    return new Date(y, m - 1, d)
}

/** 星期（ISO：1 = 周一 … 7 = 周日） */
export function weekdayOf(dayStr) {
    const wd = parseDay(dayStr).getDay()
    return wd === 0 ? 7 : wd
}

/** 日期偏移（正数向后、负数向前） */
export function shiftDay(dayStr, delta) {
    const d = parseDay(dayStr)
    d.setDate(d.getDate() + delta)
    return dayString(d)
}

/** 最近 N 天的日期串（**升序**，含今天） */
export function recentDays(n, now) {
    const today = dayString(now || new Date())
    const out = []
    for (let i = n - 1; i >= 0; i--) {
        out.push(shiftDay(today, -i))
    }
    return out
}

/** `HH:mm` 合法性（编辑页与存储校验共用同一判据） */
export function isValidTime(text) {
    return /^([01]\d|2[0-3]):[0-5]\d$/.test(String(text || ''))
}

/* ══════════════════ 配置读写 ══════════════════ */

/** 归一化存储读到的时间点：只留合法值、去重、升序、截断到上限（**不补默认值**） */
function normalizeTimes(times) {
    const seen = {}
    const out = []
    const list = Array.isArray(times) ? times : []
    for (let i = 0; i < list.length; i++) {
        const t = String(list[i] || '')
        if (!isValidTime(t) || seen[t]) {
            continue
        }
        seen[t] = true
        out.push(t)
    }
    out.sort()
    return out.slice(0, MAX_TIMES)
}

/** 归一化周几：只留 1~7、去重、升序 */
function normalizeWeekdays(days) {
    const seen = {}
    const out = []
    const list = Array.isArray(days) ? days : []
    for (let i = 0; i < list.length; i++) {
        const d = Number(list[i])
        if (WEEKDAYS.indexOf(d) < 0 || seen[d]) {
            continue
        }
        seen[d] = true
        out.push(d)
    }
    out.sort(function (a, b) { return a - b })
    return out
}

/** 存储中的一条是否可用（类型非法 / 无时间点 ⇒ 丢弃，**不猜测用户意图**） */
function isValidStored(item) {
    if (!item || REMINDER_TYPES.indexOf(item.type) < 0) {
        return false
    }
    return normalizeTimes(item.times).length > 0
}

/** 归一化一条提醒（读盘与保存共用，保证口径唯一） */
function normalizeItem(item) {
    const type = item.type
    const out = {
        id: String(item.id || ''),
        type: type,
        times: normalizeTimes(item.times),
        repeat: REPEAT_OPTIONS.some(function (o) { return o.value === item.repeat }) ? item.repeat : 'daily',
        weekdays: normalizeWeekdays(item.weekdays),
        enabled: item.enabled !== false,
        createdAt: item.createdAt || ''
    }
    if (type === 'measure') {
        out.metric = MEASURE_METRICS.indexOf(item.metric) >= 0 ? item.metric : ''
    }
    if (type === 'sleep') {
        out.sleepBeforeMin = SLEEP_BEFORE_OPTIONS.indexOf(Number(item.sleepBeforeMin)) >= 0
            ? Number(item.sleepBeforeMin)
            : 30
    }
    if (type === 'custom') {
        out.title = String(item.title || '')
    }
    return out
}

/** 读全部配置；无配置 / 读失败 → `{ enabled: true, items: [] }`（默认总开关为开） */
export function loadConfig() {
    const raw = readJson(KEYS.REMINDER_CONFIG, null)
    if (!raw || typeof raw !== 'object') {
        return { enabled: true, items: [] }
    }
    const items = []
    const list = Array.isArray(raw.items) ? raw.items : []
    for (let i = 0; i < list.length; i++) {
        if (isValidStored(list[i])) {
            items.push(normalizeItem(list[i]))
        }
    }
    return { enabled: raw.enabled !== false, items: items }
}

/** 写全部配置 */
export function saveConfig(config) {
    const cfg = config || {}
    return writeJson(KEYS.REMINDER_CONFIG, {
        enabled: cfg.enabled !== false,
        items: Array.isArray(cfg.items) ? cfg.items : []
    })
}

/** 提醒项列表（列表页渲染用） */
export function listItems() {
    return loadConfig().items
}

/** 全局总开关当前值 */
export function isGlobalEnabled() {
    return loadConfig().enabled
}

export function getItem(id) {
    const items = listItems()
    for (let i = 0; i < items.length; i++) {
        if (items[i].id === id) {
            return items[i]
        }
    }
    return null
}

/** 生成稳定的本地 id（无需服务端；时间戳 + 自增后缀，避免同毫秒碰撞） */
let idSeq = 0
export function newId() {
    idSeq += 1
    return 'r' + Date.now().toString(36) + '-' + idSeq
}

/**
 * 新增或更新一条提醒。
 * @param {object} draft 表单草稿（含 type / times / repeat / weekdays / 专属字段）
 * @param {string} id 为空 → 新增；否则更新该条（保留 `createdAt`）
 * @returns {{ok:boolean, id:string, errors:object}}
 */
export function upsertItem(draft, id) {
    const check = validateItem(draft)
    if (!check.ok) {
        return { ok: false, id: '', errors: check.errors }
    }
    const cfg = loadConfig()
    const item = normalizeItem(draft)
    item.id = id ? String(id) : newId()
    if (!item.createdAt) {
        item.createdAt = dayString(new Date()) + ' ' + timeString(new Date())
    }

    let replaced = false
    for (let i = 0; i < cfg.items.length; i++) {
        if (cfg.items[i].id === item.id) {
            item.createdAt = cfg.items[i].createdAt || item.createdAt
            item.enabled = cfg.items[i].enabled !== false
            cfg.items[i] = item
            replaced = true
            break
        }
    }
    if (!replaced) {
        cfg.items.push(item)
    }
    if (!saveConfig(cfg)) {
        return { ok: false, id: '', errors: { save: '保存失败，请重试' } }
    }
    return { ok: true, id: item.id, errors: {} }
}

/** 删除一条提醒；同时清掉它的兜底确认记录（避免残留"已处理"痕迹） */
export function removeItem(id) {
    const cfg = loadConfig()
    const kept = []
    for (let i = 0; i < cfg.items.length; i++) {
        if (cfg.items[i].id !== id) {
            kept.push(cfg.items[i])
        }
    }
    const ok = saveConfig({ enabled: cfg.enabled, items: kept })
    clearHandledOf(id)
    return ok
}

/** 全局总开关（**关闭 = 取消已注册通知**，由页面调用 notify 层执行，见 SC-14） */
export function setGlobalEnabled(enabled) {
    const cfg = loadConfig()
    cfg.enabled = enabled !== false
    return saveConfig(cfg)
}

/** 单条开关 */
export function setItemEnabled(id, enabled) {
    const cfg = loadConfig()
    for (let i = 0; i < cfg.items.length; i++) {
        if (cfg.items[i].id === id) {
            cfg.items[i].enabled = enabled !== false
            return saveConfig(cfg)
        }
    }
    return false
}

/** 已开启条数（全局关闭时恒为 0 —— 列表页的「未生效」判定依赖同一口径） */
export function enabledCount() {
    const cfg = loadConfig()
    if (!cfg.enabled) {
        return 0
    }
    let n = 0
    for (let i = 0; i < cfg.items.length; i++) {
        if (cfg.items[i].enabled !== false) {
            n += 1
        }
    }
    return n
}

/* ══════════════════ 表单校验（SC-15 ⑫ 错误态） ══════════════════ */

/**
 * 校验表单草稿（错误文案口径来自 S1-C SC-15 ⑫，**不自行发明**）：
 *   ① 未设置时间 → 「请至少添加一个时间点」；
 *   ② 自定义类型标题为空 → 「请输入提醒标题」；
 *   ③ 自定义重复规则但未选周几 → 「请选择重复的星期」；
 *   ④ 测量类未绑定指标 → 「请选择要测量的指标」。
 * @returns {{ok:boolean, errors:object}}
 */
export function validateItem(draft) {
    const errors = {}
    const d = draft || {}
    if (normalizeTimes(d.times).length === 0) {
        errors.times = '请至少添加一个时间点'
    }
    if (d.type === 'custom' && !String(d.title || '').trim()) {
        errors.title = '请输入提醒标题'
    }
    if (d.repeat === 'custom' && normalizeWeekdays(d.weekdays).length === 0) {
        errors.weekdays = '请选择重复的星期'
    }
    if (d.type === 'measure' && MEASURE_METRICS.indexOf(d.metric) < 0) {
        errors.metric = '请选择要测量的指标'
    }
    return { ok: Object.keys(errors).length === 0, errors: errors }
}

/* ══════════════════ 触发时机计算（A-11 兜底区块） ══════════════════ */

/** 该提醒在指定日期是否到点（按 repeat 规则；周日口径 ISO） */
export function occursOn(item, dayStr) {
    if (!item) {
        return false
    }
    if (item.repeat === 'workday') {
        const wd = weekdayOf(dayStr)
        return wd >= 1 && wd <= 5
    }
    if (item.repeat === 'custom') {
        return item.weekdays.indexOf(weekdayOf(dayStr)) >= 0
    }
    return true
}

/* ══════════════════ 事前排程：未来触发点（S3-9 第 11 步 · H-21 路线 A） ══════════════════ */

/** 通知栏标题（H-25 定档）：自定义类用**用户填写的标题**（复用 `itemDisplayName`，与列表同源） */
function notifyTitle(item) {
    if (item.type === 'custom') {
        return itemDisplayName(item)
    }
    return NOTIFY_TEXT[item.type] ? NOTIFY_TEXT[item.type].title : ''
}

/**
 * 通知栏内容（H-25 定档，逐字）：测量类按 `metric` 分支。
 * ★ 指标缺失（存储层归一化后理论上不会发生）⇒ 回落到**同句式的中性句**，不伪造具体指标、
 *   也不产出任何评价词。
 */
function notifyContent(item) {
    if (item.type === 'measure') {
        const label = MEASURE_METRIC_LABEL[item.metric] || ''
        return label ? '该测' + label + '了' : '该测量了'
    }
    return NOTIFY_TEXT[item.type] ? NOTIFY_TEXT[item.type].content : ''
}

/** `YYYY-MM-DD` + `HH:mm` → 毫秒时间戳（**本地墙上时间**，与全工程口径一致） */
function fireAtOf(day, time) {
    const parts = String(time || '').split(':')
    if (parts.length !== 2) {
        return -1
    }
    const d = parseDay(day)
    d.setHours(Number(parts[0]) || 0, Number(parts[1]) || 0, 0, 0)
    return d.getTime()
}

/** 自今天起向后找该时间点的**下一次**触发时刻；窗口内找不到 ⇒ -1 */
function nextFireAt(item, time, today, maxOffset, now, limit) {
    for (let k = 0; k <= maxOffset; k++) {
        const day = shiftDay(today, k)
        if (!occursOn(item, day)) {
            continue
        }
        const at = fireAtOf(day, time)
        if (at > now && at <= limit) {
            return at
        }
    }
    return -1
}

/**
 * 未来触发点（**纯时间计算**，S3-9 第 11 步 · H-21 路线 A 的排程输入）。
 *
 * ★ 与 `pendingToday` / `missedRecent` 的分工（**不得混淆**）：
 *   - `pendingToday` / `missedRecent` ＝ **事后计算**（打开页面时回看"已到点未确认"）⇒ A-11 兜底区块；
 *   - 本函数 ＝ **事前排程**（把"尚未到点"的触发点交给系统通知通道）。
 *
 * 口径：
 *   - 起点 ＝ 当前时刻；窗口 ＝ `windowMs`（缺省 `REMINDER_WINDOW_MS` ＝ 24h）；
 *   - 只遍历「全局开 ＋ 单条开」的提醒；**每个时间点只排"下一次"**（无限重复由滚动窗口续期实现）；
 *   - 重复规则**复用既有 `occursOn`**（不发明第二套判据，避免口径分叉）；
 *   - ✦ `sleepBeforeMin` 是**描述性字段**（仅用于列表副标题「睡前 30 分钟」），
 *     **不参与触发时刻计算** ⇒ 睡眠类触发时刻 ＝ `item.times`，与其余四类**完全一致**。
 *
 * 红线：本层只做**纯时间计算**，**不调用任何系统通知 API** —— 由 `utils/notify.js#syncAll()`
 *   负责系统侧动作（分层边界：数据层 ↔ 能力层）。
 *
 * @param {number} [windowMs] 排程窗口（毫秒）
 * @returns {Array<{key,reminderId,type,title,content,payload,fireAt}>} 按 `fireAt` 升序
 */
export function upcomingTriggers(windowMs) {
    const cfg = loadConfig()
    if (!cfg.enabled) {
        return []
    }
    const now = Date.now()
    const span = Number(windowMs) > 0 ? Number(windowMs) : REMINDER_WINDOW_MS
    const limit = now + span
    const today = dayString(new Date(now))
    const maxOffset = Math.ceil(span / 86400000) + 1
    const out = []
    for (let i = 0; i < cfg.items.length; i++) {
        const item = cfg.items[i]
        if (item.enabled === false) {
            continue
        }
        for (let j = 0; j < item.times.length; j++) {
            const time = item.times[j]
            const at = nextFireAt(item, time, today, maxOffset, now, limit)
            if (at <= 0) {
                continue
            }
            const day = dayString(new Date(at))
            out.push({
                key: item.id + '|' + day + '|' + time,
                reminderId: item.id,
                type: item.type,
                title: notifyTitle(item),
                content: notifyContent(item),
                payload: 'kj|' + item.type + '|' + item.id + '|' + day + '|' + time,
                fireAt: at
            })
        }
    }
    out.sort(function (a, b) {
        return a.fireAt - b.fireAt
    })
    return out
}

/**
 * 该提醒是否参与 A-11 兜底区块（**口径推断项，已登记待裁定**）。
 *
 * 判据 = 是否有"可判定的完成动作"。S1-C SC-14 ③ / 口径红线 ④ 给出的动作枚举是
 *   「去记录」（可记录类 = 喝水 / 运动 / 测量-血压·血糖·体重）与「标记已处理」（自定义），
 *   **睡眠类不在任一枚举内**（"睡前 N 分钟"是行为提示，没有完成/未完成语义）。
 * 若把睡眠类也计入兜底，会出现**无法消除**的行（既不能去记录、也不能标记已处理），
 *   故本层按"仅参与有完成动作的类型"实现，并把该判断**显式登记为待裁定项**。
 */
export function isFallbackType(item) {
    if (!item) {
        return false
    }
    return item.type === 'water' || item.type === 'sport' || item.type === 'measure' || item.type === 'custom'
}

/** 「去记录」映射：提醒 → SC-08 的 `?type=`（冻结枚举，映射不到 → 空串） */
export function recordTypeOf(item) {
    if (!item) {
        return ''
    }
    if (item.type === 'water') {
        return 'water'
    }
    if (item.type === 'sport') {
        return 'sport'
    }
    if (item.type === 'measure' && MEASURE_METRICS.indexOf(item.metric) >= 0) {
        return item.metric
    }
    return ''
}

/* ══════════════════ 兜底确认状态 ══════════════════ */

function confirmKey(reminderId, time) {
    return String(reminderId) + '|' + String(time)
}

/** 读全部确认记录（结构：`{ 'YYYY-MM-DD': { 'id|HH:mm': 时间戳 } }`） */
function loadConfirm() {
    const raw = readJson(KEYS.REMINDER_CONFIRM, null)
    return raw && typeof raw === 'object' ? raw : {}
}

function saveConfirm(map) {
    return writeJson(KEYS.REMINDER_CONFIRM, map || {})
}

/** 剪枝：只保留最近 `CONFIRM_KEEP_DAYS` 天（更早的确认记录已无展示价值） */
export function pruneConfirm(now) {
    const keep = recentDays(CONFIRM_KEEP_DAYS, now)
    const map = loadConfirm()
    let changed = false
    Object.keys(map).forEach(function (day) {
        if (keep.indexOf(day) < 0) {
            delete map[day]
            changed = true
        }
    })
    if (changed) {
        saveConfirm(map)
    }
    return changed
}

/** 该提醒在指定日期的指定时间点是否已确认（去记录 / 标记已处理） */
export function isHandled(reminderId, time, dayStr) {
    const day = loadConfirm()[dayStr]
    return !!(day && day[confirmKey(reminderId, time)])
}

/**
 * 标记已处理（「去记录」成功返回 与 「标记已处理」共用同一记录）；
 * 顺带剪枝，避免历史记录无界增长。
 */
export function markHandled(reminderId, time, dayStr, now) {
    const map = loadConfirm()
    const day = dayStr || dayString(now || new Date())
    if (!map[day]) {
        map[day] = {}
    }
    map[day][confirmKey(reminderId, time)] = Date.now()
    const ok = saveConfirm(map)
    pruneConfirm(now)
    return ok
}

/** 清掉某条提醒的全部确认记录（删除提醒时调用） */
export function clearHandledOf(reminderId) {
    const map = loadConfirm()
    let changed = false
    Object.keys(map).forEach(function (day) {
        const bucket = map[day] || {}
        Object.keys(bucket).forEach(function (k) {
            if (k.indexOf(String(reminderId) + '|') === 0) {
                delete bucket[k]
                changed = true
            }
        })
    })
    if (changed) {
        saveConfirm(map)
    }
    return changed
}

/**
 * 组装一行兜底数据（供 SC-14 渲染；字段含义固定，页面不再二次推导）。
 * @returns {{key:string, reminderId:string, time:string, name:string, type:string, recordType:string}}
 */
function buildRow(item, day, time) {
    return {
        key: day + '|' + confirmKey(item.id, time),
        reminderId: item.id,
        time: time,
        name: itemDisplayName(item),
        type: item.type,
        recordType: recordTypeOf(item)
    }
}

/**
 * 当日「未确认」提醒（S1-C SC-14 ③ 上半分支）。
 * 口径：全局开 + 单条开 + 参与兜底的类型 + 当日到点 + **时间已过** + 未确认；
 *       按时间升序，**最多 5 条**。
 * @param {Date} now 便于自检注入固定时刻
 */
export function pendingToday(now) {
    const cfg = loadConfig()
    if (!cfg.enabled) {
        return []
    }
    const d = now || new Date()
    const day = dayString(d)
    const nowHM = timeString(d)
    const rows = []
    for (let i = 0; i < cfg.items.length; i++) {
        const item = cfg.items[i]
        if (item.enabled === false || !isFallbackType(item) || !occursOn(item, day)) {
            continue
        }
        for (let j = 0; j < item.times.length; j++) {
            const t = item.times[j]
            if (t > nowHM || isHandled(item.id, t, day)) {
                continue
            }
            rows.push(buildRow(item, day, t))
        }
    }
    rows.sort(function (a, b) { return a.time < b.time ? -1 : (a.time > b.time ? 1 : 0) })
    return rows.slice(0, MAX_FALLBACK_ROWS)
}

/**
 * 近 3 日「错过」提醒（S1-C SC-14 ③ 下半分支；**仅当当日为 0 时展示**，由页面判定）。
 * 窗口 = 昨天起向前 3 天（不含今天，避免与上半分支重复计数）。
 * @param {Date} now
 */
export function missedRecent(now) {
    const cfg = loadConfig()
    if (!cfg.enabled) {
        return []
    }
    const today = dayString(now || new Date())
    const days = []
    for (let i = 1; i <= MISSED_WINDOW_DAYS; i++) {
        days.push(shiftDay(today, -i))
    }
    const rows = []
    for (let k = 0; k < days.length; k++) {
        const day = days[k]
        for (let i = 0; i < cfg.items.length; i++) {
            const item = cfg.items[i]
            if (item.enabled === false || !isFallbackType(item) || !occursOn(item, day)) {
                continue
            }
            for (let j = 0; j < item.times.length; j++) {
                const t = item.times[j]
                if (isHandled(item.id, t, day)) {
                    continue
                }
                rows.push(buildRow(item, day, t))
            }
        }
    }
    rows.sort(function (a, b) { return a.key < b.key ? -1 : (a.key > b.key ? 1 : 0) })
    return rows.slice(0, MAX_FALLBACK_ROWS)
}

/* ══════════════════ 展示辅助（列表副标题 / 行名） ══════════════════ */

/** 提醒行主文案：自定义类用用户自填标题（空 → 中性兜底名） */
export function itemDisplayName(item) {
    if (!item) {
        return ''
    }
    if (item.type === 'custom') {
        const t = String(item.title || '').trim()
        return t || REMINDER_TYPE_LABEL.custom
    }
    return REMINDER_TYPE_LABEL[item.type] || REMINDER_TYPE_SHORT[item.type] || ''
}

/** 多个时间点 → `08:00、10:00`（无时间点 → 空串） */
export function timesText(item) {
    if (!item || !item.times || !item.times.length) {
        return ''
    }
    return item.times.join('、')
}

/** 重复规则 → 中文（自定义 → 「周一、周三」） */
export function repeatText(item) {
    if (!item) {
        return ''
    }
    if (item.repeat === 'workday') {
        return '工作日'
    }
    if (item.repeat === 'custom') {
        if (!item.weekdays || !item.weekdays.length) {
            return '自定义'
        }
        const names = []
        for (let i = 0; i < item.weekdays.length; i++) {
            names.push('周' + (WEEKDAY_LABEL[item.weekdays[i]] || ''))
        }
        return names.join('、')
    }
    return '每天'
}

/** 类型专属说明（无专属参数 → 空串，**不留空标签**） */
export function detailText(item) {
    if (!item) {
        return ''
    }
    if (item.type === 'measure') {
        return item.metric ? '指标：' + (MEASURE_METRIC_LABEL[item.metric] || metricLabel(item.metric)) : ''
    }
    if (item.type === 'sleep') {
        return '睡前 ' + item.sleepBeforeMin + ' 分钟'
    }
    return ''
}

/** 列表行副标题：`08:00、10:00 · 每天 · 指标：血压` */
export function subtitleText(item) {
    const parts = []
    const t = timesText(item)
    if (t) {
        parts.push(t)
    }
    const r = repeatText(item)
    if (r) {
        parts.push(r)
    }
    const d = detailText(item)
    if (d) {
        parts.push(d)
    }
    return parts.join(' · ')
}

/** 类型图标（复用既有 8 类几何语言；自定义类**无对应图形** → 空串，不发明图标） */
export function iconOf(item) {
    if (!item) {
        return ''
    }
    if (item.type === 'water') {
        return 'water'
    }
    if (item.type === 'sport') {
        return 'sport'
    }
    if (item.type === 'sleep') {
        return 'sleep'
    }
    if (item.type === 'measure') {
        return MEASURE_METRICS.indexOf(item.metric) >= 0 ? item.metric : ''
    }
    return ''
}
