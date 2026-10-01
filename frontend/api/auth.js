/**
 * 认证与会话 / 账号 API（模块 A）。
 *
 * 依据：《S1-B 第二批 API 接口设计文档》§五（后端实现：`app/api/v1/auth.py`、`app/api/v1/users.py`、
 *       `app/api/v1/account.py`）
 *
 * | API | Method / Path | 鉴权 | 本批用途 |
 * |---|---|---|---|
 * | A-01 | `POST /auth/register` | 免登录 | SC-04 注册 |
 * | A-02 | `POST /auth/login` | 免登录 | SC-03 登录 |
 * | A-03 | `POST /auth/refresh` | 需 refresh_token | 由 `utils/request.js` 统一调用（401 单次刷新） |
 * | A-04 | `POST /auth/logout` | ✅ | SC-18 我的 → 退出登录（S3-7 首次实际调用） |
 * | A-05 | `PUT  /auth/password` | ✅ | SC-19 修改密码（S3-7 首次实际调用） |
 * | A-06 | `GET  /users/me` | ✅ | 会话恢复 / 建档标记刷新 / SC-18 资料区 |
 * | A-07 | `DELETE /users/me` | ✅ | SC-18 我的 → 注销账号（S3-7 首次实际调用） |
 *
 * ★ 本批新增的两个写接口（`A-05` / `A-07`）**自动化绝不执行**：
 *   `A-05` 会真实修改数据库中的账号密码、`A-07` 会在单事务内**物理删除 8 张表**的数据。
 *   二者只走人工验收（或另授权专用测试账号）。见 S3-7 预检报告 §8.1 ③'。
 *
 * ★ `A-07` 用的是 `DELETE` 且**需要请求体**：`utils/request.js`（S3-1 基线，**本批不改**）
 *   未提供 delete 语法糖，但其导出的 `request()` 本身即接受 `method` + `data`
 *   ⇒ 在本文件内直调 `request({ method: 'DELETE', data: {...}, auth: true })` 即可，
 *     无需改动冻结的请求层（预检报告 §6 S-4 的零改动解法）。
 *
 * 幂等说明（如实登记）：S1-B §3.11 建议客户端为注册 / 登录携带 `Idempotency-Key`；
 * **但 S2 已封板实现中仅 `POST /records` 与 `POST /records/batch-delete` 真正消费该头**
 * （`app/core/idempotency.py`），A / P / G 模块未接入。本批仍按契约"建议"携带，
 * 同时以**按钮立即 disabled + loading**（F-083 第一道防线）作为实际防重复手段。
 */
import { post, get, put, request } from '../utils/request'
import { AGREEMENT_VERSION } from '../utils/config'

/**
 * A-01 注册（成功 201）。
 * @param {object} payload { username, password, agreement_version?, agreement_accepted?, auto_login? }
 * @param {string} idempotencyKey 幂等键
 */
export function register(payload, idempotencyKey) {
    const body = {
        username: payload.username,
        password: payload.password,
        agreement_version: payload.agreement_version || AGREEMENT_VERSION,
        // F-008：协议必须为 true（服务端留痕 terms_agreed_at + agreement_version）
        agreement_accepted: payload.agreement_accepted !== false,
        auto_login: payload.auto_login !== false
    }
    return post('/auth/register', body, { idempotencyKey: idempotencyKey })
}

/**
 * A-02 登录。
 * @param {object} payload { username, password }
 * @param {string} idempotencyKey 幂等键
 */
export function login(payload, idempotencyKey) {
    return post('/auth/login', {
        username: payload.username,
        password: payload.password
    }, { idempotencyKey: idempotencyKey })
}

/**
 * A-04 退出登录（仅失效当前会话，**不删除任何业务数据**）。
 * 调用方（SC-18）必须随后执行前端清态（`store.clearSessionAndCache()`：清 9 项 + 取消已注册系统通知）
 * 并清栈跳 SC-03。成功后服务端消息为「已退出登录」。
 */
export function logout() {
    return post('/auth/logout', null, { auth: true })
}

/** A-06 获取当前用户（含 `profile_initialized`） */
export function fetchMe() {
    return get('/users/me', null, { auth: true })
}

/**
 * A-05 修改密码（成功 200；服务端消息「密码已修改，请重新登录」）。
 *
 * 请求体三字段（`backend/app/api/v1/auth.py` 的 `ChangePasswordSchema`，逐字对齐）：
 *   `old_password` / `new_password` / `confirm_password`
 *
 * ★ 成功后服务端**立即失效全部旧 Token（含当前设备）** ⇒ 调用方（SC-19）必须随即清态
 *   （`store.clearSessionAndCache()`）+ 清栈跳 SC-03，不可停留在本页继续请求。
 * ★ 原密码连续错 5 次由服务端返回 `429 SESSION_VERIFY_ABORTED` 承载（**不锁定账号、
 *   不计入登录失败计数**），前端只做文案映射，不本地计数。
 *
 * @param {object} payload { old_password, new_password, confirm_password }
 */
export function changePassword(payload) {
    return put('/auth/password', {
        old_password: payload.old_password,
        new_password: payload.new_password,
        confirm_password: payload.confirm_password
    }, { auth: true })
}

/**
 * A-07 注销账号（`DELETE /users/me`，**终局操作、无等待期**）。
 *
 * 请求体（`backend/app/api/v1/account.py`，逐字对齐）：
 *   `password`（当前登录密码）/ `confirm_text`（必须等于「注销账号」四字）
 *
 * ★ 服务端在单事务内**物理删除**该账号的 8 张表数据（不可逆、无冷静期）；
 *   核对文案与口径见 `S1-C SC-18 ⑮②` 与 `DESIGN.md §12`。
 * ★ 成功后调用方（SC-18）必须清态 + 清栈跳 SC-03，并提示「账号已注销」；
 *   **失败时不得跳转、不得出现"已注销但实际失败"的假成功**。
 *
 * @param {object} payload { password, confirm_text }
 */
export function closeAccount(payload) {
    return request({
        url: '/users/me',
        method: 'DELETE',
        data: {
            password: payload.password,
            confirm_text: payload.confirm_text
        },
        auth: true
    })
}
