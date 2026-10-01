/**
 * 轻提示总线（配合组件 C-13 `AppToast`）。
 *
 * 设计原因：
 *   1. 组件契约要求「同一时刻最多 1 条、`--d-toast` 后自动消失、不阻塞交互」（DESIGN.md §8.2 C-13）；
 *   2. 部分提示发生在**页面跳转前**（如 401 → `reLaunch` 到 SC-03 并提示「登录已过期，请重新登录」），
 *      此时当前页面的 Toast 实例即将销毁 —— 因此需要"待投递队列"，
 *      由目标页面挂载的 AppToast 在其 `mounted` 时补投（仅投递 3 秒内的消息，避免陈旧提示）。
 *
 * 用法：页面内放一个 `<AppToast />`；任何位置调用 `showToast('success', '已保存')`。
 */

/** 消息类型：success / error / info —— 与 DESIGN.md §8.2 C-13 一致 */
const VALID_TYPES = ['success', 'error', 'info']

/** 待投递队列的有效期（毫秒） */
const PENDING_TTL_MS = 3000

let handler = null
let pending = []

function deliver(type, text) {
    if (handler) {
        handler(type, text)
        return true
    }
    return false
}

/** AppToast 组件挂载时注册（并补投待投递消息） */
export function registerToastHandler(fn) {
    handler = fn
    const now = Date.now()
    const queue = pending.filter(function (item) {
        return now - item.at <= PENDING_TTL_MS
    })
    pending = []
    if (queue.length > 0) {
        const last = queue[queue.length - 1]
        fn(last.type, last.text)
    }
}

/** AppToast 组件卸载时注销 */
export function unregisterToastHandler(fn) {
    if (handler === fn) {
        handler = null
    }
}

/**
 * 显示一条轻提示。
 * @param {string} type success | error | info
 * @param {string} text 文案（必须来自产品文案口径，不得含医学判断）
 */
export function showToast(type, text) {
    const safeType = VALID_TYPES.indexOf(type) >= 0 ? type : 'info'
    const safeText = text === undefined || text === null ? '' : String(text)
    if (!safeText) {
        return
    }
    if (!deliver(safeType, safeText)) {
        pending.push({ type: safeType, text: safeText, at: Date.now() })
        // 队列上限：只保留最近 3 条，避免无界增长
        if (pending.length > 3) {
            pending = pending.slice(pending.length - 3)
        }
    }
}
