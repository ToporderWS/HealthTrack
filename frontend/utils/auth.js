/**
 * 登录态 / 会话本地能力（**只读本地，不发请求**）。
 *
 * 依据：
 *   - S1-D §6：Access Token = JWT HS256（2h）、Refresh Token = 不透明随机串（30d，服务端只存哈希）；
 *     **刷新令牌单次使用即轮换**，重放 → `TOKEN_REUSED` 且该用户会话全失效；
 *   - S1-B 第三批 §2.6：登出 / 注销 / 401 / 改密 → 清除登录态与缓存；
 *   - S1-C SC-01 ⑰：启动阶段**不主动**刷新 Token（Token 有效性由首个业务接口的 401 裁决）。
 *
 * 安全红线：**不缓存密码明文**；Token 只落在 `kj:auth.*` 专用键（见 storage.js 说明）。
 */
import { KEYS, readJson, readRaw, writeJson, removeRaw, clearAuthScopedCache } from './storage'

/** 获取 Access Token（不存在 → null） */
export function getAccessToken() {
    const token = readRaw(KEYS.ACCESS_TOKEN)
    return token ? String(token) : null
}

/** 获取 Refresh Token（不存在 → null） */
export function getRefreshToken() {
    const token = readRaw(KEYS.REFRESH_TOKEN)
    return token ? String(token) : null
}

/** 是否持有本地登录态（Access 或 Refresh 任一存在即视为"已登录"） */
export function hasSession() {
    return !!(getAccessToken() || getRefreshToken())
}

/** 本地缓存的用户信息（未登录 → null） */
export function getCachedUser() {
    return readJson(KEYS.USER, null)
}

/**
 * 本地缓存的「是否已建档」标记。
 * @returns {boolean|null} true / false / null（未知）
 * 依据：A-02 登录与 A-06 `GET /users/me` 均返回 `profile_initialized`（客户端流程判定依据 F-009）。
 */
export function getCachedProfileInitialized() {
    const raw = readRaw(KEYS.PROFILE_INITIALIZED)
    if (raw === null) {
        return null
    }
    return String(raw) === 'true'
}

/**
 * 保存登录态（登录 / 注册成功后调用）。
 * @param {object} payload { tokens, user, profileInitialized }
 */
export function saveSession(payload) {
    const tokens = (payload && payload.tokens) || {}
    const user = (payload && payload.user) || null
    if (tokens.access_token) {
        writeJson(KEYS.ACCESS_TOKEN, tokens.access_token)
    }
    if (tokens.refresh_token) {
        writeJson(KEYS.REFRESH_TOKEN, tokens.refresh_token)
    }
    if (user) {
        writeJson(KEYS.USER, user)
    }
    if (payload && payload.profileInitialized !== undefined && payload.profileInitialized !== null) {
        writeJson(KEYS.PROFILE_INITIALIZED, payload.profileInitialized ? 'true' : 'false')
    }
}

/** 仅更新令牌（A-03 刷新成功后调用；**不覆盖**用户信息与建档标记） */
export function updateTokens(tokens) {
    if (!tokens) {
        return
    }
    if (tokens.access_token) {
        writeJson(KEYS.ACCESS_TOKEN, tokens.access_token)
    }
    if (tokens.refresh_token) {
        writeJson(KEYS.REFRESH_TOKEN, tokens.refresh_token)
    }
}

/** 清除登录态（登出 / 注销 / 改密 / 会话失效） */
export function clearSession() {
    removeRaw(KEYS.ACCESS_TOKEN)
    removeRaw(KEYS.REFRESH_TOKEN)
    removeRaw(KEYS.USER)
    removeRaw(KEYS.PROFILE_INITIALIZED)
}

/** 清除登录态 + 全部登录态相关缓存（对应 S1-B 四触发口径；保留引导 / 协议标记） */
export function clearSessionAndCache() {
    return clearAuthScopedCache()
}

/* ─────────────────── 首次引导 / 协议同意（设备级，不随登出清除） ─────────────────── */

/** 是否已同意协议（F-007 / F-008） */
export function isAgreementAccepted() {
    const record = readJson(KEYS.GUIDE_AGREEMENT, null)
    return !!(record && record.accepted === true)
}

/** 记录协议同意（本地留痕；服务端留痕由 A-01 `agreement_version` 完成） */
export function saveAgreement(version, acceptedAt) {
    return writeJson(KEYS.GUIDE_AGREEMENT, {
        accepted: true,
        version: version,
        accepted_at: acceptedAt || ''
    })
}

/** 已同意协议的版本号（未同意 → null） */
export function getAgreementVersion() {
    const record = readJson(KEYS.GUIDE_AGREEMENT, null)
    return record && record.version ? String(record.version) : null
}
