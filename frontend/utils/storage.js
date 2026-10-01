/**
 * 本地存储封装 —— **全项目唯一的本地读写入口**。
 *
 * 依据：
 *   - S1-D §5：「本地缓存 = `uni.setStorageSync` + 自研缓存模块；白名单 7 类、禁缓存 10 项、
 *     四层淘汰、TTL 24h / 字典 7d」；
 *   - S1-B 第三批 §2.2 黑名单：**密码明文 / Token 明文（进入通用缓存）/ file_token /
 *     已软删数据 / 他人数据 / file_path / 日志 / 环境信息 / 医学正常值 / 用户已另存文件**；
 *   - S1-B 第三批 §2.6 四触发清缓存：**手动登出 / 注销 / 401 / 改密**。
 *
 * 命名空间约定（严格分离，避免 Token 落入通用缓存）：
 *   - `kj:auth.*`   登录态（Access / Refresh Token、用户信息、建档标记）—— 属"登录态"，随四触发清除；
 *   - `kj:guide.*`  首次引导 / 协议同意标记 —— 属"设备级"状态，**不随登出清除**；
 *   - `kj:draft.*`  表单草稿（S1-B C6）—— 随四触发清除；
 *   - `kj:cache.*`  业务缓存（S3-1 尚未使用；留待 S3-2 起按 C1~C7 落地）；
 *   - `kj:reminder.*`  **提醒配置与兜底确认状态**（S3-6 登记）—— 属"用户本地数据"，
 *     随四触发清除；**刻意不放进 `kj:cache.*`**：业务缓存有 TTL 24h，而提醒配置是用户配置
 *     （不是服务端数据的缓存），放进去会在 24 小时后凭空消失（功能缺陷）。
 *
 * 安全说明（如实登记）：
 *   V1.0 不引入任何安全存储插件（DESIGN.md §14.6 禁止新增依赖），因此 Token 存放于
 *   应用私有存储的 `kj:auth.*` 专用键，与通用缓存命名空间隔离、不写日志、不在界面回显，
 *   并在「登出 / 注销 / 401 / 改密」四触发时一并清除。
 */

import { cancelAllRegistered } from './notify'

const PREFIX = 'kj:'

export const KEYS = {
    ACCESS_TOKEN: 'auth.access_token',
    REFRESH_TOKEN: 'auth.refresh_token',
    USER: 'auth.user',
    PROFILE_INITIALIZED: 'auth.profile_initialized',
    GUIDE_AGREEMENT: 'guide.agreement',
    DRAFT_PROFILE_SETUP: 'draft.profile_setup',
    REMINDER_CONFIG: 'reminder.config',
    REMINDER_CONFIRM: 'reminder.confirm',
    REMINDER_PROMPT: 'reminder.prompted'
}

/** 随「登出 / 注销 / 401 / 改密」清除的登录态键 */
const AUTH_SCOPED_KEYS = [
    KEYS.ACCESS_TOKEN,
    KEYS.REFRESH_TOKEN,
    KEYS.USER,
    KEYS.PROFILE_INITIALIZED
]

/**
 * 登录态受保护的命名空间前缀（新增业务缓存时按此约定登记）。
 * `reminder.` 于 **S3-6** 登记：提醒配置与兜底确认状态属**用户本地数据**，
 *   必须在四触发时一并清除（I-01：否则通知栏会暴露**前一位用户**的提醒内容）。
 */
const AUTH_SCOPED_PREFIXES = ['draft.', 'cache.', 'reminder.']

function fullKey(key) {
    return PREFIX + key
}

/** 读原始值；失败 / 不存在 → null */
export function readRaw(key) {
    try {
        const value = uni.getStorageSync(fullKey(key))
        return value === '' || value === undefined ? null : value
    } catch (e) {
        return null
    }
}

/** 写原始值；失败 → false（不抛异常，避免打断页面流程） */
export function writeRaw(key, value) {
    try {
        uni.setStorageSync(fullKey(key), value)
        return true
    } catch (e) {
        console.warn('[康迹] 本地写入失败：' + key)
        return false
    }
}

/** 删除单个键 */
export function removeRaw(key) {
    try {
        uni.removeStorageSync(fullKey(key))
        return true
    } catch (e) {
        return false
    }
}

/** 读 JSON；解析失败 → fallback */
export function readJson(key, fallback) {
    const raw = readRaw(key)
    if (raw === null) {
        return fallback
    }
    if (typeof raw === 'object') {
        return raw
    }
    try {
        return JSON.parse(raw)
    } catch (e) {
        return fallback
    }
}

/** 写 JSON（对象自动序列化） */
export function writeJson(key, value) {
    if (value === null || value === undefined) {
        return writeRaw(key, '')
    }
    if (typeof value === 'object') {
        return writeRaw(key, JSON.stringify(value))
    }
    return writeRaw(key, value)
}

/** 获取全部本地键（去掉命名空间前缀）；失败 → [] */
export function listKeys() {
    try {
        const info = uni.getStorageInfoSync()
        const keys = (info && info.keys) || []
        return keys
            .filter(function (k) { return k.indexOf(PREFIX) === 0 })
            .map(function (k) { return k.slice(PREFIX.length) })
    } catch (e) {
        return []
    }
}

/**
 * 清除「登录态相关」本地数据（S1-B 第三批 §2.6 四触发）。
 *
 * 清除项：Access/Refresh Token、用户信息、建档标记、表单草稿、业务缓存（`kj:cache.*`）、
 *         提醒配置与兜底确认状态（`kj:reminder.*`，S3-6 登记）。
 * 保留项：`kj:guide.*`（首次引导 / 协议同意标记 —— 设备级状态，不清除）。
 *
 * ★ I-01（**S3-6 落地**）：清缓存四个触发点**必须同时取消已注册的系统本地通知**，
 *   否则通知栏会**暴露前一位用户的提醒内容**。
 *   实现位置刻意放在**删除本地键之前**：先取消系统侧通知，再抹掉本地配置与注册痕迹，
 *   顺序反了会在"通知已删但配置还在"或"配置已删但注册表读不到"之间留出不一致窗口。
 *   取消动作由 `utils/notify.js` 的能力层执行；本阶段系统通道未接通（裁定 4：真机能力留 S3-9）
 *   ⇒ 注册表恒为空 ⇒ **如实为空操作**，不伪造动作、也不因此抛异常。
 *
 * 如实登记（本批未覆盖项，属后续批次职责）：
 *   - 「删除 App 沙盒内临时导出文件」—— 导出功能在 S3-8 实现，本批无任何临时文件；
 *   - 「清空内存中的敏感引用」—— 由各页面 onUnload 释放，见 SC-05 页面实现。
 *
 * @returns {string[]} 被清除的**本地键**清单（不含系统侧通知，调用方沿用既有契约）
 */
export function clearAuthScopedCache() {
    const removed = []

    // I-01：先取消系统本地通知（失败不阻断清理 —— 本地数据清除的优先级更高）
    try {
        cancelAllRegistered()
    } catch (e) {
        // 通知通道异常不应影响登出 / 注销 / 改密 / 401 的主流程
    }

    AUTH_SCOPED_KEYS.forEach(function (key) {
        if (readRaw(key) !== null) {
            removed.push(key)
        }
        removeRaw(key)
    })

    listKeys().forEach(function (key) {
        const hit = AUTH_SCOPED_PREFIXES.some(function (p) {
            return key.indexOf(p) === 0
        })
        if (hit) {
            removeRaw(key)
            removed.push(key)
        }
    })

    return removed
}
