/**
 * 头像传输层（`utils/avatar.js`）—— **模块级内存缓存**，不触碰任何本地存储。
 *
 * 依据：
 *   - `S4-2A §五/§十/§十一`（头像上传 / 读取 / 删除的冻结方案）；
 *   - **S4-2C 需求方指令 §四/§五/§六**：独立头像工具（`uploadAvatar` / `downloadAvatar` /
 *     `deleteAvatar` / `clearAvatarCache` + 内存缓存）；上传走 `uni.uploadFile`（`multipart`，
 *     字段名 `file`，必须携带 `Authorization`）；读取走 `uni.downloadFile`（**必须鉴权**，
 *     URL **不含 `user_id` / `avatar_key` / 任何资源标识**）；
 *   - `utils/request.js` 是 **JSON 专用**（硬编码 `Content-Type: application/json`、走
 *     `uni.request`）⇒ **无法承载 multipart**，故本模块是"第二个传输"；但**认证语义必须同源**：
 *     401 → **复用** `request.js` 的 `refreshOnce()`（单次刷新 + 并发合并）→ **重放一次**；
 *     刷新失败 → 抛"登录已过期"（清登录态 + 提示 + 回 SC-03 已由 `request.js` 内部完成）
 *     ⇒ **不出现第二套认证体系**。
 *
 * 安全红线（`DESIGN.md §12` 头像条 / S4-2A §五）：
 *   - **不向前端暴露 `avatar_key` / 服务器路径 / `user_id`**：本模块只处理
 *     `avatar_updated_at`（服务端下发的版本戳）与 `tempFilePaths[0]`（框架消化后的临时路径）；
 *     URL 恒为常量 `/profile/avatar`；
 *   - **不写入本地存储**：缓存只活在模块级变量里（随进程消失），**不新增任何 `kj:` 键**；
 *   - **不持久化 `tempFilePath`**：模块级内存引用，`clearAvatarCache()` 即丢弃；
 *   - 错误对象**只承载安全文案**（服务端 message 已是中性可展示文案），不外泄堆栈 / 路径 / key。
 *
 * 平台差异（S4-2A §十二，如实登记）：
 *   - App 端 `uni.uploadFile` / `uni.downloadFile` 走原生（无跨域概念）；
 *   - H5 端两者走 XHR ⇒ 受 CORS 约束（需 `Origin` 命中后端 `DEV_CORS_ORIGINS`）。
 */
import { API_BASE_URL } from './config'
import { getAccessToken, getCachedUser } from './auth'
import { request, refreshOnce, SESSION_EXPIRED_TEXT, NETWORK_ERROR_CODE } from './request'

/* ─────────────────────────── 冻结常量 ─────────────────────────── */

/** 头像端点（**三端点共用同一路径**：POST 上传 / DELETE 删除 / GET 读取；URL 不含任何标识） */
export const AVATAR_PATH = '/profile/avatar'

/** multipart 字段名（与后端 `avatar_service.UPLOAD_FIELD` 逐字一致） */
export const AVATAR_UPLOAD_FIELD = 'file'

/** 选图张数（固定 1 张） */
export const AVATAR_PICK_COUNT = 1

/** 选图尺寸策略（固定压缩图，避免大原图直接触顶 2 MiB 上限） */
export const AVATAR_PICK_SIZE_TYPE = ['compressed']

/** 选图来源：相册 / 相机（**ActionSheet 已让用户选过来源 ⇒ 只传单一 `sourceType`**） */
export const AVATAR_SOURCE_ALBUM = 'album'
export const AVATAR_SOURCE_CAMERA = 'camera'

/**
 * 上传 / 下载超时（毫秒）。
 * 依据：uni-app `networkTimeout.uploadFile` / `downloadFile` 默认值 = 60000
 * （`unpackage/dist/dev/app-plus/app-config-service.js` 实测），显式声明以免随运行时默认值漂移。
 */
const UPLOAD_TIMEOUT_MS = 60000
const DOWNLOAD_TIMEOUT_MS = 60000

/* ─────────────────────── 模块级内存缓存 ─────────────────────── */

/**
 * **唯一**的头像缓存：`{ key, tempPath }`。
 *   - `key` = 当前用户身份 + `avatar_updated_at`（两者任一变化即视为不同版本 ⇒ 立即失效）；
 *   - `tempPath` = `uni.downloadFile` 返回的沙盒临时路径（**仅内存，绝不落盘**）。
 *
 * ★ 为什么**不**在页面 `onUnload` 清空：本工程 tabBar 切换用 `reLaunch`（页面被销毁重建）
 *   ⇒ 若随页面卸载清缓存，"同一会话内复用 tempFilePath"就永远不可能命中（每次都重新下载）。
 *   故缓存生命周期 = **本次 App 进程**，由以下四类事件显式失效：
 *     ① 上传成功（`uploadAvatar`）② 删除/恢复默认（`deleteAvatar`）
 *     ③ 身份或 `avatar_updated_at` 变化 ④ 登出 / 注销（页面在清态前调用 `clearAvatarCache()`）。
 */
let cache = { key: '', tempPath: '' }

/** 当前用户身份（**只读本地缓存**，不发请求；未登录 → ''） */
function currentIdentity() {
    const user = getCachedUser()
    if (!user || user.user_id === undefined || user.user_id === null) {
        return ''
    }
    return String(user.user_id)
}

/** 空值判定（`null` / `undefined` / `''` 均视为"无头像版本戳"） */
function isBlank(value) {
    return value === null || value === undefined || value === ''
}

/** 缓存键 = 身份 + 版本戳（**含身份 ⇒ 结构上不可能跨账号串用**） */
function cacheKeyOf(avatarUpdatedAt) {
    return currentIdentity() + '|' + String(avatarUpdatedAt)
}

/**
 * 清空头像内存缓存（丢弃 `tempFilePath` 引用）。
 * 调用点：上传成功 / 删除成功 / 身份或版本变化 / 登出 / 注销 / 页面判定需降级时。
 */
export function clearAvatarCache() {
    cache = { key: '', tempPath: '' }
}

/* ─────────────────────────── 错误对象 ─────────────────────────── */

/**
 * 构造统一错误对象（**与 `utils/request.js` 的 `makeError` 同形状**，
 * 使页面的 `errorText()` / `fieldErrorText()` / `isNetwork` 判定口径完全一致）。
 */
function makeError(fields) {
    const f = fields || {}
    const err = new Error(f.message ? f.message : '请求失败')
    err.isApiError = true
    err.code = f.code || NETWORK_ERROR_CODE
    err.message = f.message || '请求处理失败，请稍后重试'
    err.errors = f.errors || []
    err.httpStatus = f.httpStatus || 0
    err.data = f.data || null
    err.requestId = f.requestId || ''
    err.isNetwork = !!f.isNetwork
    return err
}

/** 网络层失败（**不属于** S1-B 的 18 个冻结错误码；文案由 `errorText()` 统一给出） */
function networkError() {
    return makeError({ code: NETWORK_ERROR_CODE, isNetwork: true })
}

/**
 * 会话失效（刷新失败）错误。
 * `sessionExpired = true` 供页面/调用方识别：**此时不要再弹一次错误提示**
 * ——「登录已过期，请重新登录」已由 `request.js` 的会话失效处理统一提示并清栈回 SC-03。
 */
function sessionExpiredError() {
    const err = makeError({
        code: 'UNAUTHENTICATED',
        message: SESSION_EXPIRED_TEXT,
        httpStatus: 401
    })
    err.sessionExpired = true
    return err
}

/** 是否"会话已失效"（页面据此跳过重复提示） */
export function isSessionExpired(err) {
    return !!(err && err.sessionExpired === true)
}

/* ─────────────────────────── 传输原语 ─────────────────────────── */

/** 认证头（**每次发送时现取** ⇒ 重放时自动用上刷新后的新 Token） */
function authHeader() {
    const token = getAccessToken()
    return token ? { Authorization: 'Bearer ' + token } : {}
}

/**
 * 401 → **复用 `request.js` 的同一套单次刷新**（并发合并）→ 重放**一次**。
 * 判定与 `utils/request.js#request()` 完全同源（仅"需要登录态的请求"才刷新）。
 *
 * @param {Function} attempt 返回 `Promise<{statusCode, ...}>` 的单次发送
 */
function withReplayOnce(attempt) {
    const state = { refreshed: false }

    function run() {
        return attempt().then(function (res) {
            if (res && res.statusCode === 401 && !state.refreshed) {
                state.refreshed = true
                return refreshOnce().then(function (refreshed) {
                    if (refreshed) {
                        return run()
                    }
                    throw sessionExpiredError()
                })
            }
            return res
        })
    }

    return run()
}

/**
 * 解析统一响应体 `{ code, message, data, request_id }`。
 * `uni.uploadFile` 的 `res.data` 是**字符串**（需自行 `JSON.parse`），故与 JSON 传输分开处理。
 */
function parseEnvelope(res) {
    const status = res && res.statusCode ? res.statusCode : 0
    let body = res ? res.data : null

    if (typeof body === 'string') {
        if (!body) {
            body = null
        } else {
            try {
                body = JSON.parse(body)
            } catch (e) {
                body = null
            }
        }
    }
    if (!body || typeof body !== 'object') {
        throw makeError({
            code: 'INVALID_RESPONSE',
            message: status >= 500 ? '服务器繁忙，请稍后重试' : '请求处理失败，请稍后重试',
            httpStatus: status
        })
    }
    if (body.code === 'OK' || body.code === 'SOFT_WARNING') {
        return body
    }
    throw makeError({
        code: body.code || 'HTTP_' + status,
        message: body.message || '请求处理失败，请稍后重试',
        errors: body.errors || [],
        data: body.data,
        requestId: body.request_id,
        httpStatus: status
    })
}

/* ─────────────────────────── 对外能力 ─────────────────────────── */

/**
 * 上传 / 更换头像（AV-01 `POST /profile/avatar`）。
 *
 * 契约（S4-2B 实现）：`200 { code:"OK", message:"头像已更新", data:{ avatar_updated_at } }`
 *   —— **响应不含 `avatar_key` / 路径 / 可复制地址**，故前端只能拿到版本戳。
 *
 * 写操作 **不自动重试**（仅 401 会话刷新后重放一次）。
 *
 * @param {string} filePath `uni.chooseImage` 返回的 `tempFilePaths[0]`
 * @returns {Promise<object>} 统一响应体
 */
export function uploadAvatar(filePath) {
    if (isBlank(filePath)) {
        return Promise.reject(makeError({
            code: 'INVALID_PARAM',
            message: '请选择要上传的图片'
        }))
    }

    function attempt() {
        return new Promise(function (resolve, reject) {
            uni.uploadFile({
                url: API_BASE_URL + AVATAR_PATH,
                filePath: String(filePath),
                name: AVATAR_UPLOAD_FIELD,
                header: authHeader(),
                timeout: UPLOAD_TIMEOUT_MS,
                success: function (res) {
                    resolve(res)
                },
                fail: function () {
                    // 网络层失败：写操作不重试（S1-D §5）
                    reject(networkError())
                }
            })
        })
    }

    return withReplayOnce(attempt).then(function (res) {
        const body = parseEnvelope(res)
        // 上传成功 ⇒ 立即失效旧缓存（旧 tempFilePath 已对应旧文件，必须丢弃）
        clearAvatarCache()
        return body
    })
}

/**
 * 读取本人头像临时路径（AV-03 `GET /profile/avatar`，**必须鉴权**）。
 *
 * 语义：
 *   - `avatarUpdatedAt` 为空 ⇒ **不发任何请求**，直接返回 `null`（`avatar_key IS NULL` = 未设置头像）；
 *   - 缓存键命中 ⇒ 直接复用 `tempFilePath`（**零网络请求**）；
 *   - 缓存键不命中（身份或版本戳变化）⇒ 丢弃旧缓存后下载；
 *   - 下载 `404`（库里有版本戳但文件缺失，属外部误删）⇒ 返回 `null` ⇒ 页面降级默认头像；
 *   - 下载失败 ⇒ 清缓存并抛错（调用方降级默认头像，**不得显示破图**）。
 *
 * 只读请求；`401` 同源刷新 + 重放一次（同 `utils/request.js`）。
 *
 * @param {string|number|null} avatarUpdatedAt P-01 返回的 `profile.avatar_updated_at`
 * @returns {Promise<string|null>} 沙盒临时路径；`null` = 无头像 / 文件缺失
 */
export function downloadAvatar(avatarUpdatedAt) {
    if (isBlank(avatarUpdatedAt)) {
        clearAvatarCache()
        return Promise.resolve(null)
    }

    const key = cacheKeyOf(avatarUpdatedAt)
    if (cache.key === key && cache.tempPath) {
        return Promise.resolve(cache.tempPath)
    }
    if (cache.key !== key) {
        clearAvatarCache()
    }

    function attempt() {
        return new Promise(function (resolve, reject) {
            uni.downloadFile({
                url: API_BASE_URL + AVATAR_PATH,
                header: authHeader(),
                timeout: DOWNLOAD_TIMEOUT_MS,
                success: function (res) {
                    resolve(res)
                },
                fail: function () {
                    reject(networkError())
                }
            })
        })
    }

    return withReplayOnce(attempt).then(function (res) {
        const status = res && res.statusCode ? res.statusCode : 0
        if (status === 404) {
            clearAvatarCache()
            return null
        }
        if (status < 200 || status >= 300 || !res || !res.tempFilePath) {
            clearAvatarCache()
            throw makeError({
                code: 'HTTP_' + status,
                message: '头像加载失败，请稍后重试',
                httpStatus: status
            })
        }
        cache = { key: key, tempPath: String(res.tempFilePath) }
        return cache.tempPath
    }, function (err) {
        // 网络失败 / 会话失效：不留半成品缓存
        clearAvatarCache()
        throw err
    })
}

/**
 * 删除头像 / 恢复默认（AV-02 `DELETE /profile/avatar`，**幂等**）。
 *
 * JSON 请求、无请求体 ⇒ **直接复用 `utils/request.js` 的 `request()`**
 * （沿用 `api/auth.js` 直调 `request({method:'DELETE'})` 的既有先例，**不改冻结请求层**）
 * ⇒ 401 刷新 / 重放 / envelope 解析 / 不自动重试 全部同源。
 *
 * 契约（S4-2B 实现）：`200 { code:"OK", message:"已恢复默认头像", data:{ avatar_updated_at:null } }`
 *
 * @returns {Promise<object>} 统一响应体
 */
export function deleteAvatar() {
    return request({ url: AVATAR_PATH, method: 'DELETE', auth: true }).then(function (body) {
        clearAvatarCache()
        return body
    })
}
