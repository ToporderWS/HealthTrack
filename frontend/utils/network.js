/**
 * 网络状态（离线判断）。
 *
 * 依据：
 *   - S1-C §四 网络与离线行为矩阵：「可读缓存只读、写操作禁用、明确提示、**不自动重放**」；
 *   - S1-D §5：「网络恢复**只刷当前页**、不自动重放」。
 *
 * S3-1 只在**提交前**做一次离线判定（写操作直接禁用 + 明确提示），
 * 不做离线队列、不做自动重放。
 */

/** 判断当前是否在线；取值失败时保守返回 true（让请求层给出真实网络错误） */
export function isOnline() {
    return new Promise(function (resolve) {
        try {
            uni.getNetworkType({
                success: function (res) {
                    resolve(res && res.networkType !== 'none')
                },
                fail: function () {
                    resolve(true)
                }
            })
        } catch (e) {
            resolve(true)
        }
    })
}

/** 离线时的统一提示文案（与 S1-C 逐页口径一致） */
export const OFFLINE_SUBMIT_TEXT = '当前网络不可用，请联网后重试'

/** 面向具体动作的离线提示（登录 / 注册 / 保存） */
export function offlineText(action) {
    if (action === 'login') {
        return '当前网络不可用，请联网后登录'
    }
    if (action === 'register') {
        return '当前网络不可用，请联网后注册'
    }
    if (action === 'save') {
        return '当前网络不可用，请联网后保存'
    }
    return OFFLINE_SUBMIT_TEXT
}
