<template>
    <!--
      SC-17 档案编辑页（pages/profile/edit）
      依据：S1-C §二 SC-17（① 顶部栏「编辑档案」/ ② 昵称·性别·出生日期 / ③ 身高+cm /
            ④ 初始体重+kg / ⑤ 血型选择器 / ⑥ **目标体重只读** +「前往目标页修改」→ SC-12 /
            ⑦ 健康背景三字段（多行 + 字数上限）/ ⑧ 整体替换提示 / ⑨ 保存按钮 / ⑩ 页脚注 D-1）｜
            DESIGN.md §8（C-03 / C-04 / C-05 / C-06）/ §10.3（**A 类系统导航栏**）/ §11 / §12 / §13 / §14.8

      顶栏：**A 类系统导航栏**（`DESIGN.md §10.3` 的 B 类自绘顶栏清单**不含** SC-17）——
            标题由 `pages.json` 指定，本页**不得**加 `navigationStyle: custom`。

      数据来源：
        · P-01 `GET /profile`          → 进入时**必须先取最新档案再回填**（SC-17 ⑪：I-02 缓解措施，不可省）
        · P-02 `PUT /profile`          → 提交（**整体替换语义**：未提交字段一律置空）
        · G-01 `GET /goals`（**只读**）  → **目标体重只读展示**（辅助请求，失败显示「—」）

      ★ D-1 / `DESIGN.md §14.8`：**本页不提供目标体重编辑控件**，只有只读展示 + 跳转 SC-12。

      ★ 医疗红线：健康背景三字段**原样存取、零解析、零提示**；越界只写
        「数值超出常见范围，请确认是否输错」，**不得出现任何医学正常值 / 参考范围 / 风险等级**
        （DESIGN.md §12 / `utils/validate.js#RANGE_TEXT`）。

      状态覆盖（DESIGN.md §13 底线清单，逐项说明）：
        正常 → 表单可编辑；
        空 → **N/A**（表单页，未填字段即空输入框 —— S1-C SC-17 ⑩ 明确「不适用」）；
        加载 → **骨架屏**（进入时先 GET 再回填）；
        失败 → `AppErrorState` + 重试；未登录 → 路由守卫 → SC-03；
        离线 → **禁止编辑**：不进入编辑态、**不展示可编辑表单**，仅提示「离线状态暂不可编辑」
              （S1-C SC-17 ⑭：写操作必须在线）；
        高风险确认 → **⑮ 清空原本已填字段**时保存前二次确认「将清空「XX」字段，确认保存？」；
        提交防重 → 保存按钮**点击即 disabled + loading**（F-083 第一道防线）。

      ★ 如实登记（本轮不伪造，逐条给出原因）：
        ① ⑧「整体替换提示」原文标注「**首次显示**」。持久化「已提示过」需要一个本地标记键，
           而 `utils/storage.js` 属 **S3-5 封板资产**（按 S-3 默认值本批不改）⇒ 本页**常显**该提示。
           这是**更保守**的取舍：整体替换语义每次都给用户一次提醒，不会因为"提示过了"而误清空。
           已作为登记项上报（若需严格"仅首次"，请指定承载键）。
        ② 血型选项为**前端常量**（S-1：`R-08` 字典不含 `blood_type`，与 SC-05 的 `genderOptions` 同先例）。
    -->
    <view class="ped">
        <view class="ped__body">
            <view class="ped__inner">
                <!-- 离线只读标记 / 网络恢复横幅 -->
                <view v-if="offlineBarText" class="ped__block">
                    <AppOfflineBar variant="offline" :text="offlineBarText" />
                </view>
                <view v-if="restoredVisible" class="ped__block">
                    <AppOfflineBar variant="restored" text="网络已恢复，正在刷新" />
                </view>

                <!-- ⑭ 离线禁止编辑：**不进入编辑态、不展示可编辑表单** -->
                <view v-if="offline" class="ped__block">
                    <AppEmpty variant="common" text="离线状态暂不可编辑" :show-action="false" />
                </view>

                <!-- ⑪ 进入时先 GET 最新档案再回填（骨架屏） -->
                <view v-else-if="state === 'loading'" class="ped__block">
                    <AppSkeleton variant="profile" />
                </view>

                <!-- ⑫③ 加载失败 → 失败组件 + 重试 -->
                <view v-else-if="state === 'error'" class="ped__block">
                    <AppErrorState variant="full" :text="errorMsg" @retry="reload" />
                </view>

                <template v-else>
                    <!-- ⑧ 整体替换提示（见文件头「如实登记 ①」：本页常显） -->
                    <view class="ped__block">
                        <view class="ped__tip">
                            <text class="ped__tip-text">保存将以本次填写内容整体覆盖档案</text>
                        </view>
                    </view>

                    <!-- ② 基础信息 -->
                    <AppCard class="ped__block" title="基础信息">
                        <AppInput
                            v-model="form.nickname"
                            label="昵称"
                            placeholder="请输入昵称"
                            hint="不超过 20 个字"
                            :maxlength="20"
                            clearable
                            :error="errors.nickname"
                        />
                        <view class="ped__gap"></view>
                        <AppSelect
                            v-model="form.gender"
                            label="性别"
                            title="请选择性别"
                            :options="genderOptions"
                            :error="errors.gender"
                        />
                        <view class="ped__gap"></view>
                        <AppDatePicker
                            v-model="form.birth_date"
                            mode="date"
                            label="出生日期"
                            placeholder="请选择出生日期"
                            :end="today"
                            start="1900-01-01"
                            :error="errors.birth_date"
                        />
                    </AppCard>

                    <!-- ③④⑤ 身体基础值 + ⑥ 目标体重（只读） -->
                    <AppCard class="ped__block" title="身体基础值">
                        <AppInput
                            v-model="form.height_cm"
                            label="身高"
                            placeholder="请输入身高"
                            unit="cm"
                            type="digit"
                            :maxlength="6"
                            :error="errors.height_cm"
                        />
                        <view class="ped__gap"></view>
                        <AppInput
                            v-model="form.initial_weight_kg"
                            label="初始体重"
                            placeholder="请输入初始体重"
                            unit="kg"
                            type="digit"
                            :maxlength="6"
                            :error="errors.initial_weight_kg"
                        />
                        <view class="ped__gap"></view>
                        <AppSelect
                            v-model="form.blood_type"
                            label="血型"
                            title="请选择血型"
                            :options="bloodOptions"
                            :error="errors.blood_type"
                        />

                        <!-- 越界软提示（可继续保存；**不含任何医学参考范围**） -->
                        <view v-if="warnLevel" class="ped__warn">
                            <AppValidateBar :visible="true" :level="warnLevel" />
                        </view>

                        <!-- ⑥ 目标体重：**只读** + 链接（D-1 / §14.8 禁令 8） -->
                        <view class="ped__gap"></view>
                        <view class="ped__ro">
                            <text class="ped__ro-label">目标体重</text>
                            <text class="ped__ro-value">{{ targetWeightText }}</text>
                        </view>
                        <view
                            class="ped__link"
                            hover-class="ped__link--press"
                            :hover-start-time="0"
                            :hover-stay-time="80"
                            @tap="onGoalEntry"
                        >
                            <text class="ped__link-text">前往目标页修改</text>
                        </view>
                    </AppCard>

                    <!-- ⑦ 健康背景（多行 + 字数计数；**原样存取、零解读**） -->
                    <AppCard class="ped__block" title="健康背景">
                        <AppTextarea
                            v-model="form.medical_history"
                            label="既往病史"
                            placeholder="选填"
                            :maxlength="textMax"
                            :error="errors.medical_history"
                        />
                        <view class="ped__gap"></view>
                        <AppTextarea
                            v-model="form.allergy_history"
                            label="过敏史"
                            placeholder="选填"
                            :maxlength="textMax"
                            :error="errors.allergy_history"
                        />
                        <view class="ped__gap"></view>
                        <AppTextarea
                            v-model="form.medication_notes"
                            label="长期用药记录"
                            placeholder="选填"
                            :maxlength="textMax"
                            :error="errors.medication_notes"
                        />
                        <text class="ped__note">仅作记录，本应用不做任何解读</text>
                    </AppCard>

                    <!-- ⑩ 页脚注（D-1 标记） -->
                    <text class="ped__foot">
                        目标体重以「健康目标」中的设置为准；本页只读展示，如需修改请前往目标页。
                    </text>
                </template>
            </view>
        </view>

        <!-- ⑨ 保存（底部固定区，含安全区；离线 / 未就绪时不渲染） -->
        <view v-if="formVisible" class="ped__bar">
            <AppButton
                label="保存"
                type="primary"
                size="l"
                block
                :loading="saving"
                @tap="onSave"
            />
        </view>

        <!-- ⑮ 清空原本已填字段 → 保存前二次确认（普通确认，非危险操作） -->
        <AppModal
            :show="clearVisible"
            mode="confirm"
            title="确认保存"
            :content="clearConfirmText"
            confirm-text="确认保存"
            cancel-text="取消"
            :confirm-disabled="saving"
            @update:show="onClearShow"
            @confirm="doSave"
            @cancel="onClearCancel"
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
import AppTextarea from '../../components/AppTextarea.vue'
import AppSelect from '../../components/AppSelect.vue'
import AppDatePicker from '../../components/AppDatePicker.vue'
import AppButton from '../../components/AppButton.vue'
import AppSkeleton from '../../components/AppSkeleton.vue'
import AppErrorState from '../../components/AppErrorState.vue'
import AppValidateBar from '../../components/AppValidateBar.vue'
import AppOfflineBar from '../../components/AppOfflineBar.vue'
import AppEmpty from '../../components/AppEmpty.vue'
import AppModal from '../../components/AppModal.vue'
import AppToast from '../../components/AppToast.vue'
import DevPagePreviewer from '../../components/DevPagePreviewer.vue'

import { ROUTES, navigateTo, navigateBack, requireLogin } from '../../utils/route'
import { getProfile, updateProfile } from '../../api/profile'
import { fetchGoals } from '../../api/goals'
import { errorText, fieldErrorText } from '../../utils/request'
import { isOnline } from '../../utils/network'
import { showToast } from '../../utils/toast'
import { NETWORK_BANNER_MS } from '../../utils/config'
import {
    checkNickname, checkBirthDate, toNumber, inRange, tooManyDecimals, todayString, RANGE_TEXT
} from '../../utils/validate'

/** 健康背景文本字段上限（S-2：`S1-B §14.2` 权威值 ≤2000 字，纯文本不富文本） */
const TEXT_MAX = 2000

/** 出生日期下限（与 SC-05 同口径） */
const BIRTH_MIN = '1900-01-01'

/** 中性技术提示（不涉及任何医学表述） */
const TOAST_SAVED = '已保存'

/**
 * 「录入合理性区间」——仅用于识别异常输入，**不是医学参考范围**，且**不回显边界值**。
 * 来源：`S1-B §六 P-02`（身高 50–250 / 体重 20–300）。
 */
const SOFT = {
    height: { min: 50, max: 250 },
    weight: { min: 20, max: 300 }
}

/** 性别选项（与 SC-05 同口径：1 男 / 2 女） */
const GENDER_OPTIONS = [
    { value: 1, label: '男' },
    { value: 2, label: '女' }
]

/**
 * 血型选项（S-1：`R-08` 字典**不含**血型 ⇒ 前端常量，与 SC-05 的 `genderOptions` 同先例；
 * 值域与后端 `BLOOD_TYPES = ("A","B","AB","O","UNKNOWN")` 对齐）。
 */
const BLOOD_OPTIONS = [
    { value: 'A', label: 'A 型' },
    { value: 'B', label: 'B 型' },
    { value: 'AB', label: 'AB 型' },
    { value: 'O', label: 'O 型' },
    { value: 'UNKNOWN', label: '不详' }
]

/** 参与「整体替换 ⇒ 清空」判定的字段与其中文名（用于二次确认文案） */
const FIELD_LABELS = [
    { key: 'nickname', label: '昵称' },
    { key: 'gender', label: '性别' },
    { key: 'birth_date', label: '出生日期' },
    { key: 'height_cm', label: '身高' },
    { key: 'initial_weight_kg', label: '初始体重' },
    { key: 'blood_type', label: '血型' },
    { key: 'medical_history', label: '既往病史' },
    { key: 'allergy_history', label: '过敏史' },
    { key: 'medication_notes', label: '长期用药记录' }
]

/** 空值判定（统一口径：null / undefined / 空串 均视为「空」） */
function isBlank(value) {
    return value === null || value === undefined || String(value) === ''
}

/** 从 G-01 响应中取「目标体重」（与 SC-16 同口径；D-1：唯一数据源 = `health_goal`） */
function weightTargetOf(res) {
    const items = (res && res.data && res.data.items) || []
    for (let i = 0; i < items.length; i++) {
        const g = items[i]
        if (g && g.goal_type === 'weight' && g.target_value !== null && g.target_value !== undefined) {
            return { known: true, value: g.target_value, unit: g.unit ? String(g.unit) : 'kg' }
        }
    }
    return { known: true, value: null, unit: '' }
}

export default {
    components: {
        AppCard: AppCard,
        AppInput: AppInput,
        AppTextarea: AppTextarea,
        AppSelect: AppSelect,
        AppDatePicker: AppDatePicker,
        AppButton: AppButton,
        AppSkeleton: AppSkeleton,
        AppErrorState: AppErrorState,
        AppValidateBar: AppValidateBar,
        AppOfflineBar: AppOfflineBar,
        AppEmpty: AppEmpty,
        AppModal: AppModal,
        AppToast: AppToast,
        DevPagePreviewer: DevPagePreviewer
    },
    data: function () {
        return {
            /** 页面态：loading / normal / error */
            state: 'loading',
            /** 失败文案（取自统一请求层，不自行编造） */
            errorMsg: '',
            today: todayString(),
            textMax: TEXT_MAX,
            genderOptions: GENDER_OPTIONS,
            bloodOptions: BLOOD_OPTIONS,

            /** 表单（字符串态，提交时再转数字 —— 避免输入过程中被"纠正"） */
            form: {
                nickname: '',
                gender: '',
                birth_date: '',
                height_cm: '',
                initial_weight_kg: '',
                blood_type: '',
                medical_history: '',
                allergy_history: '',
                medication_notes: ''
            },
            /** 服务端读回的原始档案（**仅用于「清空字段」二次确认判定**，不参与提交） */
            original: null,
            errors: {
                nickname: '', gender: '', birth_date: '', height_cm: '',
                initial_weight_kg: '', blood_type: '',
                medical_history: '', allergy_history: '', medication_notes: ''
            },

            /** 目标体重：{ known, value, unit } */
            target: { known: true, value: null, unit: '' },

            /* ── 离线 / 网络 ── */
            offline: false,
            cacheSavedAt: '',
            restoredVisible: false,

            /* ── 提交 ── */
            saving: false,
            /** 服务端软提示（客户端预判之外的边界情况） */
            serverSoftText: '',
            /** 清空字段二次确认 */
            clearVisible: false,
            clearConfirmText: '',

            bannerTimer: null,
            networkHandler: null
        }
    },
    computed: {
        /** 表单是否可见（离线 / 未加载完成时**不展示可编辑表单**） */
        formVisible: function () {
            return !this.offline && this.state === 'normal'
        },
        /** 离线条文案 */
        offlineBarText: function () {
            if (!this.offline) {
                return ''
            }
            if (this.cacheSavedAt) {
                return '离线数据 · 更新于 ' + this.cacheSavedAt
            }
            return '当前离线，暂不可编辑'
        },
        /** 越界软提示级别（档案字段只有软提示，**没有硬拦截区间**） */
        warnLevel: function () {
            return this.hasSoftViolation ? 'soft' : ''
        },
        hasSoftViolation: function () {
            const height = toNumber(this.form.height_cm)
            const weight = toNumber(this.form.initial_weight_kg)
            if (height !== null && !inRange(height, SOFT.height)) {
                return true
            }
            if (weight !== null && !inRange(weight, SOFT.weight)) {
                return true
            }
            return false
        },
        /** 目标体重展示文案（三态：具体值 / 「未设置」/ 「—」） */
        targetWeightText: function () {
            const t = this.target || {}
            if (!t.known) {
                return '—'
            }
            if (t.value === null || t.value === undefined) {
                return '未设置'
            }
            return String(t.value) + ' ' + (t.unit ? String(t.unit) : 'kg')
        },
        /** 因整体替换而**会被清空**的字段中文名（原本非空 → 现在为空） */
        clearedLabels: function () {
            const labels = []
            const base = this.original || {}
            const self = this
            FIELD_LABELS.forEach(function (item) {
                if (isBlank(base[item.key])) {
                    return
                }
                if (isBlank(self.form[item.key])) {
                    labels.push(item.label)
                }
            })
            return labels
        }
    },
    onLoad: function () {
        // 未登录守卫（S1-C SC-17 ⑬：需登录）
        if (!requireLogin()) {
            return
        }

        // ⑭ 离线禁止编辑：先判定网络，离线时**不加载、不渲染表单**
        const self = this
        isOnline().then(function (online) {
            if (!online) {
                self.offline = true
                return
            }
            self.loadProfile()
        })

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
        // 离开即清空内存中的表单输入（**不落草稿** —— S-3 默认值：SC-17 不做草稿）
        // ★ 不置 this.form = null：模板 v-model 仍依赖 form.* 字段，卸载期置 null
        //   会触发重渲染并读取 null.nickname / null.height_cm ⇒ TypeError（D-3.2-01）
        this.form.nickname = ''
        this.form.gender = ''
        this.form.birth_date = ''
        this.form.height_cm = ''
        this.form.initial_weight_kg = ''
        this.form.blood_type = ''
        this.form.medical_history = ''
        this.form.allergy_history = ''
        this.form.medication_notes = ''
        // original 不参与模板渲染（clearedLabels 以 (this.original || {}) 读取）⇒ 置 null 安全
        this.original = null
    },
    methods: {
        /* ───────────── 加载（先 GET 再回填） ───────────── */

        /**
         * ⑪ 进入时必须**先取最新档案再回填** —— I-02 缓解措施（多设备下避免用陈旧值覆盖）。
         */
        loadProfile: function () {
            const self = this
            this.errorMsg = ''
            this.state = 'loading'

            // 目标体重为**辅助请求**：失败不影响档案主体，只把目标体重降级为「—」
            fetchGoals().then(function (res) {
                self.target = weightTargetOf(res)
            }, function () {
                self.target = { known: false, value: null, unit: '' }
            })

            return getProfile().then(function (res) {
                const profile = (res.data && res.data.profile) || {}
                self.original = profile
                self.applyProfile(profile)
                self.state = 'normal'
            }, function (err) {
                if (err && err.isNetwork) {
                    // 真离线（401 已由统一请求层处理并清栈回 SC-03，不会走到这里）
                    self.offline = true
                    return
                }
                self.errorMsg = errorText(err)
                self.state = 'error'
            })
        },

        /** 手动重试 */
        reload: function () {
            this.offline = false
            this.loadProfile()
        },

        /** 服务端档案 → 表单（**空值一律转空串**，保持输入框语义） */
        applyProfile: function (profile) {
            const p = profile || {}
            this.form = {
                nickname: isBlank(p.nickname) ? '' : String(p.nickname),
                gender: isBlank(p.gender) ? '' : p.gender,
                birth_date: isBlank(p.birth_date) ? '' : String(p.birth_date),
                height_cm: isBlank(p.height_cm) ? '' : String(p.height_cm),
                initial_weight_kg: isBlank(p.initial_weight_kg) ? '' : String(p.initial_weight_kg),
                blood_type: isBlank(p.blood_type) ? '' : String(p.blood_type),
                medical_history: isBlank(p.medical_history) ? '' : String(p.medical_history),
                allergy_history: isBlank(p.allergy_history) ? '' : String(p.allergy_history),
                medication_notes: isBlank(p.medication_notes) ? '' : String(p.medication_notes)
            }
        },

        /* ───────────── 校验 ───────────── */

        /** 字段级校验（格式类）；返回是否全部通过 */
        validate: function () {
            const errors = {
                nickname: '', gender: '', birth_date: '', height_cm: '',
                initial_weight_kg: '', blood_type: '',
                medical_history: '', allergy_history: '', medication_notes: ''
            }

            errors.nickname = checkNickname(this.form.nickname, false) || ''
            errors.birth_date = checkBirthDate(this.form.birth_date, false) || ''
            errors.height_cm = this.numberError(this.form.height_cm)
            errors.initial_weight_kg = this.numberError(this.form.initial_weight_kg)

            // 文本超长（`maxlength` 已限制输入，此处按服务端口径兜底）
            const self = this
            const textKeys = ['medical_history', 'allergy_history', 'medication_notes']
            textKeys.forEach(function (key) {
                const v = self.form[key]
                if (!isBlank(v) && String(v).length > TEXT_MAX) {
                    errors[key] = '最多 ' + TEXT_MAX + ' 字'
                }
            })

            this.errors = errors
            return !(errors.nickname || errors.gender || errors.birth_date || errors.height_cm ||
                errors.initial_weight_kg || errors.blood_type ||
                errors.medical_history || errors.allergy_history || errors.medication_notes)
        },

        /** 数值字段的格式校验（空 → 不报错；非数字 / 小数位超限 → 给提示） */
        numberError: function (raw) {
            if (isBlank(raw)) {
                return ''
            }
            const value = toNumber(raw)
            if (value === null) {
                return '请填写数字'
            }
            if (tooManyDecimals(value, 1)) {
                return '最多保留一位小数'
            }
            return ''
        },

        /* ───────────── 提交 ───────────── */

        /** 保存入口：先校验 → 若有字段会被清空则先二次确认 |
         *  （越界只做**软提示**：`AppValidateBar` 已提示，仍可继续保存 —— DESIGN.md §12） */
        onSave: function () {
            if (this.saving) {
                return
            }
            if (!this.validate()) {
                showToast('error', '请检查填写内容')
                return
            }
            const cleared = this.clearedLabels
            if (cleared.length) {
                this.clearConfirmText = this.clearTextOf(cleared)
                this.clearVisible = true
                return
            }
            this.doSave()
        },

        /** ⑮ 二次确认文案（逐字取自 S1-C SC-17 ⑮ 的句式；超过 3 项时收敛，避免弹窗过长） */
        clearTextOf: function (labels) {
            const shown = labels.length <= 3 ? labels : labels.slice(0, 1)
            const parts = []
            for (let i = 0; i < shown.length; i++) {
                parts.push('「' + shown[i] + '」')
            }
            if (labels.length <= 3) {
                return '将清空 ' + parts.join('') + ' 字段，确认保存？'
            }
            return '将清空 ' + parts[0] + ' 等 ' + labels.length + ' 个字段，确认保存？'
        },

        onClearShow: function (value) {
            if (!value) {
                this.clearVisible = false
            }
        },

        onClearCancel: function () {
            this.clearVisible = false
        },

        /**
         * 提交 P-02（**整体替换**：9 字段齐全，未填一律 null）。
         * 服务端软提示（HTTP 200 + `SOFT_WARNING`，本次未写入）→ 提示后需再次确认才重发。
         */
        doSave: function () {
            const self = this
            this.clearVisible = false
            if (this.saving) {
                return
            }
            this.saving = true
            const acknowledge = this.hasSoftViolation || !!this.serverSoftText
            updateProfile(this.payload(), acknowledge).then(function (res) {
                if (res.code === 'SOFT_WARNING') {
                    // 服务端软提示（本次未写入）→ 保留输入 + 提示，用户再次点保存即为确认重发
                    self.serverSoftText = res.message || RANGE_TEXT
                    self.saving = false
                    showToast('info', self.serverSoftText)
                    return
                }
                self.saving = false
                showToast('success', TOAST_SAVED)
                // ⑯ 保存成功 → **返回 SC-16 并刷新**（SC-16 的 onShow 会自动刷新）
                navigateBack()
            }, function (err) {
                self.saving = false
                self.handleSubmitError(err)
            })
        },

        /** P-02 请求体（**整体替换**：9 字段齐全；`api/profile.js` 负责补 `acknowledge_warnings`） */
        payload: function () {
            return {
                nickname: isBlank(this.form.nickname) ? null : String(this.form.nickname).trim(),
                gender: isBlank(this.form.gender) ? null : Number(this.form.gender),
                birth_date: isBlank(this.form.birth_date) ? null : String(this.form.birth_date),
                height_cm: isBlank(this.form.height_cm) ? null : toNumber(this.form.height_cm),
                initial_weight_kg: isBlank(this.form.initial_weight_kg)
                    ? null
                    : toNumber(this.form.initial_weight_kg),
                blood_type: isBlank(this.form.blood_type) ? null : String(this.form.blood_type),
                medical_history: isBlank(this.form.medical_history) ? null : String(this.form.medical_history),
                allergy_history: isBlank(this.form.allergy_history) ? null : String(this.form.allergy_history),
                medication_notes: isBlank(this.form.medication_notes) ? null : String(this.form.medication_notes)
            }
        },

        /** 失败处理：**保留输入**（不重置表单），字段级明细回填到对应输入框 */
        handleSubmitError: function (err) {
            const code = err && err.code ? err.code : ''
            if (code === 'VALIDATION_FAILED') {
                const nicknameError = fieldErrorText(err, 'nickname')
                const birthError = fieldErrorText(err, 'birth_date')
                const heightError = fieldErrorText(err, 'height_cm')
                const weightError = fieldErrorText(err, 'initial_weight_kg')
                if (nicknameError || birthError || heightError || weightError) {
                    if (nicknameError) {
                        this.errors.nickname = nicknameError
                    }
                    if (birthError) {
                        this.errors.birth_date = birthError
                    }
                    if (heightError) {
                        this.errors.height_cm = heightError
                    }
                    if (weightError) {
                        this.errors.initial_weight_kg = weightError
                    }
                    showToast('error', '请检查填写内容')
                    return
                }
            }
            // 5xx / 其它 → 明确提示 + 保留输入（用户可直接重试）
            showToast('error', errorText(err))
        },

        /* ───────────── 出口 ───────────── */

        /** ⑥「前往目标页修改」→ SC-12（D-1：目标体重唯一编辑入口在 SC-12 / SC-13 链路） */
        onGoalEntry: function () {
            navigateTo(ROUTES.GOAL)
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
            // 恢复联网后按「首次加载」处理：重新 GET 最新档案再回填（避免用断开前的旧值覆盖）
            this.loadProfile()
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
.ped {
    min-height: 100vh;
    background-color: var(--s-page);
}

/* A 类系统导航栏占位由平台负责；底部预留固定保存区 */
.ped__body {
    padding-top: var(--page-pad-t);
    padding-bottom: calc(var(--safe-b) + var(--sp-10) * 3);
}

.ped__inner {
    max-width: var(--content-max);
    margin-left: auto;
    margin-right: auto;
    padding-left: var(--gutter);
    padding-right: var(--gutter);
}

.ped__block {
    margin-bottom: var(--card-gap);
}

.ped__gap {
    height: var(--sp-6);
}

/* ── ⑧ 整体替换提示 ── */
.ped__tip {
    padding: var(--sp-4) var(--sp-5);
    border-radius: var(--r-sm);
    background-color: var(--c-info-bg);
}

.ped__tip-text {
    display: block;
    font-size: var(--fs-caption);
    line-height: $lh-caption;
    color: var(--c-info);
    letter-spacing: 0;
}

/* ── 越界软提示 ── */
.ped__warn {
    margin-top: var(--sp-5);
}

/* ── ⑥ 目标体重（只读行 + 链接） ── */
.ped__ro {
    display: flex;
    flex-direction: row;
    align-items: center;
    justify-content: space-between;
    min-height: var(--tap-min);
}

.ped__ro-label {
    font-size: var(--fs-sub);
    line-height: $lh-sub;
    color: var(--t-2);
    letter-spacing: 0;
}

.ped__ro-value {
    font-size: var(--fs-body);
    line-height: $lh-body;
    color: var(--t-3);
    letter-spacing: 0;
    font-variant-numeric: tabular-nums;
}

.ped__link {
    display: flex;
    flex-direction: row;
    align-items: center;
    min-height: var(--tap-min);
    transition: transform var(--d-fast) var(--ease-std), opacity var(--d-fast) var(--ease-std);
}

.ped__link--press {
    transform: scale(var(--press-scale));
    opacity: var(--press-opacity);
}

.ped__link-text {
    font-size: var(--fs-btn-m);
    line-height: $lh-btn-m;
    font-weight: $fw-medium;
    color: var(--t-link);
    letter-spacing: 0;
}

/* ── ⑦ 健康背景固定说明 ── */
.ped__note {
    display: block;
    margin-top: var(--sp-5);
    font-size: var(--fs-micro);
    line-height: $lh-micro;
    color: var(--t-4);
    letter-spacing: 0;
}

/* ── ⑩ 页脚注（D-1 标记） ── */
.ped__foot {
    display: block;
    padding: var(--sp-2);
    font-size: var(--fs-caption);
    line-height: $lh-caption;
    color: var(--t-3);
    letter-spacing: 0;
}

/* ── ⑨ 底部固定保存区（含安全区） ── */
.ped__bar {
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
