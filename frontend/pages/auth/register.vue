<template>
    <!--
      SC-04 注册页（pages/auth/register）
      依据：S1-C §二 SC-04 ｜ DESIGN.md §11 / §13
      · ① 用户名 + 密码 + 确认密码 ② 密码规则说明一行 ③ 主按钮「注册并登录」 ④ 底部「已有账号？去登录」
      · **仅用户名 + 密码**（不采集邮箱 / 手机号 / 第三方账号）
      · 密码规则（S1-B 冻结）：8–64 位、须同时含字母与数字、不得与用户名相同；**前端即时提示 + 服务端最终裁决**
      · 协议同意：进入本页前已在 SC-02 完成（F-008）；未同意则回到 SC-02，**不在此页重复造协议 UI**
      · 成功后：自动登录 → SC-05 建档引导（**不弹"注册成功"再点一次**）
    -->
    <view class="reg">
        <view class="reg__status"></view>

        <view class="reg__head">
            <text class="reg__title">创建账号</text>
            <text class="reg__desc">只需用户名和密码，即可开始记录</text>
        </view>

        <view class="reg__form">
            <AppCard>
                <AppInput
                    v-model="username"
                    label="用户名"
                    placeholder="请输入用户名"
                    hint="4–20 位，字母开头，可用字母 / 数字 / 下划线"
                    :maxlength="20"
                    clearable
                    :error="errors.username"
                />

                <view class="reg__gap"></view>

                <AppInput
                    v-model="password"
                    label="密码"
                    placeholder="请输入密码"
                    hint="至少 8 位，且需同时包含字母和数字"
                    password
                    :maxlength="64"
                    :error="errors.password"
                />

                <view class="reg__gap"></view>

                <AppInput
                    v-model="confirmPassword"
                    label="确认密码"
                    placeholder="请再次输入密码"
                    password
                    :maxlength="64"
                    :error="errors.confirm"
                    @confirm="handleSubmit"
                />

                <!-- S4-1：密码保管提示（中性说明，与上方密码规则提示同区；非警告样式）。
                     刻意**不写**"密码丢失后无法恢复"之类的绝对化文案 —— 应用内提供修改密码，
                     账号问题亦可经"关于"页联系维护者。 -->
                <text class="reg__care">请妥善保管密码。</text>

                <view class="reg__submit">
                    <AppButton
                        label="注册并登录"
                        type="primary"
                        size="l"
                        block
                        :loading="submitting"
                        @tap="handleSubmit"
                    />
                </view>
            </AppCard>

            <view class="reg__bottom">
                <text class="reg__bottom-text">已有账号？</text>
                <view class="reg__bottom-hit" hover-class="reg__bottom-hit--press" @tap="handleGoLogin">
                    <text class="reg__bottom-strong">去登录</text>
                </view>
            </view>
        </view>

        <!-- 用户名冲突（409）→ 引导直接登录（S1-C SC-04 ⑫④） -->
        <AppModal
            v-model:show="showTaken"
            mode="confirm"
            title="该用户名已被注册"
            content="该用户名已被使用，是否直接登录？"
            confirm-text="去登录"
            cancel-text="取消"
            @confirm="handleGoLogin"
        />

        <AppToast />
    </view>
</template>

<script>
import AppCard from '../../components/AppCard.vue'
import AppInput from '../../components/AppInput.vue'
import AppButton from '../../components/AppButton.vue'
import AppModal from '../../components/AppModal.vue'
import AppToast from '../../components/AppToast.vue'
import { useUserStore } from '../../store/user'
import { newIdempotencyKey, errorText, fieldErrorText } from '../../utils/request'
import { isOnline, offlineText } from '../../utils/network'
import { showToast } from '../../utils/toast'
import { checkUsername, checkPassword, checkConfirmPassword } from '../../utils/validate'
import { isAgreementAccepted, getAgreementVersion } from '../../utils/auth'
import { AGREEMENT_VERSION } from '../../utils/config'
import { reLaunch, ROUTES } from '../../utils/route'

export default {
    components: {
        AppCard: AppCard,
        AppInput: AppInput,
        AppButton: AppButton,
        AppModal: AppModal,
        AppToast: AppToast
    },
    data: function () {
        return {
            username: '',
            password: '',
            confirmPassword: '',
            errors: { username: '', password: '', confirm: '' },
            submitting: false,
            showTaken: false
        }
    },
    onLoad: function () {
        const store = useUserStore()
        store.hydrate()

        // 已登录 → 不进重复注册流程
        if (store.isLoggedIn) {
            reLaunch(ROUTES.HOME)
            return
        }
        // F-008：未同意协议不得进入注册（回到 SC-02）
        if (!isAgreementAccepted()) {
            reLaunch(ROUTES.ONBOARDING)
        }
    },
    methods: {
        handleGoLogin: function () {
            // 清栈跳转并携带用户名预填（避免在栈内叠加第二个登录页）
            const target = this.username
                ? ROUTES.LOGIN + '?username=' + encodeURIComponent(this.username.trim())
                : ROUTES.LOGIN
            reLaunch(target)
        },
        /** 清除已填密码（冲突 / 失败分支避免明文长期停留） */
        clearPasswords: function () {
            this.password = ''
            this.confirmPassword = ''
        },
        validate: function () {
            const usernameError = checkUsername(this.username, true)
            const passwordError = checkPassword(this.password, this.username, true)
            const confirmError = checkConfirmPassword(this.password, this.confirmPassword, true)
            this.errors = {
                username: usernameError || '',
                password: passwordError || '',
                confirm: confirmError || ''
            }
            return !(usernameError || passwordError || confirmError)
        },
        handleSubmit: function () {
            if (this.submitting) {
                return
            }
            if (!this.validate()) {
                return
            }
            this.doRegister()
        },
        doRegister: function () {
            const self = this
            isOnline().then(function (online) {
                if (!online) {
                    // 离线：阻止提交 + 保留已填内容
                    showToast('error', offlineText('register'))
                    return
                }
                const store = useUserStore()
                self.submitting = true
                store.register({
                    username: self.username.trim(),
                    password: self.password,
                    agreement_version: getAgreementVersion() || AGREEMENT_VERSION,
                    agreement_accepted: true,
                    auto_login: true
                }, newIdempotencyKey()).then(function () {
                    // 成功后立即清除内存中的明文密码
                    self.password = ''
                    self.confirmPassword = ''
                    self.submitting = false
                    // 成功 → 自动登录 → SC-05 建档引导（不弹"注册成功"）
                    reLaunch(ROUTES.PROFILE_SETUP)
                }, function (err) {
                    self.submitting = false
                    self.handleError(err)
                })
            })
        },
        handleError: function (err) {
            const code = err && err.code ? err.code : ''
            if (code === 'USERNAME_TAKEN') {
                this.clearPasswords()
                this.showTaken = true
                return
            }
            if (code === 'VALIDATION_FAILED') {
                const usernameError = fieldErrorText(err, 'username')
                const passwordError = fieldErrorText(err, 'password')
                const confirmError = fieldErrorText(err, 'confirm_password')
                if (usernameError || passwordError || confirmError) {
                    this.errors = {
                        username: usernameError,
                        password: passwordError,
                        confirm: confirmError
                    }
                    return
                }
                const agreementError = fieldErrorText(err, 'agreement_accepted')
                    || fieldErrorText(err, 'agreement_version')
                if (agreementError) {
                    // 协议未同意（服务端裁决）→ 回到 SC-02 完成协议
                    showToast('error', agreementError)
                    reLaunch(ROUTES.ONBOARDING)
                    return
                }
            }
            showToast('error', errorText(err))
        }
    }
}
</script>

<style scoped lang="scss">
.reg {
    min-height: 100vh;
    background-color: var(--s-page);
}

.reg__status {
    height: var(--status-bar-height);
    width: 100%;
}

.reg__head {
    padding: var(--sp-8) var(--gutter) var(--sp-7) var(--gutter);
    display: flex;
    flex-direction: column;
}

.reg__title {
    font-size: var(--fs-h1);
    line-height: $lh-h1;
    font-weight: $fw-semibold;
    color: var(--t-1);
    letter-spacing: 0;
}

.reg__desc {
    margin-top: var(--sp-3);
    font-size: var(--fs-sub);
    line-height: $lh-sub;
    color: var(--t-2);
    letter-spacing: 0;
}

.reg__form {
    padding: 0 var(--gutter) calc(var(--safe-b) + var(--section-gap)) var(--gutter);
}

.reg__gap {
    height: var(--sp-6);
}

.reg__submit {
    margin-top: var(--sp-7);
}

.reg__bottom {
    margin-top: var(--sp-6);
    display: flex;
    flex-direction: row;
    align-items: center;
    justify-content: center;
}

.reg__bottom-text {
    font-size: var(--fs-sub);
    line-height: $lh-sub;
    color: var(--t-3);
    letter-spacing: 0;
}

.reg__bottom-hit {
    min-height: var(--tap-min);
    padding-left: var(--sp-2);
    padding-right: var(--sp-2);
    display: flex;
    align-items: center;
    transition: transform var(--d-fast) var(--ease-std), opacity var(--d-fast) var(--ease-std);
}

.reg__bottom-hit--press {
    transform: scale(var(--press-scale));
    opacity: var(--press-opacity);
}

.reg__bottom-strong {
    font-size: var(--fs-sub);
    line-height: $lh-sub;
    font-weight: $fw-medium;
    color: var(--t-link);
    letter-spacing: 0;
}

/* ── S4-1：密码保管提示（与密码规则提示同区的中性说明，非警告样式） ── */
.reg__care {
    display: block;
    margin-top: var(--sp-4);
    padding-left: var(--sp-2);
    padding-right: var(--sp-2);
    font-size: var(--fs-caption);
    line-height: $lh-caption;
    color: var(--t-3);
    letter-spacing: 0;
}
</style>
