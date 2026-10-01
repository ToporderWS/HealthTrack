/**
 * 邮箱绑定 / 换绑 API（**B3**：PR-04 / PR-05）。
 *
 * 依据：
 *   - 《S1-B 第二批 API 接口设计文档》§十七（B3 追加）—— 后端实现
 *     `backend/app/api/v1/email_bind.py` + `backend/app/schemas/email_bind.py`；
 *   - 《HealthTrack · B4-0 只读预检与 B4-1 前端冻结方案》§10.2（N）。
 *
 * | 编号 | Method / Path | 鉴权 | 请求体（**逐字段白名单**） | 成功 `data` |
 * |---|---|---|---|---|
 * | PR-04 | `POST /auth/email/bind-request` | ✅**需登录** | `{ email, current_password }` | **恒 `null`**（恒等响应，不泄露邮箱是否被占用） |
 * | PR-05 | `POST /auth/email/bind-confirm` | ✅**需登录** | `{ email, code, current_password }` | `{ email_bound: true }` |
 *
 * 契约要点（逐条落地）：
 *   - 身份**只**来自当前登录态（`Authorization: Bearer` ⇒ `auth: true`）；
 *     请求体**绝不携带** `user_id`（全局身份守卫会 400 `INVALID_PARAM`）；
 *   - `current_password` **两阶段均需复验**（状态机 STATE-2 发 `PR-04`、STATE-4 发 `PR-05`）；
 *   - **不新增 resend 接口**：重新发送验证码继续调用 `PR-04`，服从服务端 60 秒冷却；
 *   - **不做邮箱占用预检**：`EMAIL_TAKEN`（`409`）**只可能**出现在 `PR-05`；
 *   - `PR-05` **不撤销会话**（绑定成功无需重登、不清缓存），前端仅刷新资料区
 *     ⇒ 本模块**不触碰** `store/user.js`、不触碰任何本地存储。
 *
 * 安全红线：本模块**零日志**（不 `console.log` 邮箱 / 密码 / 验证码）、**零落盘**、**零 URL 参数**。
 *
 * ★ 不改 `api/auth.js`（PR-* 独立成文件，改动面更小、更易逐字节审计）。
 */
import { post } from '../utils/request'

/**
 * PR-04 请求邮箱绑定验证码（**需登录**；**恒等响应**）。
 *
 * **恒等响应**：目标邮箱可绑定 / 已被他账号占用 / 冷却期内 ⇒ 同一 `code` ＋ 同一 `message`
 * ＋ 同一 HTTP 200 ＋ 同一 `data: null` ⇒ 前端**不得**据此做任何占用推断，
 * 也**不得**在冷却期内提示「发送失败」。
 *
 * @param {object} payload { email, current_password }
 * @returns {Promise<object>} 统一响应体（`data` 恒为 `null`）
 */
export function requestEmailBind(payload) {
    return post('/auth/email/bind-request', {
        email: payload.email,
        current_password: payload.current_password
    }, { auth: true })
}

/**
 * PR-05 校验验证码并落库（**需登录**）。
 *
 * 失败语义（服务端）：
 *   - `422 PASSWORD_INVALID`：`current_password` 不正确（沿用既有密码错误语义，无字段级明细）；
 *   - `422 VALIDATION_FAILED`：`errors[].field = 'code'`（验证码错误 / 过期 / 与目标邮箱不符，
 *     **同一中性文案**）或 `'email'`（邮箱格式不正确）；
 *   - `429 SESSION_VERIFY_ABORTED`：尝试次数达上限 ⇒ 该码作废，需重新发起；
 *   - `409 EMAIL_TAKEN`：邮箱唯一冲突（整事务回滚，**无半写入**；旧邮箱保持有效）。
 *
 * 成功语义：同事务写 `email` ＋ `email_verified_at` ⇒ **旧邮箱立即失效**、**会话保持**。
 *
 * @param {object} payload { email, code, current_password }
 * @returns {Promise<object>} `data.email_bound === true`
 */
export function confirmEmailBind(payload) {
    return post('/auth/email/bind-confirm', {
        email: payload.email,
        code: payload.code,
        current_password: payload.current_password
    }, { auth: true })
}
