/**
 * 统一请求封装（`uni.request` 自研，**不引入 axios**）。
 *
 * 依据：
 *   - S1-D §5：「统一请求封装：**超时中断 + 明确提示**；**GET 可自动重试 1 次**、
 *     **写类一律不自动重试**；网络恢复**只刷当前页、不自动重放**；
 *     401 → 用 Refresh **单次**刷新，失败即登出并清缓存」；
 *   - S1-B §3.4/§3.5 统一响应体：`{ code, message, data, request_id }`，
 *     失败在存在字段级明细时**追加顶层 `errors[]`**（每项 3 键 `field`/`code`/`message`）；
 *   - S1-B §3.11 幂等：请求头 `Idempotency-Key`（8–128 字符，客户端生成）；
 *   - S1-B §五 认证：`Authorization: Bearer <access_token>`；
 *   - S1-B §3.6：**软提示 `SOFT_WARNING` 使用 HTTP 200**（不是错误）。
 *
 * 客户端执行口径（DESIGN.md §13 / §7）：
 *   - 写操作**点击即 disabled + loading**，且**禁止自动重试**；
 *   - 失败**绝不静默**：一律转换为可读文案交由页面 Toast / `AppErrorState` 呈现；
 *   - 401：单次 Refresh + 重放；Refresh 失败 → 清登录态与缓存 + `reLaunch` 到 SC-03
 *     + 提示「登录已过期，请重新登录」。
 *
 * 安全红线：**请求体不得携带 `user_id`**（服务端出现即 400，S1-D §6.3）。
 */
import { API_BASE_URL, REQUEST_TIMEOUT, IDEMPOTENCY_KEY_LEN } from './config'
import {
    getAccessToken,
    getRefreshToken,
    updateTokens,
    clearSessionAndCache
} from './auth'
import { showToast } from './toast'
import { ROUTES } from './route'

/** 网络层错误码（前端自造，**不属于** S1-B 的 18 个冻结错误码） */
export const NETWORK_ERROR_CODE = 'NETWORK_ERROR'

/** 网络不可用文案 */
const NETWORK_ERROR_TEXT = '当前网络不可用，请检查网络后重试'

/**
 * 会话失效文案（DESIGN.md §13 固定文案）。
 * ★ S4-2C 最小导出：头像 `multipart` 传输（`utils/avatar.js`，走 `uni.uploadFile` /
 *   `uni.downloadFile`，不经 `uni.request`）需构造与本层**同文案**的会话失效错误 ⇒
 *   复用本常量，避免同一句用户文案在两处漂移。
 */
export const SESSION_EXPIRED_TEXT = '登录已过期，请重新登录'

const JSON_HEADER = { 'Content-Type': 'application/json' }

/** 刷新令牌的单次并发合并（避免多个 401 同时刷新导致"重放 → TOKEN_REUSED"） */
let refreshingPromise = null

/** 生成一个 `Idempotency-Key`（32 位十六进制，长度落在 S1-B 冻结区间内） */
export function newIdempotencyKey() {
    let hex = ''
    while (hex.length < IDEMPOTENCY_KEY_LEN) {
        hex += Math.floor(Math.random() * 0x100000000).toString(16)
    }
    return hex.slice(0, IDEMPOTENCY_KEY_LEN)
}

/** 构造统一错误对象（`isApiError = true`，便于页面判定） */
function makeError(fields) {
    const err = new Error(fields && fields.message ? fields.message : '请求失败')
    err.isApiError = true
    err.code = (fields && fields.code) || NETWORK_ERROR_CODE
    err.message = (fields && fields.message) || NETWORK_ERROR_TEXT
    err.errors = (fields && fields.errors) || []
    err.httpStatus = (fields && fields.httpStatus) || 0
    err.data = (fields && fields.data) || null
    err.requestId = (fields && fields.request_id) || ''
    err.isNetwork = !!(fields && fields.isNetwork)
    return err
}

/** 单次发送（不含任何重试 / 刷新逻辑） */
function send(cfg) {
    return new Promise(function (resolve, reject) {
        uni.request({
            url: API_BASE_URL + cfg.url,
            method: cfg.method,
            data: cfg.data === null || cfg.data === undefined ? undefined : cfg.data,
            timeout: REQUEST_TIMEOUT,
            header: cfg.header,
            success: function (res) {
                resolve(res)
            },
            fail: function () {
                reject(makeError({
                    code: NETWORK_ERROR_CODE,
                    message: NETWORK_ERROR_TEXT,
                    isNetwork: true
                }))
            }
        })
    })
}

/** 会话失效统一处理：清登录态与缓存 → 提示 → 清栈回登录页 */
function handleSessionExpired() {
    clearSessionAndCache()
    showToast('error', SESSION_EXPIRED_TEXT)
    setTimeout(function () {
        uni.reLaunch({ url: ROUTES.LOGIN })
    }, 60)
}

/** 执行一次 A-03 刷新（**单次使用即轮换**，服务端强制） */
function doRefresh(refreshToken) {
    return send({
        url: '/auth/refresh',
        method: 'POST',
        data: { refresh_token: refreshToken },
        header: JSON_HEADER
    }).then(function (res) {
        const body = res.data
        if (res.statusCode >= 200 && res.statusCode < 300 && body && body.code === 'OK') {
            updateTokens(body.data)
            return true
        }
        // 刷新失败（含 TOKEN_REUSED / 已过期 / 会话失效）→ 按会话失效处理
        handleSessionExpired()
        return false
    }, function () {
        // 刷新请求本身网络失败：不视为会话失效（避免离线时被登出）
        return false
    })
}

/**
 * 单次刷新（并发合并，**401 会话刷新原语**）。
 * ★ S4-2C 最小、安全、可复用的导出：头像 `uni.uploadFile` / `uni.downloadFile` 无法走
 *   `uni.request` ⇒ 复用**同一套** 401 语义（单次刷新 + 并发合并 + 失败即清态回 SC-03），
 *   **不出现第二套认证体系**。
 * @returns {Promise<boolean>} true = 刷新成功（调用方重放一次）
 */
export function refreshOnce() {
    const refreshToken = getRefreshToken()
    if (!refreshToken) {
        handleSessionExpired()
        return Promise.resolve(false)
    }
    if (!refreshingPromise) {
        refreshingPromise = doRefresh(refreshToken).then(function (result) {
            refreshingPromise = null
            return result
        }, function () {
            refreshingPromise = null
            return false
        })
    }
    return refreshingPromise
}

/** 解析响应体：成功 / 软提示 → 返回 envelope；业务失败 → 抛错 */
function resolveBody(res) {
    const status = res.statusCode
    const body = res.data

    if (!body || typeof body !== 'object') {
        throw makeError({
            code: status >= 200 && status < 300 ? 'INVALID_RESPONSE' : 'HTTP_' + status,
            message: status >= 500 ? '服务器繁忙，请稍后重试' : '请求处理失败，请稍后重试',
            httpStatus: status
        })
    }

    if (body.code === 'OK') {
        return body
    }
    if (body.code === 'SOFT_WARNING') {
        // HTTP 200 + SOFT_WARNING：属"需要用户确认"的正常业务分支（S1-B §3.6）
        return body
    }
    throw makeError({
        code: body.code || 'HTTP_' + status,
        message: body.message || '请求处理失败，请稍后重试',
        errors: body.errors || [],
        data: body.data,
        request_id: body.request_id,
        httpStatus: status
    })
}

/**
 * 发送请求（统一入口）。
 *
 * @param {object} options
 *   url        相对 `/api/v1` 的路径，如 `/auth/login`
 *   method     GET | POST | PUT | PATCH | DELETE（默认 GET）
 *   data       请求体 / query 参数（默认 null）
 *   auth       是否需要登录态（默认 false）
 *   idempotencyKey 幂等键（写操作可选；**仅 S2 冻结口径中消费该头的接口才有意义**）
 * @returns {Promise<object>} 成功或软提示的统一响应体 `{ code, message, data, request_id }`
 */
export function request(options) {
    const cfg = {
        url: options.url,
        method: (options.method || 'GET').toUpperCase(),
        data: options.data === undefined ? null : options.data,
        auth: !!options.auth,
        idempotencyKey: options.idempotencyKey || null,
        header: {}
    }

    cfg.header['Content-Type'] = 'application/json'
    if (cfg.auth) {
        const token = getAccessToken()
        if (token) {
            cfg.header['Authorization'] = 'Bearer ' + token
        }
    }
    if (cfg.idempotencyKey) {
        cfg.header['Idempotency-Key'] = String(cfg.idempotencyKey)
    }

    const state = { networkRetried: false, refreshed: false }

    function execute() {
        return send(cfg).then(function (res) {
            // 401：单次 Refresh → 重放一次（仅限需要登录态的请求）
            if (res.statusCode === 401 && cfg.auth && !state.refreshed) {
                state.refreshed = true
                return refreshOnce().then(function (refreshed) {
                    if (refreshed) {
                        const token = getAccessToken()
                        cfg.header['Authorization'] = token ? 'Bearer ' + token : ''
                        return execute()
                    }
                    throw makeError({
                        code: 'UNAUTHENTICATED',
                        message: SESSION_EXPIRED_TEXT,
                        httpStatus: 401
                    })
                })
            }
            return resolveBody(res)
        }, function (err) {
            // 网络失败：**仅 GET 自动重试 1 次**（S1-D §5）；写类一律不重试
            if (cfg.method === 'GET' && !state.networkRetried) {
                state.networkRetried = true
                return execute()
            }
            throw err
        })
    }

    return execute()
}

/** GET（可带 query；默认按 S1-D 允许自动重试 1 次） */
export function get(url, params, options) {
    const opts = options || {}
    return request({
        url: url,
        method: 'GET',
        data: params || null,
        auth: !!opts.auth
    })
}

/** POST（写操作：**不自动重试**） */
export function post(url, body, options) {
    const opts = options || {}
    return request({
        url: url,
        method: 'POST',
        data: body === undefined ? null : body,
        auth: !!opts.auth,
        idempotencyKey: opts.idempotencyKey || null
    })
}

/** PUT（写操作：**不自动重试**） */
export function put(url, body, options) {
    const opts = options || {}
    return request({
        url: url,
        method: 'PUT',
        data: body === undefined ? null : body,
        auth: !!opts.auth,
        idempotencyKey: opts.idempotencyKey || null
    })
}

/**
 * 把错误对象转成"面向上方的用户文案"。
 * 依据：服务端 message 已是中性可展示文案（S1-B §3.6），网络错误用本地文案。
 */
export function errorText(err) {
    if (!err) {
        return '请求处理失败，请稍后重试'
    }
    if (err.isNetwork) {
        return NETWORK_ERROR_TEXT
    }
    return err.message || '请求处理失败，请稍后重试'
}

/**
 * 取字段级明细（`errors[]`）中某个字段的文案。
 * @returns {string} 无对应字段 → ''
 */
export function fieldErrorText(err, field) {
    if (!err || !err.errors || !err.errors.length) {
        return ''
    }
    for (let i = 0; i < err.errors.length; i++) {
        const item = err.errors[i]
        if (item && item.field === field) {
            return item.message || ''
        }
    }
    return ''
}
