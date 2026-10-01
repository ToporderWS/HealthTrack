<template>
    <!--
      SC-19 修改密码页（pages/mine/password）
      依据：S1-C §二 SC-19（① 顶部栏「修改密码」/ ② 三密码字段 + 强度提示 / ③ 规则说明 /
            ④ 警示条 / ⑤ 保存按钮）｜DESIGN.md §8（C-03 / C-18）/ §10.3（**A 类系统导航栏**）/
            §11 / §12 / §13 / §14.9

      顶栏：**A 类系统导航栏**（`DESIGN.md §10.3` 的 B 类自绘顶栏清单**不含** SC-19）——
            标题由 `pages.json` 指定，本页**不得**加 `navigationStyle: custom`。

      数据来源：`A-05 PUT /auth/password`（请求体 `old_password` / `new_password` / `confirm_password`）。
        **本页只有这一个请求**，且**没有任何读接口** ⇒ 不存在骨架屏 / 列表加载态。

      状态覆盖（DESIGN.md §13 底线清单，逐项说明）：
        正常   ✅ 三项合法 → 提交 → 成功 → 清栈跳 SC-03；
        空     **N/A**（表单页，未填字段即空输入框 —— S1-C SC-19 ⑩ 明确「不适用」）；
        加载   ✅ **按钮内 loading**（S1-C ⑪：不用骨架屏遮表单，输入内容必须始终可见）；
        失败   ✅ 逐类映射（见下）；未登录 → 路由守卫 → SC-03（S1-C ⑬）；
        离线   ✅ **阻止提交** + 明确提示 + **保留输入**（S1-C ⑭；密码字段按安全策略永不落盘）；
        401    → 由统一请求层处理（单次 Refresh → 重放；失败清栈回 SC-03）；
        高风险确认 ✅ **轻确认**「修改后需重新登录，确认修改？」（S1-C ⑮：原密码 + 新密码本身即强验证，
                 **不追加密码二次验证**）；
        提交防重 ✅ 按钮 `loading` + 确认弹层 `confirm-disabled`（F-083 第一道防线）。

      ⑫ 错误态逐类映射（文案与 `S1-C SC-19 ⑫` 逐条对应）
        ① 原密码错误        → 服务端 `422 PASSWORD_INVALID` ⇒ 字段提示「**原密码不正确**」
        ② 新密码强度不足    → 本地先判（`checkPassword`），服务端 `errors[]` 兜底
        ③ 新密码与原密码相同 → 本地先判 + 服务端 `new_password` 字段明细「新密码不得与原密码相同」
        ④ 两次不一致        → 本地先判（`checkConfirmPassword`）+ 服务端 `confirm_password` 明细
        ⑤ **原密码连续错 5 次 → 中止本次改密流程**：服务端 `429 SESSION_VERIFY_ABORTED`，
           前端只做文案映射「**操作已中止，请重新进入**」，**不本地计数、不锁定账号、
           不计入登录失败计数**（S-9；`backend/app/services/auth_service.py#change_password` 权威）。

      ★ 上线口径（如实登记，逐条给出原因）
        ① 失败时**不清空原密码框**（S1-C ⑯：便于重试），但 `onUnload` 立即释放内存引用；
           **密码明文不进 `uni.setStorageSync`、不进草稿、不进日志**（`DESIGN.md §14.9`）。
        ② ⑤ 中止后：**隐藏保存区**（流程已终止 ⇒ 不再允许本页继续提交）并清空三项输入
           （流程已中止，保留旧输入无意义且增加内存暴露面）；用户按「请重新进入」返回 SC-18 后重进本页
           即得到一条全新会话计数（计数存服务端 `user_session.change_pwd_fail_count`）。
        ③ 成功路径统一走 `store.clearSessionAndCache()`（内部**先** `cancelAllRegistered()`
           再清 9 项 —— I-01），随后清栈 `reLaunch` 到 SC-03 并提示「密码已修改，请重新登录」。
    -->
    <view class="pwd">
        <view class="pwd__body">
            <view class="pwd__inner">
                <!-- 离线标记 / 网络恢复横幅（离线时表单仍可见、输入保留，仅阻止提交） -->
                <view v-if="offline" class="pwd__block">
                    <AppOfflineBar variant="offline" text="当前离线，修改密码需联网后进行" />
                </view>
                <view v-if="restoredVisible" class="pwd__block">
                    <AppOfflineBar variant="restored" text="网络已恢复" />
                </view>

                <!-- ⑫⑤ 中止态（原密码连错 5 次 ⇒ 本次改密流程已终止，需重新进入） -->
                <view v-if="aborted" class="pwd__block">
                    <AppValidateBar :visible="true" level="block" :text="abortText" />
                </view>

                <!-- ② 表单（原密码 / 新密码 + 强度提示 / 确认新密码） -->
                <AppCard class="pwd__block" title="修改密码">
                    <AppInput
                        v-model="form.old_password"
                        label="原密码"
                        placeholder="请输入原密码"
                        :password="true"
                        :maxlength="64"
                        :error="errors.old_password"
                    />
                    <view class="pwd__gap"></view>
                    <AppInput
                        v-model="form.new_password"
                        label="新密码"
                        placeholder="请输入新密码"
                        :password="true"
                        :maxlength="64"
                        :hint="newHint"
                        :error="errors.new_password"
                    />
                    <view class="pwd__gap"></view>
                    <AppInput
                        v-model="form.confirm_password"
                        label="确认新密码"
                        placeholder="请再次输入新密码"
                        :password="true"
                        :maxlength="64"
                        :error="errors.confirm_password"
                    />
                </AppCard>

                <!-- ③ 规则说明（中性技术文案，**不含任何安全评分 / 强度等级**） -->
                <text class="pwd__rule">{{ ruleText }}</text>

                <!-- ④ 警示条（保留 C-18 的中性提示条视觉，文案为后果说明） -->
                <view class="pwd__block">
                    <AppValidateBar :visible="true" level="soft" :text="warnText" />
                </view>
            </view>
        </view>

        <!-- ⑤ 保存（底部固定区，含安全区；中止态不再提供提交入口） -->
        <view v-if="formVisible" class="pwd__bar">
            <AppButton
                label="保存"
                type="primary"
                size="l"
                block
                :loading="submitting"
                @tap="onSubmit"
            />
        </view>

        <!-- ⑮ 轻确认（原密码 + 新密码即强验证，**不追加密码二次验证**） -->
        <AppModal
            :show="confirmVisible"
            mode="confirm"
            title="确认修改"
            :content="confirmText"
            confirm-text="确认修改"
            cancel-text="取消"
            :confirm-disabled="submitting"
            @update:show="onConfirmShow"
            @confirm="doSubmit"
            @cancel="onConfirmCancel"
        />

        <!-- 轻提示宿主 -->
        <AppToast />

        <!-- 开发环境页面预览器（仅 H5 非生产环境渲染；生产构建下为空节点） -->
        <DevPagePreviewer />
    </view>
</template>

<script>
import AppCard from '../../components/AppCard.vue'
import AppInput from '../../components/AppInput.vue'
import AppButton from '../../components/AppButton.vue'
import AppValidateBar from '../../components/AppValidateBar.vue'
import AppOfflineBar from '../../components/AppOfflineBar.vue'
import AppModal from '../../components/AppModal.vue'
import AppToast from '../../components/AppToast.vue'
import DevPagePreviewer from '../../components/DevPagePreviewer.vue'

import { ROUTES, reLaunch, requireLogin } from '../../utils/route'
import { useUserStore } from '../../store/user'
import { changePassword } from '../../api/auth'
import { errorText, fieldErrorText } from '../../utils/request'
import { isOnline, offlineText } from '../../utils/network'
import { showToast } from '../../utils/toast'
import { NETWORK_BANNER_MS } from '../../utils/config'
import { checkPassword, checkConfirmPassword } from '../../utils/validate'

/** ③ 规则说明（S1-C SC-19 ③ 逐字） */
const RULE_TEXT = '至少 8 位，且需同时包含字母和数字；新密码不得与原密码相同'

/** ④ 警示条（S1-C SC-19 ④ 逐字） */
const WARN_TEXT = '修改成功后需重新登录，其他设备也会退出登录'

/** ② 新密码强度提示（中性技术文案；**不出现"弱/中/强"评级**） */
const NEW_HINT = '至少 8 位，且需同时包含字母和数字'

/** ⑫⑤ 中止文案（S1-C SC-19 ⑫⑤ 逐字） */
const ABORT_TEXT = '操作已中止，请重新进入'

/** ⑮ 轻确认文案（S1-C SC-19 ⑮ 逐字） */
const CONFIRM_TEXT = '修改后需重新登录，确认修改？'

/** ⑯ 成功提示（服务端 A-05 的成功 message 逐字，也是 S1-C SC-19 ⑯ 规定文案） */
const TOAST_OK = '密码已修改，请重新登录'

/** 字段级提示（本地预判；**服务端裁决为唯一权威**） */
const OLD_REQUIRED = '请输入原密码'
const NEW_REQUIRED = '请输入新密码'
const SAME_AS_OLD = '新密码不得与原密码相同'

/** 去首尾空格（与服务端 `normalize_password` 同口径） */
function trimText(value) {
    if (value === null || value === undefined) {
        return ''
    }
    return String(value).replace(/^\s+|\s+$/g, '')
}

export default {
    components: {
        AppCard: AppCard,
        AppInput: AppInput,
        AppButton: AppButton,
        AppValidateBar: AppValidateBar,
        AppOfflineBar: AppOfflineBar,
        AppModal: AppModal,
        AppToast: AppToast,
        DevPagePreviewer: DevPagePreviewer
    },
    data: function () {
        return {
            ruleText: RULE_TEXT,
            warnText: WARN_TEXT,
            newHint: NEW_HINT,
            abortText: ABORT_TEXT,
            confirmText: CONFIRM_TEXT,

            /** 表单（**仅内存**；离开页面即释放，绝不落盘 —— DESIGN.md §14.9） */
            form: {
                old_password: '',
                new_password: '',
                confirm_password: ''
            },
            errors: {
                old_password: '',
                new_password: '',
                confirm_password: ''
            },

            /* ── 提交 ── */
            submitting: false,
            confirmVisible: false,
            /** ⑫⑤ 本次改密流程是否已被服务端中止（429 SESSION_VERIFY_ABORTED） */
            aborted: false,

            /* ── 网络 ── */
            offline: false,
            restoredVisible: false,
            bannerTimer: null,
            networkHandler: null
        }
    },
    computed: {
        /** 表单与保存区是否可见（中止态不再提供提交入口 —— 流程已终止） */
        formVisible: function () {
            return !this.aborted
        }
    },
    onLoad: function () {
        // 未登录守卫（S1-C SC-19 ⑬：需登录）
        if (!requireLogin()) {
            return
        }

        // 网络恢复 → 撤下离线标记（**不自动重放提交** —— S1-D §5）
        const self = this
        this.networkHandler = function (res) {
            self.handleNetworkChange(res)
        }
        uni.onNetworkStatusChange(this.networkHandler)
    },
    onUnload: function () {
        this.clearBanner()
        if (this.networkHandler) {
            uni.offNetworkStatusChange(this.networkHandler)
            this.networkHandler = null
        }
        // 离开即清空内存中的密码明文（**不落草稿、不落缓存、不落日志**）
        // ★ 不置 this.form = null：模板 v-model 仍依赖 form.* 字段，卸载期置 null
        //   会触发重渲染并读取 null.old_password ⇒ TypeError（D-3.2-01）
        this.form.old_password = ''
        this.form.new_password = ''
        this.form.confirm_password = ''
    },
    onHide: function () {
        // 空实现：本页无后台任务、无计时型业务
    },
    methods: {
        /* ───────────── 校验 ───────────── */

        /**
         * 本地字段级校验（服务端为唯一权威；此处只做即时提示，减少无效请求）。
         * 组合顺序与 S1-C SC-19 ⑫ 的 ①②③④ 一致：先原密码 → 新密码 → 与原密码不同 → 两次一致。
         */
        validate: function () {
            const errors = { old_password: '', new_password: '', confirm_password: '' }
            const oldPassword = trimText(this.form.old_password)
            const newPassword = trimText(this.form.new_password)

            if (!oldPassword) {
                errors.old_password = OLD_REQUIRED
            }

            if (!newPassword) {
                errors.new_password = NEW_REQUIRED
            } else {
                errors.new_password = checkPassword(this.form.new_password, '', true) || ''
            }

            // ③ 新密码不得与原密码相同（S1-C SC-19 ⑫③；服务端同判 `new_password == old_password`）
            if (!errors.new_password && oldPassword && newPassword === oldPassword) {
                errors.new_password = SAME_AS_OLD
            }

            errors.confirm_password = checkConfirmPassword(
                this.form.new_password, this.form.confirm_password, true
            ) || ''

            this.errors = errors
            return !(errors.old_password || errors.new_password || errors.confirm_password)
        },

        /* ───────────── 提交 ───────────── */

        /** 保存入口：先本地校验 → 再判网络（⑭ 无网阻止提交 + 保留输入）→ 轻确认 */
        onSubmit: function () {
            if (this.submitting || this.aborted) {
                return
            }
            if (!this.validate()) {
                showToast('error', '请检查填写内容')
                return
            }
            const self = this
            isOnline().then(function (online) {
                if (!online) {
                    self.offline = true
                    showToast('info', offlineText('save'))
                    return
                }
                self.offline = false
                self.confirmVisible = true
            })
        },

        onConfirmShow: function (value) {
            if (!value && !this.submitting) {
                this.confirmVisible = false
            }
        },

        onConfirmCancel: function () {
            if (this.submitting) {
                return
            }
            this.confirmVisible = false
        },

        /**
         * 提交 `A-05`（请求体三字段与服务端 `ChangePasswordSchema` 逐字对齐）。
         * ★ 成功后服务端**立即失效全部旧 Token（含本机）** ⇒ 必须清态 + 清栈跳 SC-03，
         *   不得停留在本页继续请求。
         */
        doSubmit: function () {
            if (this.submitting || this.aborted) {
                return
            }
            const self = this
            this.submitting = true
            changePassword({
                old_password: trimText(this.form.old_password),
                new_password: trimText(this.form.new_password),
                confirm_password: trimText(this.form.confirm_password)
            }).then(function () {
                self.submitting = false
                self.confirmVisible = false
                self.clearForm()
                // 清态统一走 store（内部先取消已注册系统通知再清 9 项 —— I-01）
                useUserStore().clearSessionAndCache()
                showToast('success', TOAST_OK)
                reLaunch(ROUTES.LOGIN)
            }, function (err) {
                self.submitting = false
                self.confirmVisible = false
                self.handleSubmitError(err)
            })
        },

        /**
         * ⑫ 失败映射（**保留输入、不清空原密码框** —— S1-C SC-19 ⑯）。
         * 服务端裁决为唯一权威；本地只做文案归属，不改变任何业务判定。
         */
        handleSubmitError: function (err) {
            const code = err && err.code ? err.code : ''
            const status = err && err.httpStatus ? err.httpStatus : 0

            // ⑫⑤ 原密码连续错 5 次 → 服务端 429 中止本次改密流程（不锁定账号、不计入登录失败计数）
            if (code === 'SESSION_VERIFY_ABORTED' || status === 429) {
                this.aborted = true
                this.clearForm()
                return
            }

            // ⑫① 原密码错误 → 服务端 422 PASSWORD_INVALID
            if (code === 'PASSWORD_INVALID') {
                this.errors.old_password = '原密码不正确'
                showToast('error', '原密码不正确')
                return
            }

            // ⑫②③④ 服务端字段级明细（`errors[]`）→ 回填到对应输入框（文案取自服务端，不自行改写）
            const oldError = fieldErrorText(err, 'old_password')
            const newError = fieldErrorText(err, 'new_password')
            const confirmError = fieldErrorText(err, 'confirm_password')
            if (oldError || newError || confirmError) {
                if (oldError) {
                    this.errors.old_password = oldError
                }
                if (newError) {
                    this.errors.new_password = newError
                }
                if (confirmError) {
                    this.errors.confirm_password = confirmError
                }
                showToast('error', '请检查填写内容')
                return
            }

            // 其余（5xx / 网络等）→ 统一请求层的中性文案 + 保留输入
            showToast('error', errorText(err))
        },

        /** 清空三项输入（仅内存操作；成功 / 中止后调用，避免密码在内存中久留） */
        clearForm: function () {
            this.form = {
                old_password: '',
                new_password: '',
                confirm_password: ''
            }
            this.errors = {
                old_password: '',
                new_password: '',
                confirm_password: ''
            }
        },

        /* ───────────── 网络状态 ───────────── */

        handleNetworkChange: function (res) {
            const online = !!(res && res.isConnected)
            if (!online) {
                this.offline = true
                return
            }
            if (!this.offline) {
                return
            }
            this.offline = false
            this.showRestoredBanner()
        },

        showRestoredBanner: function () {
            const self = this
            this.clearBanner()
            this.restoredVisible = true
            this.bannerTimer = setTimeout(function () {
                self.restoredVisible = false
                self.bannerTimer = null
            }, NETWORK_BANNER_MS)
        },

        clearBanner: function () {
            if (this.bannerTimer) {
                clearTimeout(this.bannerTimer)
                this.bannerTimer = null
            }
        }
    }
}
</script>

<style scoped lang="scss">
.pwd {
    min-height: 100vh;
    background-color: var(--s-page);
}

/* A 类系统导航栏占位由平台负责；底部预留固定保存区 */
.pwd__body {
    padding-top: var(--page-pad-t);
    padding-bottom: calc(var(--safe-b) + var(--sp-10) * 3);
}

.pwd__inner {
    max-width: var(--content-max);
    margin-left: auto;
    margin-right: auto;
    padding-left: var(--gutter);
    padding-right: var(--gutter);
}

.pwd__block {
    margin-bottom: var(--card-gap);
}

.pwd__gap {
    height: var(--sp-6);
}

/* ── ③ 规则说明（表单下方说明句，不是卡片内容） ── */
.pwd__rule {
    display: block;
    margin-bottom: var(--card-gap);
    padding-left: var(--sp-2);
    padding-right: var(--sp-2);
    font-size: var(--fs-caption);
    line-height: $lh-caption;
    color: var(--t-3);
    letter-spacing: 0;
}

/* ── ⑤ 底部固定保存区（含安全区） ── */
.pwd__bar {
    position: fixed;
    left: 0;
    right: 0;
    bottom: 0;
    z-index: 30;
    padding: var(--sp-5) var(--gutter) calc(var(--safe-b) + var(--sp-5)) var(--gutter);
    background-color: var(--s-card);
    border-top: 1rpx solid var(--b-line);
}
</style>
