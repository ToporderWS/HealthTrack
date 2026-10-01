<template>
    <!--
      SC-05 建档引导页（pages/onboarding/profile-setup）
      依据：S1-C §二 SC-05 ｜ DESIGN.md §11 / §12 / §13
      · 4 步向导：① 昵称（必填）② 性别 + 出生日期（必填）③ 身高 + 当前体重（必填）④ 目标（可跳过）
      · 提交：`P-02` 更新档案（整体替换）；第 4 步 → `G-02` 创建目标（可跳过）
      · **不建立第二套"目标体重"数据源**：目标体重只经 `POST /goals` 写入（D-1）
      · **不显示医学正常值 / 参考范围 / 风险等级**；数值越界只提示「数值超出常见范围，请确认是否输错」
      · 草稿：离开页面 / 切换步骤即写本地草稿（≤7 天），再次进入静默续填；**绝不自动提交**
      · 状态覆盖：正常 / 加载中（骨架屏）/ 加载失败（可重试，表单仍可用）/ 未登录（守卫 → SC-03）
        / 离线（可填写、提交时阻止 + 明确提示）/ 必填校验失败 / 数值越界（软提示可保存 / 硬拦截阻止保存）
        / 提交防重复 / 失败保留已填内容 / 建档成功 → SC-06
    -->
    <view class="setup">
        <AppNavBar title="完善健康档案" :show-back="step > 1" @back="handlePrevStep" />

        <view class="setup__body">
            <!-- 进度指示 -->
            <view class="setup__progress">
                <view class="setup__progress-track">
                    <view class="setup__progress-fill" :style="{ width: progressPercent }"></view>
                </view>
                <text class="setup__progress-text">第 {{ step }} / 4 步</text>
            </view>

            <!-- 档案读取失败：局部失败只失败局部（表单继续可用） -->
            <view v-if="loadFailed" class="setup__error">
                <AppErrorState
                    variant="inline"
                    text="档案信息加载失败，你可以直接填写"
                    retry-text="重试"
                    @retry="loadProfile"
                />
            </view>

            <!-- 加载中：骨架屏（禁整页白屏） -->
            <AppCard v-if="loadingProfile" class="setup__card">
                <AppSkeleton variant="profile" />
            </AppCard>

            <template v-else>
                <!-- 第 1 步：昵称 -->
                <AppCard v-if="step === 1" class="setup__card">
                    <AppInput
                        v-model="form.nickname"
                        label="昵称"
                        placeholder="请输入昵称"
                        hint="不超过 20 个字"
                        :maxlength="20"
                        clearable
                        required
                        :error="errors.nickname"
                        @confirm="handleNextStep"
                    />
                </AppCard>

                <!-- 第 2 步：性别 + 出生日期 -->
                <AppCard v-else-if="step === 2" class="setup__card">
                    <AppSelect
                        v-model="form.gender"
                        label="性别"
                        title="请选择性别"
                        placeholder="请选择"
                        :options="genderOptions"
                        required
                        :error="errors.gender"
                    />
                    <view class="setup__gap"></view>
                    <AppDatePicker
                        v-model="form.birth_date"
                        mode="date"
                        label="出生日期"
                        placeholder="请选择出生日期"
                        :end="today"
                        start="1900-01-01"
                        required
                        :error="errors.birth_date"
                    />
                </AppCard>

                <!-- 第 3 步：身高 + 当前体重 -->
                <AppCard v-else-if="step === 3" class="setup__card">
                    <AppInput
                        v-model="form.height_cm"
                        label="身高"
                        placeholder="请输入身高"
                        unit="cm"
                        type="digit"
                        :maxlength="6"
                        required
                        :error="errors.height_cm"
                    />
                    <view class="setup__gap"></view>
                    <AppInput
                        v-model="form.initial_weight_kg"
                        label="当前体重"
                        placeholder="请输入当前体重"
                        unit="kg"
                        type="digit"
                        :maxlength="6"
                        required
                        :error="errors.initial_weight_kg"
                    />
                    <view v-if="warnLevel" class="setup__warn">
                        <AppValidateBar :visible="true" :level="warnLevel" />
                    </view>
                </AppCard>

                <!-- 第 4 步：目标（可跳过） -->
                <AppCard v-else class="setup__card" title="设置一个目标（可跳过）">
                    <AppInput
                        v-model="goals.weight"
                        label="目标体重"
                        placeholder="选填"
                        unit="kg"
                        type="digit"
                        :maxlength="6"
                        :error="goalErrors.weight"
                    />
                    <view class="setup__gap"></view>
                    <AppInput
                        v-model="goals.water"
                        label="每日饮水"
                        placeholder="选填"
                        unit="ml"
                        type="number"
                        :maxlength="6"
                        :error="goalErrors.water"
                    />
                    <view class="setup__gap"></view>
                    <AppInput
                        v-model="goals.sport"
                        label="每周运动"
                        placeholder="选填"
                        unit="min"
                        type="number"
                        :maxlength="7"
                        :error="goalErrors.sport"
                    />
                    <view class="setup__gap"></view>
                    <AppInput
                        v-model="goals.sleep"
                        label="每日睡眠"
                        placeholder="选填"
                        unit="hour"
                        type="digit"
                        :maxlength="5"
                        :error="goalErrors.sleep"
                    />
                    <view v-if="warnLevel" class="setup__warn">
                        <AppValidateBar :visible="true" :level="warnLevel" />
                    </view>
                    <text class="setup__tip">目标只用于展示你自己的进度，不作为任何建议或评价。</text>
                </AppCard>
            </template>
        </view>

        <!-- 底部操作区（含安全区） -->
        <view class="setup__foot">
            <view v-if="step > 1" class="setup__foot-prev">
                <AppButton label="上一步" type="secondary" size="l" block :disabled="submitting" @tap="handlePrevStep" />
            </view>
            <view class="setup__foot-main">
                <AppButton
                    :label="primaryLabel"
                    type="primary"
                    size="l"
                    block
                    :loading="submitting"
                    :disabled="warnLevel === 'block'"
                    @tap="handlePrimary"
                />
            </view>
            <view v-if="step === 4" class="setup__foot-skip" hover-class="setup__foot-skip--press" @tap="handleSkipGoals">
                <text class="setup__foot-skip-text">稍后补充</text>
            </view>
        </view>

        <AppToast />
    </view>
</template>

<script>
import AppNavBar from '../../components/AppNavBar.vue'
import AppCard from '../../components/AppCard.vue'
import AppInput from '../../components/AppInput.vue'
import AppSelect from '../../components/AppSelect.vue'
import AppDatePicker from '../../components/AppDatePicker.vue'
import AppButton from '../../components/AppButton.vue'
import AppSkeleton from '../../components/AppSkeleton.vue'
import AppErrorState from '../../components/AppErrorState.vue'
import AppValidateBar from '../../components/AppValidateBar.vue'
import AppToast from '../../components/AppToast.vue'
import { useUserStore } from '../../store/user'
import { getProfile, updateProfile } from '../../api/profile'
import { createGoal } from '../../api/goals'
import { errorText, fieldErrorText } from '../../utils/request'
import { isOnline, offlineText } from '../../utils/network'
import { showToast } from '../../utils/toast'
import {
    checkNickname, checkBirthDate, toNumber, inRange, tooManyDecimals, todayString, RANGE_TEXT
} from '../../utils/validate'
import { readJson, writeJson, removeRaw, KEYS } from '../../utils/storage'
import { DRAFT_TTL_MS } from '../../utils/config'
import { requireLogin, reLaunch, ROUTES } from '../../utils/route'

/**
 * 「录入合理性区间」——仅用于识别异常输入，**不是医学参考范围**，且**不回显边界值**。
 * 来源：S1-B §六 P-02（身高 50–250 / 体重 20–300）与 G-02 硬·软区间（后端 `goal_service.py`）。
 */
const SOFT = {
    height: { min: 50, max: 250 },
    weight: { min: 20, max: 300 },
    goalWeight: { min: 20, max: 300 },
    water: { min: 100, max: 5000 },
    sport: { min: 1, max: 600 },
    sleep: { min: 1, max: 16 }
}

/** 硬拦截区间（仅"不可能值"，越界即阻止保存） */
const HARD = {
    goalWeight: { minExclusive: 0, max: 500 },
    water: { minExclusive: 0, max: 20000 },
    sport: { minExclusive: 0, max: 10080 },
    sleep: { minExclusive: 0, max: 24 }
}

export default {
    components: {
        AppNavBar: AppNavBar,
        AppCard: AppCard,
        AppInput: AppInput,
        AppSelect: AppSelect,
        AppDatePicker: AppDatePicker,
        AppButton: AppButton,
        AppSkeleton: AppSkeleton,
        AppErrorState: AppErrorState,
        AppValidateBar: AppValidateBar,
        AppToast: AppToast
    },
    data: function () {
        return {
            step: 1,
            today: todayString(),
            genderOptions: [
                { value: 1, label: '男' },
                { value: 2, label: '女' }
            ],
            form: {
                nickname: '',
                gender: '',
                birth_date: '',
                height_cm: '',
                initial_weight_kg: ''
            },
            goals: {
                weight: '',
                water: '',
                sport: '',
                sleep: ''
            },
            errors: { nickname: '', gender: '', birth_date: '', height_cm: '', initial_weight_kg: '' },
            goalErrors: { weight: '', water: '', sport: '', sleep: '' },
            loadingProfile: false,
            loadFailed: false,
            submitting: false,
            /** 服务端软提示回退（客户端预判之外的边界情况） */
            serverSoftText: '',
            /** 是否已在服务端软提示后确认过一次 */
            serverSoftAcknowledged: false
        }
    },
    computed: {
        progressPercent: function () {
            return String(Math.round((this.step / 4) * 100)) + '%'
        },
        primaryLabel: function () {
            if (this.step < 4) {
                return '下一步'
            }
            if (this.serverSoftText && !this.serverSoftAcknowledged) {
                return '确认并保存'
            }
            return '完成'
        },
        hasHardViolation: function () {
            return this.hardFields().length > 0
        },
        hasSoftViolation: function () {
            return this.softFields().length > 0
        },
        warnLevel: function () {
            if (this.hasHardViolation) {
                return 'block'
            }
            if (this.hasSoftViolation) {
                return 'soft'
            }
            return ''
        }
    },
    onLoad: function () {
        const store = useUserStore()
        store.hydrate()
        // 需登录（未登录 → 守卫跳 SC-03）
        if (!requireLogin()) {
            return
        }
        const restored = this.restoreDraft()
        this.loadProfile(restored)
    },
    onHide: function () {
        // 中途离开（切后台 / 跳走）→ 落草稿，绝不自动提交
        this.saveDraft()
    },
    onUnload: function () {
        // 页面销毁时清空内存中的敏感输入（对应"清空内存中的敏感引用"口径）
        // ★ 不置 this.form / this.goals = null：模板 v-model 仍依赖其字段，卸载期
        //   置 null 会触发重渲染并读取 null.nickname / null.weight ⇒ TypeError（D-3.2-01）
        this.form.nickname = ''
        this.form.gender = ''
        this.form.birth_date = ''
        this.form.height_cm = ''
        this.form.initial_weight_kg = ''
        this.goals.weight = ''
        this.goals.water = ''
        this.goals.sport = ''
        this.goals.sleep = ''
    },
    methods: {
        /* ───────────── 档案加载与草稿 ───────────── */

        loadProfile: function (draftRestored) {
            const self = this
            this.loadFailed = false
            this.loadingProfile = true
            getProfile().then(function (res) {
                self.loadingProfile = false
                if (draftRestored) {
                    // 草稿优先：用户未完成的输入不应被服务端旧值覆盖
                    return
                }
                const profile = (res.data && res.data.profile) || {}
                self.applyProfile(profile)
            }, function () {
                self.loadingProfile = false
                // 局部失败只失败局部：表单继续可用（可直接新建档案）
                self.loadFailed = true
            })
        },
        applyProfile: function (profile) {
            if (!profile) {
                return
            }
            this.form.nickname = profile.nickname ? String(profile.nickname) : this.form.nickname
            this.form.gender = profile.gender === 0 || profile.gender === null || profile.gender === undefined
                ? this.form.gender
                : profile.gender
            this.form.birth_date = profile.birth_date ? String(profile.birth_date) : this.form.birth_date
            this.form.height_cm = profile.height_cm === null || profile.height_cm === undefined
                ? this.form.height_cm
                : String(profile.height_cm)
            this.form.initial_weight_kg = profile.initial_weight_kg === null || profile.initial_weight_kg === undefined
                ? this.form.initial_weight_kg
                : String(profile.initial_weight_kg)
        },
        restoreDraft: function () {
            const draft = readJson(KEYS.DRAFT_PROFILE_SETUP, null)
            if (!draft || !draft.savedAt) {
                return false
            }
            if (Date.now() - Number(draft.savedAt) > DRAFT_TTL_MS) {
                removeRaw(KEYS.DRAFT_PROFILE_SETUP)
                return false
            }
            if (draft.form) {
                this.form = Object.assign({}, this.form, draft.form)
            }
            if (draft.goals) {
                this.goals = Object.assign({}, this.goals, draft.goals)
            }
            if (draft.step && draft.step >= 1 && draft.step <= 4) {
                this.step = draft.step
            }
            return true
        },
        saveDraft: function () {
            if (!this.form) {
                return
            }
            writeJson(KEYS.DRAFT_PROFILE_SETUP, {
                step: this.step,
                form: this.form,
                goals: this.goals,
                savedAt: Date.now()
            })
        },
        clearDraft: function () {
            removeRaw(KEYS.DRAFT_PROFILE_SETUP)
        },

        /* ───────────── 步骤流转与校验 ───────────── */

        handlePrevStep: function () {
            if (this.step <= 1) {
                // 第 1 步无处可退：建档为强制流程（S1-C SC-05：1–3 步不可跳过）
                return
            }
            this.step = this.step - 1
            this.resetTransientErrors()
            this.saveDraft()
        },
        handlePrimary: function () {
            if (this.submitting) {
                return
            }
            if (this.step < 4) {
                this.handleNextStep()
                return
            }
            this.handleFinish(false)
        },
        /** 下一步：逐步校验（1–3 步必填） */
        handleNextStep: function () {
            if (!this.validateStep(this.step)) {
                return
            }
            this.step = this.step + 1
            this.resetTransientErrors()
            this.saveDraft()
        },
        resetTransientErrors: function () {
            this.serverSoftText = ''
            this.serverSoftAcknowledged = false
        },
        validateStep: function (step) {
            if (step === 1) {
                const nicknameError = checkNickname(this.form.nickname, true)
                this.errors.nickname = nicknameError || ''
                return !nicknameError
            }
            if (step === 2) {
                const genderError = this.form.gender === '' || this.form.gender === null ? '请选择性别' : ''
                const birthError = checkBirthDate(this.form.birth_date, true)
                this.errors.gender = genderError
                this.errors.birth_date = birthError || ''
                return !(genderError || birthError)
            }
            if (step === 3) {
                const height = toNumber(this.form.height_cm)
                const weight = toNumber(this.form.initial_weight_kg)
                let heightError = ''
                let weightError = ''
                if (height === null) {
                    heightError = '请输入身高'
                } else if (tooManyDecimals(height, 1)) {
                    heightError = '最多保留一位小数'
                }
                if (weight === null) {
                    weightError = '请输入当前体重'
                } else if (tooManyDecimals(weight, 1)) {
                    weightError = '最多保留一位小数'
                }
                this.errors.height_cm = heightError
                this.errors.initial_weight_kg = weightError
                return !(heightError || weightError)
            }
            return true
        },
        /** 越界的软提示字段（仅识别异常输入；不回显边界） */
        softFields: function () {
            const hits = []
            const height = toNumber(this.form.height_cm)
            const weight = toNumber(this.form.initial_weight_kg)
            if (height !== null && !inRange(height, SOFT.height)) {
                hits.push('height')
            }
            if (weight !== null && !inRange(weight, SOFT.weight)) {
                hits.push('weight')
            }
            this.goalFields().forEach(function (item) {
                if (!inRange(item.value, item.soft)) {
                    hits.push(item.key)
                }
            })
            return hits
        },
        /** 越界的硬拦截字段（"不可能值"） */
        hardFields: function () {
            const hits = []
            this.goalFields().forEach(function (item) {
                const rule = HARD[item.key]
                if (!rule) {
                    return
                }
                if (item.value <= rule.minExclusive || item.value > rule.max) {
                    hits.push(item.key)
                }
            })
            return hits
        },
        /** 第 4 步已填目标（值为数字） */
        goalFields: function () {
            const self = this
            const defs = [
                { key: 'weight', soft: SOFT.goalWeight },
                { key: 'water', soft: SOFT.water },
                { key: 'sport', soft: SOFT.sport },
                { key: 'sleep', soft: SOFT.sleep }
            ]
            const hits = []
            defs.forEach(function (def) {
                const value = toNumber(self.goals[def.key])
                if (value !== null) {
                    hits.push({ key: def.key, value: value, soft: def.soft })
                }
            })
            return hits
        },
        validateGoals: function () {
            const self = this
            const errors = { weight: '', water: '', sport: '', sleep: '' }
            const defs = [
                { key: 'weight', decimals: 1 },
                { key: 'water', decimals: 0 },
                { key: 'sport', decimals: 0 },
                { key: 'sleep', decimals: 1 }
            ]
            defs.forEach(function (def) {
                const raw = self.goals[def.key]
                const value = toNumber(raw)
                if (value === null) {
                    if (raw !== '' && raw !== null && raw !== undefined) {
                        errors[def.key] = '请填写数字'
                    }
                    return
                }
                if (tooManyDecimals(value, def.decimals)) {
                    errors[def.key] = def.decimals === 0 ? '请填写整数' : '最多保留一位小数'
                }
            })
            // 体重目标不得与当前体重相同（服务端会判定为无法计算完成度）
            const goalWeight = toNumber(this.goals.weight)
            const currentWeight = toNumber(this.form.initial_weight_kg)
            if (goalWeight !== null && currentWeight !== null && goalWeight === currentWeight) {
                errors.weight = '目标体重不能与当前体重相同'
            }
            this.goalErrors = errors
            return !(errors.weight || errors.water || errors.sport || errors.sleep)
        },

        /* ───────────── 提交 ───────────── */

        handleSkipGoals: function () {
            if (this.submitting) {
                return
            }
            this.handleFinish(true)
        },
        handleFinish: function (skipGoals) {
            if (this.submitting) {
                return
            }
            if (!this.validateStep(3)) {
                this.step = 3
                return
            }
            if (!skipGoals && !this.validateGoals()) {
                return
            }
            if (this.hasHardViolation) {
                showToast('error', RANGE_TEXT)
                return
            }
            const self = this
            isOnline().then(function (online) {
                if (!online) {
                    // 离线：可填写不可提交（保留内容，不自动重放）
                    showToast('error', offlineText('save'))
                    self.saveDraft()
                    return
                }
                self.doFinish(skipGoals)
            })
        },
        doFinish: function (skipGoals) {
            const self = this
            this.submitting = true
            // 软提示场景：确认后原样重发并置 acknowledge_warnings = true
            const acknowledge = this.hasSoftViolation || !!this.serverSoftText
            updateProfile(this.profilePayload(), acknowledge).then(function (res) {
                if (res.code === 'SOFT_WARNING') {
                    // 服务端软提示（本次未写入）→ 提示后需再次确认
                    self.serverSoftText = res.message || RANGE_TEXT
                    self.serverSoftAcknowledged = false
                    self.submitting = false
                    showToast('info', self.serverSoftText)
                    return
                }
                // 建档成功 → 本地标记（服务端 P-02 后 profile 至少一项非空）
                const store = useUserStore()
                store.setProfileInitialized(true)
                return self.createGoals(skipGoals).then(function (failed) {
                    self.submitting = false
                    self.clearDraft()
                    if (failed && failed.length) {
                        showToast('info', '档案已保存，部分目标未设置成功')
                    }
                    // 完成 / 跳过 → SC-06 首页（不可回退到引导流）
                    reLaunch(ROUTES.HOME)
                })
            }, function (err) {
                self.submitting = false
                self.handleSubmitError(err)
            })
        },
        createGoals: function (skipGoals) {
            const list = skipGoals ? [] : this.filledGoals()
            if (!list.length) {
                return Promise.resolve([])
            }
            const acknowledge = this.hasSoftViolation
            const failed = []
            let chain = Promise.resolve()
            list.forEach(function (item) {
                item.acknowledge_warnings = acknowledge
                chain = chain.then(function () {
                    return createGoal(item).then(function () {
                        // 成功或软提示（本次未写入）均如此处理
                    }, function (err) {
                        if (err && err.code === 'GOAL_TYPE_EXISTS') {
                            // 同类型目标已存在 = 用户意图已满足，跳过
                            return
                        }
                        failed.push(item.label)
                    })
                })
            })
            return chain.then(function () {
                return failed
            })
        },
        filledGoals: function () {
            const list = []
            const currentWeight = toNumber(this.form.initial_weight_kg)
            const goalWeight = toNumber(this.goals.weight)
            if (goalWeight !== null) {
                list.push({
                    label: '目标体重',
                    goal_type: 'weight',
                    target_value: goalWeight,
                    start_weight_kg: currentWeight
                })
            }
            const water = toNumber(this.goals.water)
            if (water !== null) {
                list.push({ label: '每日饮水目标', goal_type: 'water', target_value: water })
            }
            const sport = toNumber(this.goals.sport)
            if (sport !== null) {
                // sport 必须携带 attr_1：本页采用「周分钟」（min），与 unit 一致
                list.push({ label: '每周运动目标', goal_type: 'sport', target_value: sport, attr_1: 'min' })
            }
            const sleep = toNumber(this.goals.sleep)
            if (sleep !== null) {
                list.push({ label: '每日睡眠目标', goal_type: 'sleep', target_value: sleep })
            }
            return list
        },
        /** 档案请求体（P-02 为**整体替换**：未采集字段一律提交 null） */
        profilePayload: function () {
            return {
                nickname: this.form.nickname ? String(this.form.nickname).trim() : null,
                gender: this.form.gender === '' || this.form.gender === null ? null : Number(this.form.gender),
                birth_date: this.form.birth_date ? String(this.form.birth_date) : null,
                height_cm: toNumber(this.form.height_cm),
                initial_weight_kg: toNumber(this.form.initial_weight_kg),
                // SC-05 不采集以下字段 → 提交 null（整体替换语义）
                blood_type: null,
                medical_history: null,
                allergy_history: null,
                medication_notes: null
            }
        },
        handleSubmitError: function (err) {
            const code = err && err.code ? err.code : ''
            if (code === 'VALIDATION_FAILED' || code === 'PASSWORD_INVALID') {
                const nicknameError = fieldErrorText(err, 'nickname')
                const birthError = fieldErrorText(err, 'birth_date')
                const heightError = fieldErrorText(err, 'height_cm')
                const weightError = fieldErrorText(err, 'initial_weight_kg')
                if (nicknameError) {
                    this.errors.nickname = nicknameError
                    this.step = 1
                }
                if (birthError) {
                    this.errors.birth_date = birthError
                    this.step = 2
                }
                if (heightError || weightError) {
                    this.errors.height_cm = heightError
                    this.errors.initial_weight_kg = weightError
                    this.step = 3
                }
                if (nicknameError || birthError || heightError || weightError) {
                    showToast('error', '请检查填写内容')
                    return
                }
            }
            // 失败 → Toast + 保留已填内容（草稿已落盘）
            this.saveDraft()
            showToast('error', errorText(err))
        }
    }
}
</script>

<style scoped lang="scss">
.setup {
    min-height: 100vh;
    background-color: var(--s-page);
}

.setup__body {
    padding-top: var(--nav-total-h);
    padding-left: var(--gutter);
    padding-right: var(--gutter);
    /* 预留底部固定操作区：安全区 + 上下内边距 + AppButton(m) + 「稍后补充」浮层，全部由 Token 推导 */
    padding-bottom: calc(var(--safe-b) + var(--sp-10) * 3);
}

.setup__progress {
    padding-top: var(--sp-7);
    padding-bottom: var(--sp-7);
}

.setup__progress-track {
    height: 8rpx;
    border-radius: var(--r-full);
    background-color: var(--s-sunken);
    overflow: hidden;
}

.setup__progress-fill {
    height: 8rpx;
    border-radius: var(--r-full);
    background-color: var(--c-p-600);
    transition: width var(--d-base) var(--ease-std);
}

.setup__progress-text {
    display: block;
    margin-top: var(--sp-4);
    font-size: var(--fs-caption);
    line-height: $lh-caption;
    color: var(--t-3);
    letter-spacing: 0;
}

.setup__error {
    margin-bottom: var(--card-gap);
}

.setup__card {
    margin-bottom: var(--card-gap);
}

.setup__gap {
    height: var(--sp-6);
}

.setup__warn {
    margin-top: var(--sp-5);
}

.setup__tip {
    display: block;
    margin-top: var(--sp-5);
    font-size: var(--fs-micro);
    line-height: $lh-micro;
    color: var(--t-4);
    letter-spacing: 0;
}

/* 底部固定操作区 */
.setup__foot {
    position: fixed;
    left: 0;
    right: 0;
    bottom: 0;
    z-index: 30;
    display: flex;
    flex-direction: row;
    align-items: center;
    padding: var(--sp-5) var(--gutter) calc(var(--safe-b) + var(--sp-5)) var(--gutter);
    background-color: var(--s-card);
    border-top: 1rpx solid var(--b-line);
}

.setup__foot-prev {
    flex: 1;
    margin-right: var(--sp-5);
}

.setup__foot-main {
    flex: 1.4;
}

/* 第 4 步「稍后补充」 */
.setup__foot-skip {
    position: absolute;
    left: 0;
    right: 0;
    top: calc(-1 * var(--tap-min));
    height: var(--tap-min);
    display: flex;
    align-items: center;
    justify-content: center;
    transition: transform var(--d-fast) var(--ease-std), opacity var(--d-fast) var(--ease-std);
}

.setup__foot-skip--press {
    transform: scale(var(--press-scale));
    opacity: var(--press-opacity);
}

.setup__foot-skip-text {
    font-size: var(--fs-btn-m);
    line-height: $lh-btn-m;
    font-weight: $fw-medium;
    color: var(--t-3);
    letter-spacing: 0;
}
</style>
