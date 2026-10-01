<template>
    <!--
      F1b「忘记密码 / 自助找回」面板（**B4-2 第一批**；业务面板组件，非 P0 页、不注册 pages.json）

      依据：
        · 《HealthTrack · B4-0 只读预检与 B4-1 前端冻结方案》§4（G：7 主态 + 11 异常态）、
          §6（I：敏感状态）、§7（J：cooldown）、§9（L：无绑定邮箱 fallback）、
          §10.1（M：组件形态）；
        · 需求方 B4-2 第一批授权 §四 / §七 / §八 / §九 / §十 / §十一。

      承载方式：**下一批**由 `pages/auth/login.vue` 以页内步骤（`mode='login' | 'forgot'`）渲染本组件。
      本组件**不 import 路由、不改 store、不做任何跳转** —— 出口一律走 emit（`back-login` / `contact`）。

      七主态（与冻结 §4.1 逐条对应）：
        STEP-1 输入用户名 → PR-01
        STEP-2 已请求（恒等提示 + 60s 倒计时 + 重发 + 常驻联系入口 + 已收到下一步）
        STEP-3 输入验证码 → PR-02（成功取一次性 reset_token）
        STEP-4 验证成功过渡态（不显示、不复制 reset_token）→ 自动进入 STEP-5
        STEP-5 新密码 + 确认密码 → PR-03
        STEP-6 重置成功（[返回登录]）
        STEP-7 返回登录（出口：清敏感内存 → emit back-login）

      安全（硬约束，逐条落地）：
        · `resetToken` / `code` / `newPassword` / `confirmPassword` **仅存在于本组件 `data` 内存**；
          不落 `localStorage` / `uni storage` / Pinia / draft / URL / route / query / console / 日志；
        · 统一 `clearSensitive()`：成功 / 返回登录 / 组件卸载 三条路径均调用；
        · **零 `console.*`**；错误对象只经 `errorText()` / `fieldErrorText()` 转文案，绝不回显 `err` 本体；
        · 防账号枚举：**不**出现「用户名不存在」「账号未绑定邮箱」「验证码已发送到 x***@y.com」等任何文本；
          STEP-2 主提示**逐字使用服务端 `message`**（PR-01 四态恒等）。
    -->
    <view class="prp">
        <AppCard>
            <!-- ═══════════ STEP-1 输入用户名 ═══════════ -->
            <view v-if="step === STEPS.USERNAME">
                <text class="prp__lead">请输入你的用户名，我们会向该账号已绑定的邮箱发送验证码。</text>

                <view class="prp__gap"></view>

                <AppInput
                    v-model="username"
                    label="用户名"
                    placeholder="请输入用户名"
                    :maxlength="20"
                    clearable
                    :error="errors.username"
                    @confirm="onRequestCode"
                />

                <view class="prp__actions">
                    <AppButton
                        label="下一步"
                        type="primary"
                        size="l"
                        block
                        :loading="submitting"
                        @tap="onRequestCode"
                    />
                </view>

                <view class="prp__link-hit" hover-class="prp__link-hit--press" @tap="onBackLogin">
                    <text class="prp__link">返回登录</text>
                </view>
            </view>

            <!-- ═══════════ STEP-2 已请求（恒等提示 + 倒计时 + 重发 + 联系入口） ═══════════ -->
            <view v-else-if="step === STEPS.SENT">
                <text class="prp__notice">{{ notice }}</text>
                <text class="prp__assist">
                    若你的账号尚未绑定已验证邮箱，将无法收到验证码；可通过下方联系方式联系维护者协助处理。
                </text>

                <view class="prp__row">
                    <AppButton
                        :label="resendLabel"
                        type="secondary"
                        size="s"
                        :disabled="cooling"
                        :loading="submitting"
                        @tap="onResend"
                    />
                </view>

                <view class="prp__actions">
                    <AppButton
                        label="已收到，下一步"
                        type="primary"
                        size="l"
                        block
                        @tap="onGoCode"
                    />
                </view>

                <!-- email=NULL 用户的兜底出口：与 S4-3-1 既有未登录可达通道同一出口（SC-25） -->
                <view class="prp__link-hit" hover-class="prp__link-hit--press" @tap="onContact">
                    <text class="prp__link">未收到验证码？查看联系方式</text>
                </view>

                <view class="prp__link-hit" hover-class="prp__link-hit--press" @tap="onBackLogin">
                    <text class="prp__link">返回登录</text>
                </view>
            </view>

            <!-- ═══════════ STEP-3 输入验证码 ═══════════ -->
            <view v-else-if="step === STEPS.CODE">
                <AppInput
                    v-model="code"
                    label="验证码"
                    placeholder="请输入邮件中的验证码"
                    :maxlength="8"
                    clearable
                    :error="errors.code"
                    @confirm="onVerify"
                />

                <view class="prp__actions">
                    <AppButton
                        label="验证"
                        type="primary"
                        size="l"
                        block
                        :loading="submitting"
                        @tap="onVerify"
                    />
                </view>

                <view class="prp__link-hit" hover-class="prp__link-hit--press" @tap="onBackToSent">
                    <text class="prp__link">返回上一步</text>
                </view>
            </view>

            <!-- ═══════════ STEP-4 验证成功过渡态（自动进入 STEP-5） ═══════════ -->
            <view v-else-if="step === STEPS.VERIFIED">
                <text class="prp__notice">验证成功，请设置新密码。</text>
            </view>

            <!-- ═══════════ STEP-5 新密码 + 确认密码 ═══════════ -->
            <view v-else-if="step === STEPS.PASSWORD">
                <AppInput
                    v-model="newPassword"
                    label="新密码"
                    placeholder="请设置新密码"
                    password
                    :maxlength="64"
                    :error="errors.newPassword"
                />

                <view class="prp__gap"></view>

                <AppInput
                    v-model="confirmPassword"
                    label="确认密码"
                    placeholder="请再次输入新密码"
                    password
                    :maxlength="64"
                    :error="errors.confirmPassword"
                    @confirm="onConfirmReset"
                />

                <text class="prp__assist">密码需 8–64 位，且同时包含字母与数字。</text>

                <view class="prp__actions">
                    <AppButton
                        label="确认重置"
                        type="primary"
                        size="l"
                        block
                        :loading="submitting"
                        @tap="onConfirmReset"
                    />
                </view>

                <view class="prp__link-hit" hover-class="prp__link-hit--press" @tap="onBackLogin">
                    <text class="prp__link">返回登录</text>
                </view>
            </view>

            <!-- ═══════════ STEP-6 重置成功 ／ STEP-7 返回登录（出口） ═══════════ -->
            <view v-else>
                <text class="prp__notice">密码已重置，请使用新密码登录</text>
                <text class="prp__assist">为保护账号安全，该账号原有的登录状态已全部失效。</text>

                <view class="prp__actions">
                    <AppButton label="返回登录" type="primary" size="l" block @tap="onBackLogin" />
                </view>
            </view>
        </AppCard>
    </view>
</template>

<script>
/**
 * F1b 忘记密码面板。
 *
 * ★ 本组件的**唯一对外出口**是 emit（`back-login` / `contact`）：
 *   不 import `utils/route.js`、不做 `navigateTo/reLaunch`、不读写 `store`、
 *   不触碰 `utils/storage.js` / `utils/draft.js`（静态可核查）。
 */
import AppCard from './AppCard.vue'
import AppInput from './AppInput.vue'
import AppButton from './AppButton.vue'

import { requestResetCode, verifyResetCode, confirmReset } from '../api/passwordReset'
import { checkPassword, checkConfirmPassword } from '../utils/validate'
import { errorText, fieldErrorText } from '../utils/request'
import { showToast } from '../utils/toast'
import { createCodeSend, resendText, CODE_SEND_SECONDS } from '../utils/codeSend'

/** 七主态编号（与冻结方案 §4.1 的 STEP-1 ~ STEP-7 逐条对应；STEP-7 为出口态） */
const STEPS = {
    USERNAME: 1,
    SENT: 2,
    CODE: 3,
    VERIFIED: 4,
    PASSWORD: 5,
    RESET_OK: 6,
    RETURN_LOGIN: 7
}

/** STEP-4 → STEP-5 的过渡停留时长（毫秒）；纯视觉过渡，不承载任何业务判断 */
const VERIFIED_ADVANCE_MS = 700

/** STEP-2 主提示兜底（服务端 PR-01 恒等 message 的**同值**兜底；正常路径逐字用服务端 `message`） */
const REQUEST_NOTICE_FALLBACK = '如果该账号存在且已绑定邮箱，我们已发送验证码'

/** STEP-1 用户名必填提示 */
const USERNAME_REQUIRED = '请输入用户名'
/** STEP-3 验证码必填提示 */
const CODE_REQUIRED = '请输入验证码'

/** 服务端错误码（前端只做文案映射与分支，不做任何本地计数） */
const CODE_VALIDATION_FAILED = 'VALIDATION_FAILED'
const CODE_SESSION_VERIFY_ABORTED = 'SESSION_VERIFY_ABORTED'
const CODE_UNAUTHENTICATED = 'UNAUTHENTICATED'

/** 取字符串（空值 / 非字符串 → ''） */
function textOf(value) {
    if (value === null || value === undefined) {
        return ''
    }
    return String(value)
}

export default {
    name: 'PasswordResetPanel',
    components: {
        AppCard: AppCard,
        AppInput: AppInput,
        AppButton: AppButton
    },
    props: {
        /** 进入本面板时预填的用户名（由登录页带入；可为空） */
        initialUsername: { type: String, default: '' }
    },
    emits: [
        /** 回到登录表单（STEP-6/7 与各步「返回登录」）；载荷 = 已填用户名（便于登录页回填） */
        'back-login',
        /** 请求展示「联系方式」（由宿主页跳 SC-25；面板自身不做跳转） */
        'contact'
    ],
    data: function () {
        return {
            /** 当前主态（STEPS.*） */
            step: STEPS.USERNAME,

            /* ── 非敏感输入 ── */
            username: '',
            notice: REQUEST_NOTICE_FALLBACK,

            /* ── 敏感输入（**仅内存**，见 clearSensitive） ── */
            /** 验证码（F1b） */
            code: '',
            /** 一次性重置凭证（PR-02 → PR-03；**不是** Access/Refresh Token） */
            resetToken: '',
            /** 新密码 / 确认密码 */
            newPassword: '',
            confirmPassword: '',

            /* ── 交互态 ── */
            /** 提交闸门（防重复提交的第一道防线；按钮 loading 为第二道） */
            submitting: false,
            /** 倒计时剩余秒数（**纯 UX**，不持久化、不代表后端冷却状态） */
            countdown: 0,
            /** 字段级错误文案 */
            errors: {
                username: '',
                code: '',
                newPassword: '',
                confirmPassword: ''
            },

            /** `codeSend` 倒计时实例（非持久化；`beforeUnmount` 中 dispose） */
            counter: null,
            /** STEP-4 过渡定时器句柄（`beforeUnmount` / 回退时清除，防泄漏） */
            advanceTimer: null
        }
    },
    computed: {
        /**
         * 主态常量（模板 `STEPS.*` 的**实例可解析来源**）。
         * ★ B4-2-INTEGRATION-FIX（第二批）：`STEPS` 原为模块级 `const`，而 Options API
         *   模板表达式经组件实例解析（`_ctx.STEPS`）⇒ 实例上不存在 ⇒ 渲染期
         *   `TypeError: Cannot read properties of undefined (reading 'USERNAME')`，
         *   面板整块白屏。最小修复 = 以 computed 暴露**同一常量对象**
         *   （只读；不改模板、不改状态机、不改任何业务语义）。
         */
        STEPS: function () {
            return STEPS
        },
        /** 倒计时中（重发按钮置灰；**仅前端 UX 闸门**） */
        cooling: function () {
            return this.countdown > 0
        },
        /**
         * 重发按钮文案：`发送验证码` / `重发（58s）`（提交中的 loading 由 AppButton 承担）。
         * ★ 必须依赖响应式 `countdown`（而非倒计时实例的内部闭包变量），否则 computed 不会随秒推进刷新。
         */
        resendLabel: function () {
            return resendText(this.countdown)
        }
    },
    created: function () {
        this.username = textOf(this.initialUsername)
        const self = this
        this.counter = createCodeSend({
            seconds: CODE_SEND_SECONDS,
            onChange: function (remaining) {
                self.countdown = remaining
            }
        })
    },
    beforeUnmount: function () {
        this.disposeTimers()
        // 组件卸载 = 流程退出：清空全部敏感内存（冻结 §6.2「四条路径」之一）
        this.clearSensitive()
    },
    methods: {
        /* ═════════════════ STEP 推进 ═════════════════ */

        gotoStep: function (next) {
            this.step = next
        },

        /* ═════════════════ STEP-1 → PR-01 ═════════════════ */

        onRequestCode: function () {
            if (this.submitting) {
                return
            }
            const name = textOf(this.username).trim()
            if (!name) {
                this.errors.username = USERNAME_REQUIRED
                return
            }
            this.errors.username = ''
            const self = this
            this.submitting = true
            requestResetCode({ username: name }).then(function (body) {
                self.submitting = false
                // 恒等响应：**逐字信任服务端 message**，不另写近似文案（冻结 §7.4）
                self.notice = (body && body.message) ? textOf(body.message) : REQUEST_NOTICE_FALLBACK
                self.gotoStep(STEPS.SENT)
                self.startCountdown()
            }, function (err) {
                self.submitting = false
                // PR-01 无业务失败分支（四态恒等 200）⇒ 只可能是网络 / 服务端异常：就地提示、原态保留
                showToast('error', errorText(err))
            })
        },

        /** STEP-2 重新发送：**继续调用 PR-01**（不新增 resend 接口），服从服务端 60s 冷却 */
        onResend: function () {
            if (this.submitting || this.cooling) {
                return
            }
            const self = this
            this.submitting = true
            requestResetCode({ username: textOf(this.username).trim() }).then(function (body) {
                self.submitting = false
                self.notice = (body && body.message) ? textOf(body.message) : REQUEST_NOTICE_FALLBACK
                self.startCountdown()
            }, function (err) {
                self.submitting = false
                showToast('error', errorText(err))
            })
        },

        onGoCode: function () {
            if (this.submitting) {
                return
            }
            this.gotoStep(STEPS.CODE)
        },

        onBackToSent: function () {
            if (this.submitting) {
                return
            }
            this.gotoStep(STEPS.SENT)
        },

        /* ═════════════════ STEP-3 → PR-02 ═════════════════ */

        onVerify: function () {
            if (this.submitting) {
                return
            }
            const code = textOf(this.code).trim()
            if (!code) {
                this.errors.code = CODE_REQUIRED
                return
            }
            this.errors.code = ''
            const self = this
            this.submitting = true
            verifyResetCode({
                username: textOf(this.username).trim(),
                code: code
            }).then(function (body) {
                self.submitting = false
                const data = (body && body.data) ? body.data : {}
                self.resetToken = textOf(data.reset_token)
                if (!self.resetToken) {
                    // 契约异常（不应发生）：按中性文案处理并退回 STEP-1，绝不展示内部细节
                    showToast('error', '验证未完成，请重新发起找回')
                    self.backToStart()
                    return
                }
                // STEP-4 过渡态：**不显示、不做复制入口**；短暂停留后自动进入 STEP-5
                self.gotoStep(STEPS.VERIFIED)
                self.advanceTimer = setTimeout(function () {
                    self.advanceTimer = null
                    if (self.step === STEPS.VERIFIED) {
                        self.gotoStep(STEPS.PASSWORD)
                    }
                }, VERIFIED_ADVANCE_MS)
            }, function (err) {
                self.submitting = false
                self.handleVerifyError(err)
            })
        },

        /**
         * PR-02 失败处置：
         *   ① 尝试次数耗尽（429）⇒ 中性提示 + 清 code/resetToken + 回 STEP-1；
         *   ② 验证码错误 / 过期（422，**同一文案不可区分**）⇒ 验证码字段级提示，停留 STEP-3；
         *   ③ 网络 / 其他 ⇒ 就地提示，保留已填内容。
         */
        handleVerifyError: function (err) {
            const code = err && err.code ? String(err.code) : ''
            if (code === CODE_SESSION_VERIFY_ABORTED) {
                showToast('error', (err && err.message) ? textOf(err.message) : '验证失败次数过多，请重新发起')
                this.backToStart()
                return
            }
            if (code === CODE_VALIDATION_FAILED) {
                const codeError = fieldErrorText(err, 'code')
                const usernameError = fieldErrorText(err, 'username')
                if (codeError) {
                    this.errors.code = codeError
                    return
                }
                if (usernameError) {
                    this.errors.username = usernameError
                    this.backToStart()
                    return
                }
            }
            showToast('error', errorText(err))
        },

        /* ═════════════════ STEP-5 → PR-03 ═════════════════ */

        onConfirmReset: function () {
            if (this.submitting) {
                return
            }
            // 本地即时校验**仅作先导 UX 提示**；服务端为唯一权威（不复制密码规则）
            const pwError = checkPassword(this.newPassword, this.username, true)
            const cfError = checkConfirmPassword(this.newPassword, this.confirmPassword, true)
            this.errors.newPassword = pwError || ''
            this.errors.confirmPassword = cfError || ''
            if (pwError || cfError) {
                return
            }
            const self = this
            this.submitting = true
            confirmReset({
                reset_token: this.resetToken,
                new_password: this.newPassword,
                confirm_password: this.confirmPassword
            }).then(function () {
                self.submitting = false
                // 成功：**立刻**清空新密码 / 确认密码（早于进入 STEP-6）
                self.newPassword = ''
                self.confirmPassword = ''
                self.code = ''
                self.gotoStep(STEPS.RESET_OK)
            }, function (err) {
                self.submitting = false
                self.handleConfirmError(err)
            })
        },

        /**
         * PR-03 失败处置：
         *   ① 凭证无效 / 过期 / **已使用（重放）**（401，同一中性文案）⇒ 清敏感态 + 回 STEP-1；
         *   ② 密码规则 / 两次不一致（422 字段级）⇒ 字段提示，**停留 STEP-5 可修正重试**；
         *   ③ 网络 / 其他 ⇒ 就地提示，保留输入。
         */
        handleConfirmError: function (err) {
            const code = err && err.code ? String(err.code) : ''
            if (code === CODE_UNAUTHENTICATED || (err && err.httpStatus === 401)) {
                showToast('error', (err && err.message) ? textOf(err.message) : '重置凭证无效或已过期，请重新发起找回')
                this.backToStart()
                return
            }
            if (code === CODE_VALIDATION_FAILED) {
                const newError = fieldErrorText(err, 'new_password')
                const cfError = fieldErrorText(err, 'confirm_password')
                if (newError || cfError) {
                    this.errors.newPassword = newError || ''
                    this.errors.confirmPassword = cfError || ''
                    return
                }
            }
            showToast('error', errorText(err))
        },

        /* ═════════════════ 出口 / 清敏 ═════════════════ */

        /** 回 STEP-1 并清空流程内敏感态（尝试耗尽 / 凭证失效） */
        backToStart: function () {
            this.disposeTimers()
            this.stopCountdown()
            this.resetInputs()
            this.errors = { username: '', code: '', newPassword: '', confirmPassword: '' }
            this.gotoStep(STEPS.USERNAME)
        },

        /** STEP-6/7：清敏感内存 → 记录出口态 → 交由宿主页切回登录表单 */
        onBackLogin: function () {
            const name = textOf(this.username).trim()
            this.disposeTimers()
            this.stopCountdown()
            this.gotoStep(STEPS.RETURN_LOGIN)
            this.clearSensitive()
            this.$emit('back-login', name)
        },

        /** 联系维护者：**面板不跳转**，由宿主页处理（SC-25） */
        onContact: function () {
            this.$emit('contact')
        },

        /* ═════════════════ 定时器 ═════════════════ */

        startCountdown: function () {
            if (this.counter) {
                this.counter.start()
            }
        },

        stopCountdown: function () {
            if (this.counter) {
                this.counter.stop()
            }
        },

        /** 释放全部定时器（STEP-4 过渡定时器 + 倒计时）—— 防泄漏 */
        disposeTimers: function () {
            if (this.advanceTimer) {
                clearTimeout(this.advanceTimer)
                this.advanceTimer = null
            }
            if (this.counter) {
                this.counter.dispose()
            }
            this.countdown = 0
        },

        /* ═════════════════ 敏感态 ═════════════════ */

        /** 清空流程内全部敏感输入（成功 / 取消 / 关闭 / 卸载 四条路径统一调用） */
        clearSensitive: function () {
            this.resetToken = ''
            this.code = ''
            this.newPassword = ''
            this.confirmPassword = ''
        },

        /** 清空全部输入（回 STEP-1 时使用；含非敏感的用户名与提示） */
        resetInputs: function () {
            this.clearSensitive()
            this.notice = REQUEST_NOTICE_FALLBACK
        }
    }
}
</script>

<style scoped lang="scss">
.prp {
    width: 100%;
}

.prp__lead {
    display: block;
    font-size: var(--fs-body);
    line-height: $lh-body;
    color: var(--t-2);
    letter-spacing: 0;
}

/* STEP-2 / STEP-4 / STEP-6 主提示：中性、可读、不使用危险色 */
.prp__notice {
    display: block;
    font-size: var(--fs-body);
    line-height: $lh-body;
    font-weight: $fw-medium;
    color: var(--t-1);
    letter-spacing: 0;
}

/* 辅助说明（次要信息：未绑定邮箱兜底说明 / 密码规则） */
.prp__assist {
    display: block;
    margin-top: var(--sp-3);
    font-size: var(--fs-caption);
    line-height: $lh-caption;
    color: var(--t-3);
    letter-spacing: 0;
}

.prp__gap {
    height: var(--sp-6);
}

/* 重发按钮行：右对齐，与提示文字拉开节奏 */
.prp__row {
    display: flex;
    flex-direction: row;
    justify-content: flex-end;
    margin-top: var(--sp-5);
}

.prp__actions {
    margin-top: var(--sp-6);
}

/* 文字次级入口（返回登录 / 返回上一步 / 查看联系方式）：热区 ≥ --tap-min */
.prp__link-hit {
    min-height: var(--tap-min);
    margin-top: var(--sp-2);
    display: flex;
    flex-direction: row;
    align-items: center;
    justify-content: center;
    transition: transform var(--d-fast) var(--ease-std), opacity var(--d-fast) var(--ease-std);
}

.prp__link-hit--press {
    transform: scale(var(--press-scale));
    opacity: var(--press-opacity);
}

.prp__link {
    font-size: var(--fs-caption);
    line-height: $lh-caption;
    color: var(--t-link);
    letter-spacing: 0;
}
</style>
