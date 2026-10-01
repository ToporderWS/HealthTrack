/**
 * 本地通知**能力抽象层**（S3-6 建立 · S3-9 第 11 步接通 App 端真实通道）。
 *
 * 为什么单独成层（设计原因，**不是随手拆文件**）：
 *   1. 「本地提醒」由两件不同性质的事组成 —— ① 用户本地的提醒配置（数据）；② 系统通知的
 *      注册 / 取消 / 权限状态（**设备能力**）。后者在 H5 / 小程序 / App 上**可用性完全不同**，
 *      把能力判定散落在页面里，必然出现"UI 说生效、实际不会提醒"的**虚假承诺**；
 *   2. 本工程开发与验收环境是 **H5**，而系统本地通知 API 只存在于 App 端运行期 ⇒ 必须有
 *      一处**显式**回答"当前环境到底能不能通知"，并让页面据此**诚实降级**。
 *
 * S3-9 第 11 步的变更依据（**全部为真机实测，不是推断**）：
 *   - **第 0 步**：Android 真机标准基座实测 `uni.createPushMessage` **可用，且通知栏真实出现**
 *     ⇒ 本层不再是占位 stub，`getCapability` 的 App 分支改读**真实授权状态**；
 *   - **A3**：`uni.getAppAuthorizeSetting().notificationAuthorized` 随系统开关**双向跟随**
 *     （关 = `denied` / 开 = `authorized`）⇒ 可作权限判据；
 *   - **A4**：`uni.openAppAuthorizeSetting()` 可进入系统授权管理页，通知开关**非灰色禁用**
 *     ⇒ 作「去设置」首选；`plus.runtime.openSettings()` 作降级；
 *   - **A2（撤销）**：`plus.push.remove()` 的**精确撤销被证伪** —— 已实际调用、靶仍照常弹出
 *     ⇒ **禁止依赖精确撤销**，走**档 1**（见下）；
 *   - **A1（进程）**：App 被划掉后到点**不弹** ⇒ 延迟通知的有效生命周期 ＝ **App 运行时存活期**。
 *
 * 排程策略（**档 1 · 对账式全量重建**，见 `syncAll`）：
 *   配置变更（保存 / 启停 / 删除 / 全局开关 / 清缓存）→ 清空 → 按 24h 滚动窗口**重排全量**。
 *   **不做逐条 diff**、**不做精确撤销承诺**；「撤销」的语义 ＝ **台账剔除 ＋ 下次重建时不投**。
 *
 * 裁定口径（S3-6 第 2 步 裁定 ①②④，继续有效）：
 *   - **A 方案**：本能力抽象层存在；App 端走**纯本地**通知通道；
 *   - **H5 不支持真实通知时显示「未生效」并降级**：`canNotify === false` ⇒ 页面显示
 *     「未生效」+ 顶部引导条，**绝不伪造"已注册"**；
 *   - **不接第三方推送**：不引入任何推送 SDK / 云通道（S1-D §5.4 与隐私草案 A13 冻结）；
 *   - **不做后台保活**：因此**不使用**浏览器原生 `Notification` 兜底 —— 浏览器通知依赖
 *     页面存活、无 Service Worker，页面一关就失效，用它只会给出**看似能提醒、实际不能**的假象。
 *
 * 依赖约定（**刻意为零依赖**）：
 *   本文件**不 import 任何模块**（尤其不 import `utils/storage.js`）—— 因为
 *   `utils/storage.js` 的 I-01（清缓存时取消已注册通知）需要调用本文件，若此处反向依赖
 *   storage 即构成**循环依赖**。本层因此只维护**内存注册台账**；进程重启后台账自然清空，
 *   系统侧残留由 `plus.push.clear()` 兜底（I-01 与每次 `syncAll` 都会走它）。
 *   ★ 台账**不落盘**：本批**不新增任何存储键**（授权边界）。
 *   ★ 通知 `title` / `content` 由调用方（`utils/reminder.js`）生成后传入 —— 本层不产出上屏文案。
 *
 * 能力边界（**如实登记，不得对外宣称超出**）：
 *   ① App 进程被划掉后，已排入的延迟通知到点**不弹**（A1 实测）；
 *   ② 超出 24h 窗口的触发点**不排程**；
 *   ③ 进程重启后需**再次进入 App** 才能恢复后续排程（`App.vue#onShow`）；
 *   ④ 不接第三方推送 ⇒ **无服务端补发**。
 *   四条均落在 S1-C 冻结文案「提醒可能延迟或不触发，本应用会尽量提醒」的覆盖范围内
 *   ⇒ **本批零文案改动**。
 *
 * 红线（DESIGN.md §12）：本层不产出任何上屏文案，不得出现"准时"承诺，也不得出现医疗评价词。
 */

/** 能力状态（**唯一对外口径**，页面据此判断「未生效」） */
export const CAPABILITY = {
    /** 当前平台不存在本地通知 API（H5 / 小程序）—— 本工程验收环境即此态 */
    UNSUPPORTED: 'unsupported',
    /** App 端授权状态**未定**（如 `notDetermined`、或授权状态读取失败）⇒ 如实按不可用 */
    PENDING: 'pending',
    /** 已获通知权限，可注册 */
    GRANTED: 'granted',
    /** 用户拒绝通知权限 */
    DENIED: 'denied'
}

/** 注册失败 / 取消失败的原因码（页面只做日志与降级，不直接上屏） */
export const REASON = {
    UNSUPPORTED: 'unsupported',
    PENDING: 'pending',
    DENIED: 'denied',
    EMPTY: 'empty',
    ERROR: 'error'
}

/**
 * 单次同步的**条数护栏**（S3-9 第 11 步 · H-28 定档 24h 窗口下约 10~15 条，40 留足余量）。
 * 目的：防未知上限 —— 条数失控是"不可控的运行时未知"，而不是可以"等出问题再说"的事。
 */
export const MAX_SYNC_ITEMS = 40

/**
 * 已注册的本地通知（**内存注册台账**）。
 * 结构：`{ [triggerKey]: { key, reminderId, type, title, content, payload, fireAt, ok, err } }`
 * ★ 框架**不返回消息 id** ⇒ 台账键由本层按 `trigger.key` 自编。
 */
let registry = {}

/** 最近一次同步的时刻（**仅内存**，不新增存储键）—— 供回前台重排程的节流判定 */
let lastSyncAt = 0

/** 当前运行平台标识（取不到 → 空串，**不猜测**） */
function platform() {
    try {
        const info = uni.getSystemInfoSync()
        return (info && info.uniPlatform) || ''
    } catch (e) {
        return ''
    }
}

/** 是否 App 端运行期（系统本地通知 API 的唯一宿主平台） */
export function isAppRuntime() {
    return platform() === 'app'
}

/**
 * 系统通知授权状态（**同步**读取，A3 真机实测口径）。
 * @returns {string} `authorized` / `denied` / 其它（未定）；读取失败 → 空串
 */
function notificationAuthorized() {
    try {
        if (typeof uni.getAppAuthorizeSetting !== 'function') {
            return ''
        }
        const setting = uni.getAppAuthorizeSetting() || {}
        return setting.notificationAuthorized ? String(setting.notificationAuthorized) : ''
    } catch (e) {
        return ''
    }
}

/**
 * 当前环境的通知能力。
 *
 * 判定顺序（**先平台、后权限** —— 平台不具备 API 时谈权限没有意义）：
 *   ① 非 App 端 ⇒ `UNSUPPORTED`（H5 验收环境即此态，页面显示「未生效」）；
 *   ② App 端 `notificationAuthorized === 'authorized'` ⇒ `GRANTED`（可注册）；
 *   ③ App 端 `'denied'` ⇒ `DENIED`；
 *   ④ 其余取值（`notDetermined`、读取失败）⇒ `PENDING`，**如实按不可用**，不乐观放行。
 *
 * ★ 第 ④ 支的取舍：不把"读不到"当成"可以用" —— 否则页面会显示"已生效"却弹不出通知，
 *   正是本层存在的理由（宁可显示「未生效」也不能虚假承诺）。
 *
 * @returns {{status:string, canNotify:boolean, platform:string}}
 */
export function getCapability() {
    if (!isAppRuntime()) {
        return { status: CAPABILITY.UNSUPPORTED, canNotify: false, platform: platform() }
    }
    const auth = notificationAuthorized()
    if (auth === 'authorized') {
        return { status: CAPABILITY.GRANTED, canNotify: true, platform: platform() }
    }
    if (auth === 'denied') {
        return { status: CAPABILITY.DENIED, canNotify: false, platform: platform() }
    }
    return { status: CAPABILITY.PENDING, canNotify: false, platform: platform() }
}

/** 是否具备真实通知能力（页面的「未生效」唯一判据） */
export function canNotify() {
    return getCapability().canNotify === true
}

/* ══════════════════ 内部工具 ══════════════════ */

/** 诊断日志（**仅控制台**，不产出上屏文案；日志失败不得影响通知主流程） */
function note(text) {
    try {
        if (typeof console !== 'undefined' && console && typeof console.warn === 'function') {
            console.warn('[康迹·通知] ' + String(text))
        }
    } catch (e) {
        // 刻意空实现：日志属诊断，不得打断主流程
    }
}

/** 错误对象 → 短文本（回调形态不确定，逐层兜底；**不抛异常**） */
function brief(obj) {
    if (!obj) {
        return ''
    }
    try {
        if (typeof obj === 'string') {
            return obj
        }
        if (obj.errMsg) {
            return String(obj.errMsg)
        }
        if (obj.message) {
            return String(obj.message)
        }
        return JSON.stringify(obj)
    } catch (e) {
        return 'unknown'
    }
}

/**
 * 距触发时刻的秒数（`delay` 的官方单位 ＝ **秒**）。
 * @returns {number} > 0 可排程；已过点 / 取值非法 ⇒ -1（**不排程**）
 */
function delaySecondsOf(trigger) {
    const at = Number(trigger && trigger.fireAt)
    if (!isFinite(at) || at <= 0) {
        return -1
    }
    const sec = Math.round((at - Date.now()) / 1000)
    return sec > 0 ? sec : -1
}

/** 台账键（`trigger.key` 缺省时以 `类型@触发时刻` 兜底，保证仍可去重） */
function keyOf(trigger) {
    const t = trigger || {}
    const k = String(t.key || '')
    if (k) {
        return k
    }
    return String(t.type || '') + '@' + String(t.fireAt || '')
}

/**
 * 归一化待排程清单：剔除**已过点 / 非法**项 → **去重** → 按 `fireAt` **升序** → **截断护栏**。
 * （档 1 的三条硬约束之一：条数护栏在"发出前"收口，而不是事后补救。）
 */
function prepareTriggers(triggers) {
    const list = Array.isArray(triggers) ? triggers : []
    const seen = {}
    const out = []
    for (let i = 0; i < list.length; i++) {
        const t = list[i]
        if (!t || delaySecondsOf(t) < 0) {
            continue
        }
        const k = keyOf(t)
        if (seen[k]) {
            continue
        }
        seen[k] = true
        out.push(t)
    }
    out.sort(function (a, b) {
        return Number(a.fireAt) - Number(b.fireAt)
    })
    return out.slice(0, MAX_SYNC_ITEMS)
}

/* ══════════════════ 注册 / 取消 ══════════════════ */

/**
 * 注册**一条**提醒的系统本地通知。
 *
 * ★ 返回值语义（**勿误读**）：`ok === true` 表示"**调用已发起且未同步抛异常**"，
 *   **不等于"已送达"** —— 框架的成功/失败回调是**异步**的，其结果只回写**内存台账**
 *   （`registry[key].ok / .err`），供诊断与验收取证使用。
 *   这样设计是为了让 `syncAll()` 保持**同步编排**（页面无需 await 即可完成一次全量重建）。
 *
 * @param {{key:string, reminderId:string, type:string, title:string, content:string,
 *          payload:string, fireAt:number}} trigger 由 `utils/reminder.js#upcomingTriggers()` 产出
 * @returns {{ok:boolean, reason:string}}
 */
export function registerLocal(trigger) {
    if (!canNotify()) {
        return { ok: false, reason: getCapability().status }
    }
    const t = trigger || {}
    const delay = delaySecondsOf(t)
    if (delay < 0) {
        return { ok: false, reason: REASON.EMPTY }
    }
    const entry = {
        key: keyOf(t),
        reminderId: String(t.reminderId || ''),
        type: String(t.type || ''),
        title: String(t.title || ''),
        content: String(t.content || ''),
        payload: String(t.payload || ''),
        fireAt: Number(t.fireAt) || 0,
        ok: false,
        err: ''
    }
    try {
        // 参数集**逐字对齐第 0 步实测通过的调用形状**（只传已证可用的四个业务参数）。
        uni.createPushMessage({
            title: entry.title,
            content: entry.content,
            payload: entry.payload,
            delay: delay,
            success: function () {
                entry.ok = true
            },
            fail: function (err) {
                entry.err = brief(err)
                note('createPushMessage 失败：' + entry.err)
            },
            complete: function () {}
        })
    } catch (e) {
        entry.err = brief(e)
        note('createPushMessage 同步异常：' + entry.err)
    }
    // 成功 / 失败**均回写台账**（未触发项的诊断信息只能靠这里留存）
    registry[entry.key] = entry
    return { ok: entry.err === '', reason: entry.err === '' ? '' : REASON.ERROR }
}

/**
 * 取消一条提醒已注册的本地通知 —— **档 1 语义**。
 *
 * ★ **不调用 `remove`**：A2 真机实测已证伪其精确撤销能力（调用后靶仍弹出）。
 *   本函数只做「**台账剔除**」；系统侧的实际收敛由调用方**紧随其后的 `syncAll()`**
 *   以「清空 ＋ 重建」完成 —— 通知栏最终是**新配置的全量投影**。
 *
 * 入参可为**台账键**（`trigger.key`）或**提醒 id**（后者剔除该提醒的全部触发点）。
 *
 * @param {string} id 台账键 或 提醒 id
 * @returns {{ok:boolean, reason:string}}
 */
export function cancelLocal(id) {
    const k = String(id || '')
    if (!k) {
        return { ok: false, reason: REASON.EMPTY }
    }
    let removed = 0
    const keys = Object.keys(registry)
    for (let i = 0; i < keys.length; i++) {
        const entry = registry[keys[i]]
        if (entry.key === k || entry.reminderId === k) {
            delete registry[keys[i]]
            removed += 1
        }
    }
    if (removed === 0) {
        return { ok: false, reason: REASON.EMPTY }
    }
    return { ok: true, reason: '' }
}

/**
 * 取消**全部**已注册的本地通知 —— I-01 的执行点。
 *
 * 触发场景（DESIGN.md §13 / S1-C SC-14 I-01 注）：清缓存四触发（登出 / 注销 / 401 / 改密）
 *   —— 否则通知栏会暴露**前一位用户**的提醒内容；以及 SC-14 关闭全局总开关
 *   （裁定 ⑪：关闭 = **取消已注册通知**，而不是仅仅"不再注册"，否则通知栏会残留）。
 *
 * ★ 本批（S3-9 第 11 步）起，I-01 由"如实的空操作"**升级为真操作**：`plus.push.clear()`
 *   ＋ 清空内存台账。`clear()` 对**未触发**延迟通知的效力见 H-30（A6 真机验收定性）。
 *
 * @returns {{ok:boolean, cancelled:number, reason:string}}
 */
export function cancelAllRegistered() {
    const ids = Object.keys(registry)
    registry = {}
    if (!isAppRuntime()) {
        // H5 / 小程序内**不存在**系统通知通道 ⇒ 如实为空操作（不伪造动作）
        return {
            ok: ids.length === 0,
            cancelled: 0,
            reason: ids.length === 0 ? REASON.EMPTY : CAPABILITY.UNSUPPORTED
        }
    }
    try {
        plus.push.clear()
        return { ok: true, cancelled: ids.length, reason: ids.length === 0 ? REASON.EMPTY : '' }
    } catch (e) {
        note('cancelAllRegistered: plus.push.clear 异常：' + brief(e))
        return { ok: false, cancelled: ids.length, reason: REASON.ERROR }
    }
}

/**
 * 「去设置」：打开系统通知设置。
 *
 * 首选 `uni.openAppAuthorizeSetting()`（A4 真机实测**可进入**系统授权管理页）；
 * 降级 `plus.runtime.openSettings()`（跳应用设置页）；
 * 两者均不可用 ⇒ 返回 `{ok:false}`，由页面以中性文案提示（**绝不假装跳转成功**）。
 *
 * ★ 为何必须以"系统设置"为唯一可靠路径：Android 用户一旦**拒绝**通知权限
 *   （尤其勾选"不再询问"），再次运行时申请**不会弹框**、直接回调拒绝（S1-C 口径）。
 *
 * @returns {{ok:boolean, reason:string}}
 */
export function openSystemSettings() {
    if (!isAppRuntime()) {
        // H5 / 小程序内**不存在**系统通知设置页 ⇒ 如实失败，由页面以中性文案提示
        return { ok: false, reason: CAPABILITY.UNSUPPORTED }
    }
    if (typeof uni.openAppAuthorizeSetting === 'function') {
        try {
            uni.openAppAuthorizeSetting({
                success: function () {},
                fail: function (err) {
                    note('openAppAuthorizeSetting 失败：' + brief(err))
                }
            })
            return { ok: true, reason: '' }
        } catch (e) {
            note('openAppAuthorizeSetting 同步异常：' + brief(e))
        }
    }
    try {
        if (typeof plus !== 'undefined' && plus.runtime &&
            typeof plus.runtime.openSettings === 'function') {
            plus.runtime.openSettings()
            return { ok: true, reason: '' }
        }
    } catch (e2) {
        note('plus.runtime.openSettings 异常：' + brief(e2))
    }
    return { ok: false, reason: REASON.ERROR }
}

/* ══════════════════ 对账式全量重建（档 1） ══════════════════ */

/**
 * 把"未来触发点清单"**全量投影**到系统通知栏 —— 档 1 的唯一写路径。
 *
 * 顺序：① 清空（`plus.push.clear()` ＋ 清台账）→ ② 逐条重建（`registerLocal`）。
 * **先清后建**：避免残留与重复；这也让 `clear` 成为"撤销"的实际承担者（A2 已证伪 remove）。
 *
 * 节流：`minIntervalMs > 0` 时，若距上次同步不足该间隔则**直接跳过**（返回 `throttled` 语义
 * 的 `reason: REASON.EMPTY`）—— 供 `App.vue#onShow` 预防"前后台频繁切换导致高频重建"；
 * 页面内的**配置变更**调用应传 0（**每次都必须真同步**）。
 *
 * @param {Array} triggers `upcomingTriggers()` 的产出
 * @param {number} [minIntervalMs] 节流窗口（毫秒）；缺省 / 0 ⇒ 不节流
 * @returns {{ok:boolean, dispatched:number, cleared:boolean, reason:string}}
 */
export function syncAll(triggers, minIntervalMs) {
    const list = prepareTriggers(triggers)
    if (!isAppRuntime()) {
        return { ok: false, dispatched: 0, cleared: false, reason: CAPABILITY.UNSUPPORTED }
    }
    const gap = Number(minIntervalMs) > 0 ? Number(minIntervalMs) : 0
    if (gap > 0 && lastSyncAt > 0 && Date.now() - lastSyncAt < gap) {
        return { ok: true, dispatched: 0, cleared: false, reason: REASON.EMPTY }
    }
    let cleared = false
    try {
        plus.push.clear()
        cleared = true
    } catch (e) {
        note('syncAll: plus.push.clear 异常：' + brief(e))
    }
    registry = {}
    lastSyncAt = Date.now()

    const cap = getCapability()
    if (!cap.canNotify) {
        // 无通知权限：**只清不排**（避免系统通知栏残留旧配置），并如实返回原因
        note('syncAll: 无通知权限（' + cap.status + '），已清空未重排')
        return { ok: false, dispatched: 0, cleared: cleared, reason: cap.status }
    }

    let dispatched = 0
    for (let i = 0; i < list.length; i++) {
        if (registerLocal(list[i]).ok) {
            dispatched += 1
        }
    }
    note('syncAll: cleared=' + cleared + ' planned=' + list.length + ' dispatched=' + dispatched)
    return { ok: true, dispatched: dispatched, cleared: cleared, reason: '' }
}

/** 当前已注册条数（供自检与诊断使用，**不上屏**） */
export function registeredCount() {
    return Object.keys(registry).length
}
