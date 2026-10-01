<template>
    <!--
      A2「邮箱绑定 / 换绑」面板（**B4-2 第一批**；业务面板组件，非 P0 页、不注册 pages.json）

      依据：
        · 《HealthTrack · B4-0 只读预检与 B4-1 前端冻结方案》§5（H：5 主态 + 8 异常态）、
          §6（I：敏感状态）、§7（J：cooldown）、§8（K：EMAIL_TAKEN）、§10.1（M）；
        · 需求方 B4-2 第一批授权 §五 / §六 / §七 / §八 / §九 / §十一。

      承载方式：**下一批**由 `pages/mine/index.vue` 的 `AppModal`（`mode="confirm"`）默认插槽渲染本组件。
      绑定态**唯一数据源 = A-06 `GET /users/me`** 的 `email_bound` / `email_masked`（props 传入）；
      本组件**不推断**绑定态、**不读完整邮箱**、**不自建掩码来源**。

      五主态（与冻结 §5.1 逐条对应）：
        STATE-1 当前绑定态展示（未绑定 / 后端掩码邮箱）→ 点入口
        STATE-2 输入目标邮箱 + 当前密码 → PR-04（换绑时顶部展示后端掩码旧邮箱）
        STATE-3 恒等发送提示 + 60s 倒计时（[重新发送] / [下一步]）
        STATE-4 验证码 + **再次**当前密码 → PR-05
        STATE-5 绑定 / 换绑成功 → [完成] → emit success

      安全（硬约束，逐条落地）：
        · `email`（目标邮箱）/ `code` / `currentPassword` **仅存在于本组件 `data` 内存**；
          不落 `localStorage` / `uni storage` / Pinia / draft / URL / route / query / console / 日志；
        · `currentPassword`：**STATE-2 发送成功后立即置 ''**；STATE-4 **必须重新输入**（不复用 STATE-2 的密码）；
        · 统一 `clearSensitive()`：成功 / 关闭 / 组件卸载 三条路径均调用；
        · **零 `console.*`**；错误只经 `errorText()` / `fieldErrorText()` 转文案；
        · `EMAIL_TAKEN`（`409`）**只可能**出现在 `PR-05`，**不做**任何邮箱占用预检、**不新增** resend / check-email 接口；
        · 界面**绝不出现完整邮箱**：当前绑定态只用后端掩码；成功页回显的目标邮箱亦**本地掩码**后再展示；
        · `PR-05` 不撤销会话 ⇒ 本组件**不触碰** `store`、不重登、不清缓存，仅 emit `success` 交由宿主页刷新。
    -->
    <view class="ebp">
        <!-- ═══════════ STATE-1 当前绑定态展示 ═══════════ -->
        <view v-if="state === STATES.STATUS">
            <text class="ebp__label">{{ statusLabel }}</text>
            <text class="ebp__value" :class="{ 'ebp__value--unset': !isBound }">{{ statusText }}</text>
            <text class="ebp__assist">
                {{ isBound
                    ? '已验证邮箱可用于「忘记密码」自助找回；如需更换，请准备可正常收信的邮箱。'
                    : '绑定并验证邮箱后，即可使用「忘记密码」自助找回；也可以稍后再绑定。' }}
            </text>

            <view class="ebp__actions">
                <AppButton :label="entryLabel" type="primary" size="l" block @tap="onStart" />
            </view>
        </view>

        <!-- ═══════════ STATE-2 输入目标邮箱 + 当前密码 ═══════════ -->
        <view v-else-if="state === STATES.INPUT">
            <!-- 换绑：只展示**后端返回的掩码**旧邮箱；绝不展示完整邮箱 -->
            <view v-if="isBound" class="ebp__rebind">
                <text class="ebp__rebind-line">当前已验证邮箱：{{ currentMaskedText }}</text>
                <text class="ebp__rebind-tip">确认后将立即切换为新邮箱，旧邮箱随即失效。</text>
            </view>

            <AppInput
                v-model="email"
                label="邮箱"
                placeholder="请输入要绑定的邮箱"
                type="text"
                :maxlength="254"
                clearable
                :disabled="submitting"
                :error="errors.email"
            />

            <view class="ebp__gap"></view>

            <AppInput
                v-model="currentPassword"
                label="当前密码"
                placeholder="请输入当前登录密码"
                password
                :maxlength="64"
                :disabled="submitting"
                :error="errors.currentPassword"
                @confirm="onRequestCode"
            />

            <text class="ebp__assist">邮箱是密码找回的安全因子，绑定前需验证当前密码。</text>

            <view class="ebp__actions">
                <AppButton
                    :label="resendLabel"
                    type="primary"
                    size="l"
                    block
                    :disabled="cooling"
                    :loading="submitting"
                    @tap="onRequestCode"
                />
            </view>

            <view class="ebp__link-hit" hover-class="ebp__link-hit--press" @tap="onBackToStatus">
                <text class="ebp__link">返回上一步</text>
            </view>
        </view>

        <!-- ═══════════ STATE-3 恒等发送提示 + 倒计时 ═══════════ -->
        <view v-else-if="state === STATES.SENT">
            <text class="ebp__notice">{{ notice }}</text>
            <text class="ebp__assist">
                请到该邮箱查收验证码。若长时间未收到，可在倒计时结束后重新发送。
            </text>

            <view class="ebp__actions">
                <AppButton label="下一步" type="primary" size="l" block @tap="onGoCode" />
            </view>

            <view class="ebp__link-hit" hover-class="ebp__link-hit--press" @tap="onBackToInput">
                <text class="ebp__link">重新发送（需再次输入当前密码）</text>
            </view>
        </view>

        <!-- ═══════════ STATE-4 验证码 + 再次当前密码 ═══════════ -->
        <view v-else-if="state === STATES.CODE">
            <AppInput
                v-model="code"
                label="验证码"
                placeholder="请输入邮件中的验证码"
                :maxlength="8"
                clearable
                :disabled="submitting"
                :error="errors.code"
            />

            <view class="ebp__gap"></view>

            <!-- ★ 必须重新输入：STATE-2 的密码已在发送成功时清空，此处为**全新输入** -->
            <AppInput
                v-model="currentPassword"
                label="当前密码"
                placeholder="请再次输入当前登录密码"
                password
                :maxlength="64"
                :disabled="submitting"
                :error="errors.currentPassword"
                @confirm="onConfirmBind"
            />

            <view class="ebp__actions">
                <AppButton
                    label="确认绑定"
                    type="primary"
                    size="l"
                    block
                    :loading="submitting"
                    @tap="onConfirmBind"
                />
            </view>

            <view class="ebp__link-hit" hover-class="ebp__link-hit--press" @tap="onBackToSent">
                <text class="ebp__link">返回上一步</text>
            </view>
        </view>

        <!-- ═══════════ STATE-5 绑定 / 换绑成功 ═══════════ -->
        <view v-else>
            <text class="ebp__notice">{{ isRebind ? '邮箱已更换' : '邮箱绑定成功' }}</text>
            <text class="ebp__assist">已验证邮箱：{{ boundEchoText }}</text>
            <text v-if="isRebind" class="ebp__assist">旧邮箱已失效，请使用新邮箱进行密码找回。</text>

            <view class="ebp__actions">
                <AppButton label="完成" type="primary" size="l" block @tap="onDone" />
            </view>
        </view>
    </view>
</template>

<script>
/**
 * A2 邮箱绑定 / 换绑面板。
 *
 * ★ 绑定态**只消费** A-06 的 `email_bound` / `email_masked`（props）；
 *   本组件**不**读取完整邮箱、**不**自行推断绑定状态、**不**做邮箱占用预检。
 * ★ 唯一对外出口 = emit `success`（宿主页负责关闭弹层 + 刷新 A-06 + 重读 `email_bound`/`email_masked`）；
 *   本组件**不**修改 `store` 的会话、**不**跳转、**不**触碰任何本地存储。
 */
import AppInput from './AppInput.vue'
import AppButton from './AppButton.vue'

import { requestEmailBind, confirmEmailBind } from '../api/emailBind'
import { errorText, fieldErrorText } from '../utils/request'
import { showToast } from '../utils/toast'
import { createCodeSend, resendText, CODE_SEND_SECONDS } from '../utils/codeSend'

/** 五主态编号（与冻结方案 §5.1 的 STATE-1 ~ STATE-5 逐条对应） */
const STATES = {
    STATUS: 1,
    INPUT: 2,
    SENT: 3,
    CODE: 4,
    DONE: 5
}

/** STATE-3 主提示兜底（服务端 PR-04 恒等 message 的**同值**兜底；正常路径逐字用服务端 `message`） */
const REQUEST_NOTICE_FALLBACK = '如果该邮箱可绑定，我们已发送验证码'

/** 必填提示 */
const EMAIL_REQUIRED = '请输入邮箱'
const CODE_REQUIRED = '请输入验证码'
const PASSWORD_REQUIRED = '请输入当前密码'

/** 服务端错误码（前端只做文案映射与分支，不做任何本地计数） */
const CODE_VALIDATION_FAILED = 'VALIDATION_FAILED'
const CODE_PASSWORD_INVALID = 'PASSWORD_INVALID'
const CODE_EMAIL_TAKEN = 'EMAIL_TAKEN'
const CODE_SESSION_VERIFY_ABORTED = 'SESSION_VERIFY_ABORTED'
const CODE_UNAUTHENTICATED = 'UNAUTHENTICATED'

/** 取字符串（空值 / 非字符串 → ''） */
function textOf(value) {
    if (value === null || value === undefined) {
        return ''
    }
    return String(value)
}

/**
 * 本地最小掩码（**只用于回显用户自己刚输入的目标邮箱**，不用于任何后端状态展示）。
 *
 * 规则与后端 `app/services/auth_service.py::mask_email` **同形**：`local[:1] + '***' + '@' + domain`；
 * 非法 / 空 ⇒ `''`（此时回显为中性占位，绝不回退为完整邮箱）。
 *
 * ★ 用途边界（防误读）：A-06 「当前绑定态」的掩码**一律只用后端 `email_masked`**（props），
 *   本函数**不参与**该路径；它只服务于「成功页展示本次提交的目标邮箱」这一处，
 *   目的是**避免任何完整邮箱出现在界面**。
 */
function maskEmailText(value) {
    const raw = textOf(value).trim()
    const at = raw.lastIndexOf('@')
    if (at <= 0 || at === raw.length - 1) {
        return ''
    }
    return raw.slice(0, 1) + '***@' + raw.slice(at + 1)
}

export default {
    name: 'EmailBindPanel',
    components: {
        AppInput: AppInput,
        AppButton: AppButton
    },
    props: {
        /** A-06 `email_bound`：当前账号是否已绑定**已验证邮箱**（唯一数据源，不本地推断） */
        emailBound: { type: Boolean, default: false },
        /** A-06 `email_masked`：后端生成的掩码邮箱（`email_bound=false` 时为空串） */
        emailMasked: { type: String, default: '' }
    },
    emits: [
        /** 绑定 / 换绑成功（宿主页：关闭弹层 + 刷新 A-06 + 重读 email_bound / email_masked） */
        'success'
    ],
    data: function () {
        return {
            /** 当前主态（STATES.*） */
            state: STATES.STATUS,

            /** 目标邮箱（用户输入；**仅内存**，成功 / 关闭 / 卸载 置 ''） */
            email: '',
            /** 验证码（**仅内存**） */
            code: '',
            /** 当前密码（**仅内存**；STATE-2 发送成功后立即置 ''，STATE-4 重新输入） */
            currentPassword: '',

            /** 服务端恒等 message（STATE-3 主提示，逐字信任） */
            notice: REQUEST_NOTICE_FALLBACK,
            /** STATE-5 回显：本次提交目标邮箱的**本地掩码**（不展示完整邮箱） */
            boundEcho: '',

            /** 提交闸门（防重复提交） */
            submitting: false,
            /** 倒计时剩余秒数（**纯 UX**，不持久化、不代表后端冷却状态） */
            countdown: 0,
            /** 字段级错误文案 */
            errors: {
                email: '',
                code: '',
                currentPassword: ''
            },

            /** `codeSend` 倒计时实例（非持久化；`beforeUnmount` 中 dispose） */
            counter: null
        }
    },
    computed: {
        /**
         * 主态常量（模板 `STATES.*` 的**实例可解析来源**）。
         * ★ B4-2-INTEGRATION-FIX（第二批）：`STATES` 原为模块级 `const`，而 Options API
         *   模板表达式经组件实例解析（`_ctx.STATES`）⇒ 实例上不存在 ⇒ 渲染期
         *   `TypeError: Cannot read properties of undefined (reading 'STATUS')`，
         *   弹层面板整块白屏。最小修复 = 以 computed 暴露**同一常量对象**
         *   （只读；不改模板、不改状态机、不改任何业务语义）。
         */
        STATES: function () {
            return STATES
        },
        /** 是否已绑定已验证邮箱（**只读 A-06**） */
        isBound: function () {
            return this.emailBound === true
        },
        /** 换绑场景（已绑定 → 更换）；首次绑定为 false */
        isRebind: function () {
            return this.isBound
        },
        /** 当前绑定态展示值：未绑定 → 「未绑定」；已绑定 → **后端掩码**（空则中性占位） */
        statusText: function () {
            if (!this.isBound) {
                return '未绑定'
            }
            return textOf(this.emailMasked) || '已绑定'
        },
        /** 标签名（与 STATE-2 顶部提示共用同一数据源） */
        statusLabel: function () {
            return '邮箱'
        },
        /** 换绑时展示的当前邮箱（**只用后端掩码**） */
        currentMaskedText: function () {
            return textOf(this.emailMasked) || '已绑定'
        },
        /** STATE-5 回显文案（本地掩码；空 → 中性占位，绝不回退完整邮箱） */
        boundEchoText: function () {
            return this.boundEcho || '已绑定'
        },
        /** 入口按钮文案 */
        entryLabel: function () {
            return this.isRebind ? '更换邮箱' : '绑定邮箱'
        },
        /** 倒计时中（发送按钮置灰；**仅前端 UX 闸门**） */
        cooling: function () {
            return this.countdown > 0
        },
        /** 发送按钮文案（提交中的 loading 由 AppButton 承担） */
        resendLabel: function () {
            return resendText(this.countdown)
        }
    },
    created: function () {
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
        // 组件卸载（= 弹层关闭 / 页面退出）：清空全部敏感内存（冻结 §6.2「三条路径」之一）
        this.clearSensitive()
    },
    methods: {
        /* ═════════════════ 状态推进 ═════════════════ */

        onStart: function () {
            this.errors = { email: '', code: '', currentPassword: '' }
            this.state = STATES.INPUT
        },

        onBackToStatus: function () {
            if (this.submitting) {
                return
            }
            this.state = STATES.STATUS
        },

        onBackToInput: function () {
            if (this.submitting) {
                return
            }
            this.state = STATES.INPUT
        },

        onBackToSent: function () {
            if (this.submitting) {
                return
            }
            this.state = STATES.SENT
        },

        /* ═════════════════ STATE-2 → PR-04 ═════════════════ */

        onRequestCode: function () {
            if (this.submitting || this.cooling) {
                return
            }
            const email = textOf(this.email).trim()
            if (!email) {
                this.errors.email = EMAIL_REQUIRED
                return
            }
            if (!textOf(this.currentPassword)) {
                this.errors.email = ''
                this.errors.currentPassword = PASSWORD_REQUIRED
                return
            }
            this.errors.email = ''
            this.errors.currentPassword = ''
            const self = this
            this.submitting = true
            requestEmailBind({
                email: email,
                current_password: this.currentPassword
            }).then(function (body) {
                self.submitting = false
                // ★ 发送成功即清空当前密码（冻结 §6.1）；STATE-4 必须重新输入
                self.currentPassword = ''
                self.notice = (body && body.message) ? textOf(body.message) : REQUEST_NOTICE_FALLBACK
                self.state = STATES.SENT
                self.startCountdown()
            }, function (err) {
                self.submitting = false
                self.handleRequestError(err)
            })
        },

        /** PR-04 失败处置：当前密码错（422 PASSWORD_INVALID）／邮箱格式（422 field=email）／其他 */
        handleRequestError: function (err) {
            const code = err && err.code ? String(err.code) : ''
            if (code === CODE_PASSWORD_INVALID) {
                // 服务端该错误**无字段级明细** ⇒ 用顶层 message（服务端文案，不本地改写）
                this.errors.currentPassword = (err && err.message) ? textOf(err.message) : '当前密码不正确'
                return
            }
            if (code === CODE_VALIDATION_FAILED) {
                const emailError = fieldErrorText(err, 'email')
                if (emailError) {
                    this.errors.email = emailError
                    return
                }
            }
            this.showError(err)
        },

        onGoCode: function () {
            if (this.submitting) {
                return
            }
            this.errors.code = ''
            this.errors.currentPassword = ''
            this.state = STATES.CODE
        },

        /* ═════════════════ STATE-4 → PR-05 ═════════════════ */

        onConfirmBind: function () {
            if (this.submitting) {
                return
            }
            if (!textOf(this.code).trim()) {
                this.errors.code = CODE_REQUIRED
                return
            }
            if (!textOf(this.currentPassword)) {
                this.errors.code = ''
                this.errors.currentPassword = PASSWORD_REQUIRED
                return
            }
            this.errors.code = ''
            this.errors.currentPassword = ''
            const self = this
            this.submitting = true
            confirmEmailBind({
                email: textOf(this.email).trim(),
                code: textOf(this.code).trim(),
                current_password: this.currentPassword
            }).then(function () {
                self.submitting = false
                // 先固化**本地掩码**回显，再清空全部敏感输入（绝不保存完整邮箱）
                self.boundEcho = maskEmailText(self.email)
                self.clearSensitive()
                self.disposeTimers()
                self.state = STATES.DONE
            }, function (err) {
                self.submitting = false
                self.handleConfirmError(err)
            })
        },

        /**
         * PR-05 失败处置（冻结 §5.2）：
         *   ① `409 EMAIL_TAKEN`（**只可能**出现在此）⇒ 邮箱字段级提示（服务端 message）＋清 code → 回 STATE-2；
         *   ② `422 PASSWORD_INVALID` ⇒ 当前密码字段提示，停留 STATE-4；
         *   ③ `422 VALIDATION_FAILED`：`field='code'`（错误 / 过期 / 与目标邮箱不符，同一中性文案）
         *      或 `field='email'` ⇒ 对应字段提示，停留 STATE-4；
         *   ④ `429 SESSION_VERIFY_ABORTED`（尝试耗尽）⇒ 中性提示 ＋ 清 code → 回 STATE-2；
         *   ⑤ 网络 / 其他 ⇒ 就地提示，保留输入（**不得**以"未收到"为由提示"发送失败"）。
         */
        handleConfirmError: function (err) {
            const code = err && err.code ? String(err.code) : ''
            if (code === CODE_EMAIL_TAKEN) {
                this.errors.email = (err && err.message) ? textOf(err.message) : '该邮箱已被其他账号使用，请更换'
                this.code = ''
                this.errors.code = ''
                this.errors.currentPassword = ''
                this.state = STATES.INPUT
                return
            }
            if (code === CODE_PASSWORD_INVALID) {
                this.errors.currentPassword = (err && err.message) ? textOf(err.message) : '当前密码不正确'
                return
            }
            if (code === CODE_SESSION_VERIFY_ABORTED) {
                showToast('error', (err && err.message) ? textOf(err.message) : '验证失败次数过多，请重新发起')
                this.code = ''
                this.errors.code = ''
                this.errors.currentPassword = ''
                this.disposeTimers()
                this.state = STATES.INPUT
                return
            }
            if (code === CODE_VALIDATION_FAILED) {
                const codeError = fieldErrorText(err, 'code')
                const emailError = fieldErrorText(err, 'email')
                if (codeError) {
                    this.errors.code = codeError
                    return
                }
                if (emailError) {
                    this.errors.email = emailError
                    this.errors.code = ''
                    this.state = STATES.INPUT
                    return
                }
            }
            this.showError(err)
        },

        /* ═════════════════ 出口 / 清敏 ═════════════════ */

        /** STATE-5 → emit success（宿主页负责关闭弹层 + 刷新 A-06；本组件不做跳转、不碰 store） */
        onDone: function () {
            this.$emit('success')
        },

        /**
         * 统一错误出口：**只用统一请求层的安全文案**。
         * 会话失效（401 / UNAUTHENTICATED）由统一请求层负责清态与清栈跳 SC-03 ⇒ 此处**不重复提示**。
         */
        showError: function (err) {
            const code = err && err.code ? String(err.code) : ''
            if (code === CODE_UNAUTHENTICATED || (err && err.httpStatus === 401)) {
                return
            }
            showToast('error', errorText(err))
        },

        /* ═════════════════ 定时器 ═════════════════ */

        startCountdown: function () {
            if (this.counter) {
                this.counter.start()
            }
        },

        /** 释放倒计时定时器（防泄漏） */
        disposeTimers: function () {
            if (this.counter) {
                this.counter.dispose()
            }
            this.countdown = 0
        },

        /* ═════════════════ 敏感态 ═════════════════ */

        /** 清空全部敏感输入（成功 / 关闭 / 卸载 三条路径统一调用） */
        clearSensitive: function () {
            this.email = ''
            this.code = ''
            this.currentPassword = ''
        }
    }
}
</script>

<style scoped lang="scss">
.ebp {
    width: 100%;
}

.ebp__label {
    display: block;
    font-size: var(--fs-caption);
    line-height: $lh-caption;
    color: var(--t-3);
    letter-spacing: 0;
}

.ebp__value {
    display: block;
    margin-top: var(--sp-2);
    font-size: var(--fs-body);
    line-height: $lh-body;
    font-weight: $fw-medium;
    color: var(--t-1);
    letter-spacing: 0;
}

/* 未绑定：次要文字色 + 常规字重（与真实掩码值一眼可分） */
.ebp__value--unset {
    font-weight: $fw-regular;
    color: var(--t-3);
}

/* 换绑提示块：中性底、1rpx 描边，不使用危险色 */
.ebp__rebind {
    margin-bottom: var(--sp-6);
    padding: var(--sp-5);
    border-radius: var(--r-sm);
    background-color: var(--s-card-sub);
    border: 1rpx solid var(--b-line);
}

.ebp__rebind-line {
    display: block;
    font-size: var(--fs-sub);
    line-height: $lh-sub;
    font-weight: $fw-medium;
    color: var(--t-1);
    letter-spacing: 0;
}

.ebp__rebind-tip {
    display: block;
    margin-top: var(--sp-2);
    font-size: var(--fs-caption);
    line-height: $lh-caption;
    color: var(--t-3);
    letter-spacing: 0;
}

.ebp__notice {
    display: block;
    font-size: var(--fs-body);
    line-height: $lh-body;
    font-weight: $fw-medium;
    color: var(--t-1);
    letter-spacing: 0;
}

.ebp__assist {
    display: block;
    margin-top: var(--sp-3);
    font-size: var(--fs-caption);
    line-height: $lh-caption;
    color: var(--t-3);
    letter-spacing: 0;
}

.ebp__gap {
    height: var(--sp-6);
}

.ebp__actions {
    margin-top: var(--sp-6);
}

.ebp__link-hit {
    min-height: var(--tap-min);
    margin-top: var(--sp-2);
    display: flex;
    flex-direction: row;
    align-items: center;
    justify-content: center;
    transition: transform var(--d-fast) var(--ease-std), opacity var(--d-fast) var(--ease-std);
}

.ebp__link-hit--press {
    transform: scale(var(--press-scale));
    opacity: var(--press-opacity);
}

.ebp__link {
    font-size: var(--fs-caption);
    line-height: $lh-caption;
    color: var(--t-link);
    letter-spacing: 0;
}
</style>
