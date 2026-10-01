<template>
    <!--
      SC-03 登录页（pages/auth/login）
      依据：S1-C §二 SC-03 ｜ DESIGN.md §11 / §13
      · ① 顶部 App 名 + slogan（名称暂定标注） ② 用户名 + 密码（眼睛切换显隐）
        ③ 辅助行「忘记密码？」 ④ 主按钮「登录」（防重复） ⑤ 底部「还没有账号？立即注册」
      · 认证：**仅用户名 + 密码**（不提供邮箱 / 手机号 / 第三方登录）
      · 安全：失败**统一文案**（不区分账号不存在与密码错误，防枚举）；**不缓存明文密码**
      · 状态覆盖：正常 / 首次使用(N/A：表单页恒可用) / loading（按钮内） / 失败（Toast）
        / 离线（阻止提交 + 保留输入） / 未登录（本页即未登录页）/ 表单校验失败 / 提交防重复
        / 401（登录接口本身返回 401 凭据错误） / 会话失效（由统一请求层处理）

      ★ B4-2 第二批（2026-09-29）：新增页内展示态 mode: login | forgot。
        forgot ⇒ 渲染 PasswordResetPanel（忘记密码自助找回；7 主态 + 11 异常态），
        登录表单**同页隐藏**。**不新增页面、不新增路由**（25 页冻结口径不变）。
        出口：@back-login（仅回填用户名，密码框置空）/ @contact → SC-25 关于页。
        旧「暂不支持自助找回」说明弹窗已移除（其兜底语义由面板 STEP-2 常驻联系入口承载）。
    -->
    <view class="login">
        <view class="login__status"></view>

        <view class="login__head">
            <view class="login__mark">
                <view class="mark__bar mark__bar--1"></view>
                <view class="mark__bar mark__bar--2"></view>
                <view class="mark__bar mark__bar--3"></view>
            </view>
            <text class="login__name">康迹 HealthTrack</text>
            <text class="login__slogan">记录每一天，看见自己的变化</text>
            <text class="login__tentative">产品名称暂定</text>
        </view>

        <view v-if="mode === 'login'" class="login__form">
            <AppCard>
                <AppInput
                    v-model="username"
                    label="用户名"
                    placeholder="请输入用户名"
                    :maxlength="20"
                    clearable
                    :error="errors.username"
                    @confirm="handleSubmit"
                />

                <view class="login__gap"></view>

                <AppInput
                    v-model="password"
                    label="密码"
                    placeholder="请输入密码"
                    password
                    :maxlength="64"
                    :error="errors.password"
                    @confirm="handleSubmit"
                />

                <view class="login__aux">
                    <view class="login__aux-hit" hover-class="login__aux-hit--press" @tap="openForgot">
                        <text class="login__aux-text">忘记密码？</text>
                    </view>
                </view>

                <view class="login__submit">
                    <AppButton label="登录" type="primary" size="l" block :loading="submitting" @tap="handleSubmit" />
                </view>
            </AppCard>

            <view class="login__bottom">
                <text class="login__bottom-text">还没有账号？</text>
                <view class="login__bottom-hit" hover-class="login__bottom-hit--press" @tap="handleGoRegister">
                    <text class="login__bottom-strong">立即注册</text>
                </view>
            </view>
        </view>

        <view v-else class="login__panel">
            <!-- B4-2 第二批：忘记密码自助找回（**页内分步态**；不新增页面、不新增路由） -->
            <PasswordResetPanel
                :initial-username="username"
                @back-login="onBackLogin"
                @contact="openContact"
            />
        </view>

        <AppToast />
    </view>
</template>

<script>
import AppCard from '../../components/AppCard.vue'
import AppInput from '../../components/AppInput.vue'
import AppButton from '../../components/AppButton.vue'
import AppToast from '../../components/AppToast.vue'
import PasswordResetPanel from '../../components/PasswordResetPanel.vue'
import { useUserStore } from '../../store/user'
import { newIdempotencyKey, errorText, fieldErrorText } from '../../utils/request'
import { isOnline, offlineText } from '../../utils/network'
import { showToast } from '../../utils/toast'
import { resolveAfterAuth, reLaunch, leaveIfLoggedIn, ROUTES } from '../../utils/route'

export default {
    components: {
        AppCard: AppCard,
        AppInput: AppInput,
        AppButton: AppButton,
        AppToast: AppToast,
        PasswordResetPanel: PasswordResetPanel
    },
    data: function () {
        return {
            username: '',
            password: '',
            errors: { username: '', password: '' },
            submitting: false,
            /**
             * 页内展示态：'login' 正常登录表单 ｜ 'forgot' 忘记密码自助找回面板。
             * ★ 两者**同页切换**（不新增页面、不新增路由；25 页冻结口径不变）。
             */
            mode: 'login'
        }
    },
    onLoad: function (options) {
        const store = useUserStore()
        store.hydrate()

        // 已登录访问登录页 → 不进重复登录流程（S1-C / 用户要求）
        if (leaveIfLoggedIn()) {
            return
        }
        // 从注册页"用户名冲突 → 去登录"带参预填
        if (options && options.username) {
            try {
                this.username = decodeURIComponent(options.username)
            } catch (e) {
                this.username = String(options.username)
            }
        }
    },
    onShow: function () {
        // 返回本页时（如表单从注册页退回）再次确认登录态
        if (this.submitting) {
            return
        }
        leaveIfLoggedIn()
    },
    methods: {
        /**
         * 进入忘记密码自助找回（**页内切换**，不跳新页面）。
         * 同时清空登录密码内存：切换到 PASSWORD_RESET 后登录表单被隐藏，返回登录时密码框必须为空
         * （冻结 STEP-7 口径）；登录密码**绝不**传入面板、不进 storage / URL / 日志。
         */
        openForgot: function () {
            this.password = ''
            this.errors = { username: '', password: '' }
            this.mode = 'forgot'
        },
        /**
         * 「联系维护者」→ SC-25 关于页（未登录可达；不发起任何网络请求）。
         * 入口 = 面板 STEP-2 常驻次级入口（@contact）。B4-2 第二批起旧忘密说明弹窗已移除，
         * 本方法**只做跳转**（面板自身不跳转，出口一律走 emit；联系方式由 SC-25 单一渲染）。
         */
        openContact: function () {
            uni.navigateTo({ url: ROUTES.ABOUT })
        },

        /**
         * 面板出口（STEP-6 / STEP-7）：回到登录表单。
         * 只接收面板给出的**用户名**（便于回填）；**绝不**接收密码 / 验证码 / reset_token / 新密码
         * —— 面板负责自身 clearSensitive()，本页不做任何敏感值回填。
         * @param {string} payload 面板回传的用户名（可为空串）
         */
        onBackLogin: function (payload) {
            const name = payload === null || payload === undefined ? '' : String(payload).trim()
            if (name) {
                this.username = name
            }
            this.password = ''
            this.errors = { username: '', password: '' }
            this.mode = 'login'
        },
        handleGoRegister: function () {
            // SC-04 注册页（可返回本页）
            uni.navigateTo({ url: ROUTES.REGISTER })
        },
        handleSubmit: function () {
            if (this.submitting) {
                return
            }
            // 登录只校验"是否填写"：格式与强度以服务端裁决为唯一权威
            const usernameError = this.username.trim() ? '' : '请输入用户名'
            const passwordError = this.password ? '' : '请输入密码'
            this.errors = { username: usernameError, password: passwordError }
            if (usernameError || passwordError) {
                return
            }
            this.doLogin()
        },
        doLogin: function () {
            const self = this
            isOnline().then(function (online) {
                if (!online) {
                    // 离线：阻止提交，保留已输入内容（密码保持掩码）
                    showToast('error', offlineText('login'))
                    return
                }
                const store = useUserStore()
                self.submitting = true
                store.login({
                    username: self.username.trim(),
                    password: self.password
                }, newIdempotencyKey()).then(function (res) {
                    // 成功后立即从内存中清除明文密码（不做任何本地缓存）
                    self.password = ''
                    self.submitting = false
                    const data = res.data || {}
                    // 成功 → 已建档 SC-06 / 未建档 SC-05（S1-C SC-03 ⑦）；不弹成功 Toast
                    reLaunch(resolveAfterAuth(data.profile_initialized))
                }, function (err) {
                    self.submitting = false
                    self.handleError(err)
                })
            })
        },
        handleError: function (err) {
            const code = err && err.code ? err.code : ''
            if (code === 'CREDENTIALS_INVALID') {
                // 统一文案：不区分"账号不存在"与"密码错误"
                showToast('error', err.message)
                return
            }
            if (code === 'ACCOUNT_LOCKED') {
                // 锁定文案由服务端给出剩余分钟数；不得反推账号是否存在
                showToast('error', err.message)
                return
            }
            if (code === 'VALIDATION_FAILED') {
                const usernameError = fieldErrorText(err, 'username')
                const passwordError = fieldErrorText(err, 'password')
                if (usernameError || passwordError) {
                    this.errors = { username: usernameError, password: passwordError }
                    return
                }
            }
            showToast('error', errorText(err))
        }
    }
}
</script>

<style scoped lang="scss">
.login {
    min-height: 100vh;
    background-color: var(--s-page);
}

.login__status {
    height: var(--status-bar-height);
    width: 100%;
}

.login__head {
    display: flex;
    flex-direction: column;
    align-items: center;
    padding-top: var(--sp-10);
    padding-bottom: var(--sp-9);
}

.login__mark {
    width: 104rpx;
    height: 104rpx;
    border-radius: var(--r-lg);
    background-color: var(--c-p-600);
    display: flex;
    flex-direction: row;
    align-items: flex-end;
    justify-content: center;
    padding-bottom: var(--sp-5);
    box-shadow: var(--el-1);
}

.mark__bar {
    width: 12rpx;
    border-radius: var(--r-full);
    background-color: var(--t-inverse);
    margin-left: var(--sp-1);
    margin-right: var(--sp-1);
}

.mark__bar--1 {
    height: 18rpx;
}

.mark__bar--2 {
    height: 34rpx;
}

.mark__bar--3 {
    height: 52rpx;
}

.login__name {
    margin-top: var(--sp-7);
    font-size: var(--fs-h2);
    line-height: $lh-h2;
    font-weight: $fw-semibold;
    color: var(--t-1);
    letter-spacing: 0;
}

.login__slogan {
    margin-top: var(--sp-3);
    font-size: var(--fs-sub);
    line-height: $lh-sub;
    color: var(--t-2);
    letter-spacing: 0;
}

.login__tentative {
    margin-top: var(--sp-2);
    font-size: var(--fs-micro);
    line-height: $lh-micro;
    color: var(--t-4);
    letter-spacing: 0;
}

.login__form {
    padding: 0 var(--gutter) calc(var(--safe-b) + var(--section-gap)) var(--gutter);
}

.login__gap {
    height: var(--sp-6);
}

.login__aux {
    display: flex;
    flex-direction: row;
    justify-content: flex-end;
    margin-top: var(--sp-2);
}

.login__aux-hit {
    min-height: var(--tap-min);
    padding-left: var(--sp-4);
    display: flex;
    align-items: center;
    transition: transform var(--d-fast) var(--ease-std), opacity var(--d-fast) var(--ease-std);
}

.login__aux-hit--press {
    transform: scale(var(--press-scale));
    opacity: var(--press-opacity);
}

.login__aux-text {
    font-size: var(--fs-caption);
    line-height: $lh-caption;
    color: var(--t-link);
    letter-spacing: 0;
}

.login__submit {
    margin-top: var(--sp-6);
}

.login__bottom {
    margin-top: var(--sp-7);
    display: flex;
    flex-direction: row;
    align-items: center;
    justify-content: center;
}

.login__bottom-text {
    font-size: var(--fs-sub);
    line-height: $lh-sub;
    color: var(--t-3);
    letter-spacing: 0;
}

.login__bottom-hit {
    min-height: var(--tap-min);
    padding-left: var(--sp-2);
    padding-right: var(--sp-2);
    display: flex;
    align-items: center;
    transition: transform var(--d-fast) var(--ease-std), opacity var(--d-fast) var(--ease-std);
}

.login__bottom-hit--press {
    transform: scale(var(--press-scale));
    opacity: var(--press-opacity);
}

.login__bottom-strong {
    font-size: var(--fs-sub);
    line-height: $lh-sub;
    font-weight: $fw-medium;
    color: var(--t-link);
    letter-spacing: 0;
}

/* B4-2 第二批：PASSWORD_RESET 面板容器 —— 与登录表单同一栅格
   （左右 gutter + 底部安全区 + 区块间距），面板内部自带 AppCard，本页不重复包壳。 */
.login__panel {
    padding: 0 var(--gutter) calc(var(--safe-b) + var(--section-gap)) var(--gutter);
}
</style>
