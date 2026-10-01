/**
 * 找回密码 API（**B2**：PR-01 / PR-02 / PR-03）。
 *
 * 依据：
 *   - 《S1-B 第二批 API 接口设计文档》§十七（B2 追加）—— 后端实现
 *     `backend/app/api/v1/password_reset.py` + `backend/app/schemas/password_reset.py`；
 *   - 《HealthTrack · B4-0 只读预检与 B4-1 前端冻结方案》§10.2（N）。
 *
 * | 编号 | Method / Path | 鉴权 | 请求体（**逐字段白名单**） | 成功 `data` |
 * |---|---|---|---|---|
 * | PR-01 | `POST /auth/password-reset/request` | ❌**免鉴权** | `{ username }` | **恒 `null`**（四态恒等，防账号枚举） |
 * | PR-02 | `POST /auth/password-reset/verify`  | ❌**免鉴权** | `{ username, code }` | `{ reset_token }`（**一次性**） |
 * | PR-03 | `POST /auth/password-reset/confirm` | ❌**免鉴权** | `{ reset_token, new_password, confirm_password }` | `{ all_sessions_revoked, revoked_sessions }` |
 *
 * 安全红线（逐条落地）：
 *   - 三个请求**均不携带** `Authorization`（`auth` 缺省 `false`）—— 找回是未登录场景入口；
 *   - `reset_token` **只在请求体**，既非 `Authorization: Bearer`，也**不进 URL / 路由参数**；
 *   - 请求体**绝不携带 `user_id` / 完整用户对象 / 多余字段**（全局身份守卫会 400 `INVALID_PARAM`）；
 *   - 本模块**不触碰任何存储**（无 `localStorage` / `uni.setStorageSync` / `store`），
 *     **不打印日志**，**不写 URL**；`reset_token` 的生命周期完全由
 *     `components/PasswordResetPanel.vue` 的**组件内存态**承担。
 *
 * ★ 不改 `api/auth.js`（其头部已登记 A-01~A-07 契约表；PR-* 独立成文件，
 *   改动面更小、更易逐字节审计）。
 */
import { post } from '../utils/request'

/**
 * PR-01 请求密码找回验证码（**免鉴权**）。
 *
 * **恒等响应**：账号存在且已绑定已验证邮箱 / 账号不存在 / 未绑定邮箱 / 冷却期内
 * ⇒ 同一 `code` ＋ 同一 `message` ＋ 同一 HTTP 200 ＋ 同一 `data: null`。
 * ⇒ 前端**不得**据此推断「账号是否存在」「是否已绑定邮箱」，也**不得**据此提示发送失败。
 *
 * @param {object} payload { username }
 * @returns {Promise<object>} 统一响应体（`data` 恒为 `null`）
 */
export function requestResetCode(payload) {
    return post('/auth/password-reset/request', {
        username: payload.username
    })
}

/**
 * PR-02 校验验证码并换取**一次性** `reset_token`（**免鉴权**）。
 *
 * 失败语义（服务端）：
 *   - `422 VALIDATION_FAILED`（`errors[].field = 'code'`）：验证码错误**或**已过期
 *     ⇒ **同一中性文案，不可区分**；
 *   - `429 SESSION_VERIFY_ABORTED`：尝试次数达上限 ⇒ 该码作废，需重新发起。
 *
 * @param {object} payload { username, code }
 * @returns {Promise<object>} `data.reset_token`
 */
export function verifyResetCode(payload) {
    return post('/auth/password-reset/verify', {
        username: payload.username,
        code: payload.code
    })
}

/**
 * PR-03 用 `reset_token` 设置新密码（**免鉴权**）。
 *
 * 失败语义（服务端）：
 *   - `401 UNAUTHENTICATED`：凭证无效 / 已过期 / **已被使用（重放）** ⇒ 同一中性文案；
 *   - `422 VALIDATION_FAILED`：`errors[].field = 'new_password'`（`WEAK_PASSWORD` / `SAME_AS_OLD`）
 *     或 `'confirm_password'`（`MISMATCH`）。
 *
 * 成功副作用：撤销该账号**全部会话**（`revoked_reason='password_reset'`）＋ 清零登录失败状态。
 * 因本流程处于**未登录态**，前端**无需**也**不得**做任何清态动作。
 *
 * @param {object} payload { reset_token, new_password, confirm_password }
 * @returns {Promise<object>}
 */
export function confirmReset(payload) {
    return post('/auth/password-reset/confirm', {
        reset_token: payload.reset_token,
        new_password: payload.new_password,
        confirm_password: payload.confirm_password
    })
}
