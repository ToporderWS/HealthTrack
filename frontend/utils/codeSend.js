/**
 * 验证码「发送 / 重发」倒计时 —— **纯前端 UX 逻辑**（F1b 与 A2 共用一份）。
 *
 * 依据：
 *   - 《HealthTrack · B4-0 只读预检与 B4-1 前端冻结方案》§7（J：cooldown 处理）；
 *   - 需求方 B4-2 第一批授权 §八（codeSend.js 职责边界）。
 *
 * ★ 职责**只允许**（冻结）：
 *     ① 开始倒计时；② 剩余秒数；③ 是否允许再次点击；④ 按钮文案；⑤ 停止；⑥ 销毁 / 清理。
 * ★ **不得**负责（红线）：
 *     - 判断后端是否真的发信；- 判断 cooldown 是否结束；- 持久化倒计时；
 *     - 写 `localStorage` / `uni.setStorageSync`；- 写 Pinia；- 写 URL；- 调用任何 API。
 *   **后端始终是 cooldown 的唯一权威**：刷新 / 重新进入导致前端倒计时丢失是**允许**的
 *   （服务端仍负责真实 60 秒冷却；且 PR-01 / PR-04 在冷却期内**仍返回恒等 200**，
 *    前端本来也无从区分「已发送」与「冷却中」）。
 *
 * ★ 本模块**零副作用、零依赖**：不 import 任何工程内模块，便于静态核查与单测。
 */

/** 冻结的倒计时秒数（与后端 60 秒冷却同值；仅用于 UX，不构成任何服务端承诺） */
export const CODE_SEND_SECONDS = 60

/** 倒计时计时步长（毫秒） */
const TICK_MS = 1000

/**
 * 把「剩余秒数」转成按钮文案。
 * 三态中的「提交中」由 `AppButton` 自身的 `loading` 承担，**不在本函数内**。
 * @param {number} remaining 剩余秒数（<=0 表示可发送）
 * @returns {string} `发送验证码` / `重发（58s）`
 */
export function resendText(remaining) {
    const left = Number(remaining)
    if (!isFinite(left) || left <= 0) {
        return '发送验证码'
    }
    return '重发（' + Math.floor(left) + 's）'
}

/**
 * 是否允许再次点击「发送 / 重发」。
 * ★ 仅为**前端 UX 闸门**：放宽它并不能真正绕过服务端冷却（服务端二次校验）。
 * @param {number} remaining 剩余秒数
 * @returns {boolean}
 */
export function canResend(remaining) {
    const left = Number(remaining)
    return !isFinite(left) || left <= 0
}

/**
 * 创建一个倒计时实例（工厂）。
 *
 * @param {object} [options]
 *   options.seconds  {number}   倒计时总秒数（默认 {@link CODE_SEND_SECONDS}）
 *   options.onChange {Function} 每次变化回调 `(remaining) => void`；由调用方写入自身响应式数据
 * @returns {object} 实例（方法均不触碰任何存储 / 网络 / 全局状态）
 *   - start()           开始（或重新开始）倒计时；重复调用先清旧定时器
 *   - stop()            立即停止并归零，并回调一次
 *   - dispose()         仅清定时器（**不回调** —— 用于组件卸载期，避免卸载后写状态）
 *   - isCooling()       当前是否处于倒计时中
 *   - remaining()       当前剩余秒数（number）
 *   - text()            当前按钮文案
 */
export function createCodeSend(options) {
    const opts = options || {}
    const total = isFinite(Number(opts.seconds)) && Number(opts.seconds) > 0
        ? Math.floor(Number(opts.seconds))
        : CODE_SEND_SECONDS
    const onChange = typeof opts.onChange === 'function' ? opts.onChange : null

    let remaining = 0
    let timer = null

    function clearTimer() {
        if (timer) {
            clearInterval(timer)
            timer = null
        }
    }

    function emit() {
        if (onChange) {
            onChange(remaining)
        }
    }

    function tick() {
        remaining = remaining > 0 ? remaining - 1 : 0
        if (remaining <= 0) {
            clearTimer()
        }
        emit()
    }

    return {
        start: function () {
            clearTimer()
            remaining = total
            emit()
            timer = setInterval(tick, TICK_MS)
        },
        stop: function () {
            clearTimer()
            remaining = 0
            emit()
        },
        dispose: function () {
            clearTimer()
            remaining = 0
        },
        isCooling: function () {
            return remaining > 0
        },
        remaining: function () {
            return remaining
        },
        text: function () {
            return resendText(remaining)
        }
    }
}
