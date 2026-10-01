<template>
    <!--
      SC-13 目标编辑页（pages/goal/edit?type=）
      依据：S1-C §二 SC-13（① 顶部栏 / ② 类型选择 / ③ 目标值 / ④ 周期 / ⑤ 状态操作 / ⑥ 保存）
            ｜ DESIGN.md §8.3（C-25）/ §10.3（**A 类系统导航栏**）/ §11 / §12 / §13

      顶栏：**A 类系统导航栏**，标题由 `uni.setNavigationBarTitle` 动态设置（「新建目标」/「编辑目标」）；
            原型 ① 的【删除】在导航栏放不下 ⇒ **照 SC-09 先例落内容区底部**。

      接口（**只用已封板接口，未改后端**）：
        · G-01 `GET /api/v1/goals`        → 判定"哪些类型已有在用目标"（决定模式与置灰）
        · G-02 `POST /api/v1/goals`       → 新建（体重目标带 `auto_start_weight: true`）
        · G-03 `PATCH /api/v1/goals/{id}` → 修改（**局部更新**，不带 `goal_type` / `start_weight_kg`）
        · G-04 / G-05 `…/pause` `…/resume` → 暂停 / 恢复
        · G-06 `DELETE /api/v1/goals/{id}` → 删除（soft delete；二次确认由 C-12 danger 完成）

      ★ 本页三处口径来自需求方裁定（S3-5）：
        ① 开始日期**只读显示今天**，不开放修改（不放 `AppDatePicker`）；
        ② 体重目标采用 `auto_start_weight: true`（服务端取"最近一条体重记录"），**不设**起始体重输入框；
        ③ 运动目标为**二选一**（周次数 / 周分钟），配**一个**目标值，不同时填。

      状态覆盖（DESIGN.md §13）：
        正常 / 加载（G-01 载入中 → 骨架屏）/ 失败（载入失败 → 失败组件 + 重试）/
        参数非法（`?type=` 非 4 类之一 → 整页错误态 + 返回）/ 未登录（守卫 → SC-03）/
        离线（**写操作全部禁用** + 离线条 + 明确提示，且**不进入新建表单**）/
        409（同类型在用目标已存在 → 中性提示 + 重新加载进入编辑态）/ 422（字段级红字，保留输入）/
        软提示（服务端 `SOFT_WARNING` → 校验条 + 确认后原样重发并带 `acknowledge_warnings: true`）/
        提交防重（点击即 `loading` + `disabled`；**G 模块不接 `Idempotency-Key`** ⇒ 靠禁用防重）/
        高风险确认（删除：C-12 `mode="danger"`，不可点遮罩关闭）。
        空态 → **N/A**（表单页，S1-C 明确「不适用」）。

      ★ 离线数据来源：本页本身**不写缓存**；离线时读 SC-12 已写入的 `cache.goal`（只读），
        用于"只读查看已有目标"。取不到就按"无数据"处理，**不伪造**任何目标。
    -->
    <view class="gedit">
        <view class="gedit__body">
            <view class="gedit__inner">
                <!-- 离线提示条（写操作禁用；数据可能来自本地缓存，故只声明"不可编辑"） -->
                <view v-if="offline" class="gedit__block">
                    <AppOfflineBar variant="offline" text="当前离线，编辑功能需要联网后使用" />
                </view>

                <!-- 参数非法（`?type=` 非 4 类之一）→ 整页错误态，不静默降级成"另一类目标" -->
                <view v-if="invalidType" class="gedit__block">
                    <AppErrorState
                        variant="full"
                        text="目标类型不正确，请从目标页进入"
                        retry-text="返回目标页"
                        @retry="goBackToGoal"
                    />
                </view>

                <!-- 载入中 / 载入失败 -->
                <view v-else-if="loading" class="gedit__block">
                    <AppSkeleton variant="profile" />
                </view>

                <view v-else-if="loadError" class="gedit__block">
                    <AppErrorState variant="full" :text="loadError" @retry="reload" />
                </view>

                <!-- 离线且无任何本地数据 ⇒ 明确"不可新建"，引导回目标页（不展示空表单） -->
                <view v-else-if="offlineBlocked" class="gedit__block">
                    <AppEmpty
                        variant="common"
                        text="当前离线，无法新建目标"
                        action-text="返回目标页"
                        @action="goBackToGoal"
                    />
                </view>

                <template v-else>
                    <!-- ② 类型选择（**仅新建模式**；编辑模式下类型不可改：G-03 传 goal_type 即 422） -->
                    <AppCard v-if="!editing" title="目标类型" class="gedit__block">
                        <view
                            v-for="(t, i) in typeOptions"
                            :key="t.value"
                            hover-class="none"
                            @tap="onTypeSelect(t)"
                        >
                            <AppListRow
                                :icon="t.value"
                                :title="t.label"
                                :value="typeRowValue(t)"
                                :disabled="t.exists"
                                :last="i === typeOptions.length - 1"
                            />
                        </view>
                    </AppCard>

                    <!-- ③ 目标值 -->
                    <AppCard title="目标值" class="gedit__block">
                        <!-- 运动目标：先选计量口径（二选一），再填**一个**目标值 -->
                        <template v-if="form.goal_type === 'sport'">
                            <view
                                v-for="(a, i) in sportAttrOptions"
                                :key="a.value"
                                hover-class="none"
                                @tap="onAttrSelect(a)"
                            >
                                <AppListRow
                                    :title="a.label"
                                    :value="a.value === form.attr_1 ? '已选择' : ''"
                                    :disabled="offline"
                                    :last="i === sportAttrOptions.length - 1"
                                />
                            </view>
                        </template>

                        <AppInput
                            label="目标值"
                            :model-value="form.target_value"
                            type="digit"
                            :unit="unitCn"
                            :placeholder="valuePlaceholder"
                            :error="valueError"
                            :disabled="offline"
                            @update:model-value="onValueInput"
                        />
                        <text v-if="fieldErrors.attr_1" class="gedit__field-error">{{ fieldErrors.attr_1 }}</text>
                    </AppCard>

                    <!-- ④ 周期 -->
                    <AppCard title="周期" class="gedit__block">
                        <!-- 裁定 ①：开始日期只读显示今天 -->
                        <AppListRow
                            title="开始日期"
                            :value="today"
                            :last="form.goal_type !== 'weight'"
                        />
                        <!-- 目标日期：**仅体重目标可填**（契约：其他类型传值 → 422） -->
                        <AppDatePicker
                            v-if="form.goal_type === 'weight'"
                            label="目标日期"
                            placeholder="可不填"
                            :model-value="form.target_date"
                            :start="today"
                            :error="fieldErrors.target_date || ''"
                            :disabled="offline"
                            @update:model-value="onTargetDateChange"
                        />
                    </AppCard>

                    <!-- ⑤ 状态操作（**仅编辑模式**） -->
                    <AppCard v-if="editing" title="状态" class="gedit__block">
                        <view hover-class="none" @tap="onTogglePause">
                            <AppButton
                                :label="suspended ? '恢复' : '暂停'"
                                type="secondary"
                                block
                                :disabled="actionDisabled"
                                :loading="pausing"
                            />
                        </view>
                        <text class="gedit__op-hint">{{ pauseHintText }}</text>
                    </AppCard>

                    <!-- 软提示（服务端 SOFT_WARNING：本次未写入，确认后原样重发） -->
                    <view class="gedit__block">
                        <AppValidateBar :visible="softVisible" level="soft" :text="softText" />
                    </view>

                    <!-- ⑥ 保存 -->
                    <view class="gedit__block" hover-class="none" @tap="onSave">
                        <AppButton
                            :label="saveLabel"
                            block
                            :disabled="saving || offline"
                            :loading="saving"
                        />
                    </view>

                    <!-- ⑦ 删除（**仅编辑模式**；A 类页导航栏放不下 ⇒ 照 SC-09 先例落内容区底部） -->
                    <view v-if="editing" class="gedit__block">
                        <view hover-class="none" @tap="onDeleteTap">
                            <AppButton
                                label="删除目标"
                                type="danger"
                                block
                                :disabled="actionDisabled"
                            />
                        </view>
                        <text v-if="offline" class="gedit__offline-hint">{{ offlineActionText }}</text>
                    </view>
                </template>
            </view>
        </view>

        <!-- 高风险确认：删除目标（C-12 danger，不可点遮罩关闭） -->
        <AppModal
            :show="deleteVisible"
            mode="danger"
            title="删除这个目标？"
            content="删除后无法恢复；历史完成度记录也将一并移除"
            confirm-text="删除"
            cancel-text="取消"
            :confirm-disabled="deleting"
            @update:show="onDeleteShow"
            @confirm="doDelete"
        />

        <!-- 轻提示宿主 -->
        <AppToast />

        <!-- 开发环境页面预览器（仅 H5 非生产环境渲染；生产构建下为空节点） -->
        <DevPagePreviewer />
    </view>
</template>

<script>
import AppCard from '../../components/AppCard.vue'
import AppButton from '../../components/AppButton.vue'
import AppListRow from '../../components/AppListRow.vue'
import AppInput from '../../components/AppInput.vue'
import AppDatePicker from '../../components/AppDatePicker.vue'
import AppModal from '../../components/AppModal.vue'
import AppValidateBar from '../../components/AppValidateBar.vue'
import AppToast from '../../components/AppToast.vue'
import AppSkeleton from '../../components/AppSkeleton.vue'
import AppErrorState from '../../components/AppErrorState.vue'
import AppOfflineBar from '../../components/AppOfflineBar.vue'
import AppEmpty from '../../components/AppEmpty.vue'
// 开发环境专用页面预览器（**仅 H5 + 非生产**生效；不注册进 `pages.json`、不计入 25 页）
import DevPagePreviewer from '../../components/DevPagePreviewer.vue'

import { ROUTES, navigateBack, reLaunch, requireLogin } from '../../utils/route'
import {
    fetchGoals,
    createGoal,
    updateGoal,
    pauseGoal,
    resumeGoal,
    deleteGoal,
    GOAL_TYPE_ORDER,
    unitOf
} from '../../api/goals'
import { goalLabel, goalUnitLabel } from '../../utils/metrics'
import { errorText, fieldErrorText } from '../../utils/request'
import { CACHE_KEYS, loadCache } from '../../utils/cache'
import { showToast } from '../../utils/toast'
import { isOnline } from '../../utils/network'
import { todayString, toNumber } from '../../utils/validate'

/** `sport` 的两种计量口径（**二选一**，与后端 `goal_service.SPORT_ATTRS` 一一对应） */
const SPORT_ATTR_OPTIONS = [
    { value: 'count', label: '周次数' },
    { value: 'min', label: '周分钟' }
]

/**
 * 目标值输入框的占位 —— **仅格式示例，不是推荐值**
 * （红线：目标一律用户自设，`DESIGN.md §8` / 后端 `GoalCreateSchema` 明确"不接受任何系统推荐值参数"）。
 */
const VALUE_PLACEHOLDER = {
    weight: '如 65',
    water: '如 2000',
    sleep: '如 8'
}
const SPORT_PLACEHOLDER = {
    count: '如 3',
    min: '如 150'
}

/** 目标值本地预检文案（**只判"必填 + 大于 0"**；硬拦截区间 / 软提示区间一律交服务端） */
const VALUE_REQUIRED_TEXT = '请输入目标值'
const VALUE_POSITIVE_TEXT = '目标值需为大于 0 的数值'

/** 离线时写操作的统一提示（S1-C 网络矩阵） */
const OFFLINE_ACTION_TEXT = '当前网络不可用，请联网后操作'

/** `409 GOAL_TYPE_EXISTS` 的提示（S1-C SC-13 失败态口径：中性陈述 + 给出下一步） */
const CONFLICT_TEXT = '该类型目标已存在，请编辑现有目标'

/**
 * 「操作成功」提示后**延迟返回**的毫秒数。
 *
 * ★ 为什么不能立即返回：`AppToast` 的宿主是**页面级**的，页面卸载会
 *   `unregisterToastHandler()`（全局 handler 置空）⇒ 立刻 `navigateBack()` 会让刚弹出的
 *   提示**根本没机会显示**。留出 `--d-toast`(2000ms) 的一半左右再返回，用户能读到结果。
 */
const BACK_DELAY_MS = 800

/** `?type=` 归一化：只接受 4 类之一，其余 → 空串（由调用方判定是否"非法参数"） */
function normalizeType(raw) {
    const text = raw === null || raw === undefined ? '' : String(raw).trim()
    return GOAL_TYPE_ORDER.indexOf(text) >= 0 ? text : ''
}

/**
 * 把服务端软提示载荷转成一句中性文案（**只陈述需要确认的事实，不含任何评价**）。
 * @param {object} data `SOFT_WARNING` 的 `data`（`{ requires_confirm, warnings[] }`）
 */
function softTextOf(data) {
    const list = data && data.warnings && data.warnings.length ? data.warnings : []
    if (!list.length) {
        return '目标值超出常见范围，请确认是否输错'
    }
    const first = list[0]
    if (first && first.message) {
        return String(first.message)
    }
    return '目标值超出常见范围，请确认是否输错'
}

export default {
    components: {
        AppCard: AppCard,
        AppButton: AppButton,
        AppListRow: AppListRow,
        AppInput: AppInput,
        AppDatePicker: AppDatePicker,
        AppModal: AppModal,
        AppValidateBar: AppValidateBar,
        AppToast: AppToast,
        AppSkeleton: AppSkeleton,
        AppErrorState: AppErrorState,
        AppOfflineBar: AppOfflineBar,
        AppEmpty: AppEmpty,
        DevPagePreviewer: DevPagePreviewer
    },
    data: function () {
        return {
            /** 今天（`YYYY-MM-DD`，本地墙上时间口径）—— 裁定 ①：开始日期只读显示今天 */
            today: '',
            /** `?type=` 归一化后的类型（空串 = 未传 / 非法） */
            typeParam: '',
            /** 参数非法（明确传了非 4 类的 `type`） */
            invalidType: false,

            /** G-01 载入中 / 载入失败文案 */
            loading: true,
            loadError: '',

            /** 在用目标映射：`goal_type` → G-01 的元素（含 `id` / `status` / `target_value` …） */
            existing: {},

            /** 表单（`target_value` 保存为**字符串**：与 `AppInput` 的 `modelValue` 同型，提交前再转数） */
            form: {
                goal_type: '',
                target_value: '',
                attr_1: 'min',
                target_date: ''
            },

            /** 本地预检 / 服务端字段级错误 */
            valueError: '',
            fieldErrors: {},

            /** 软提示（服务端 `SOFT_WARNING`） */
            softVisible: false,
            softText: '',

            /** 写操作状态（用于按钮禁用与 loading） */
            saving: false,
            pausing: false,
            deleting: false,
            deleteVisible: false,

            /** 离线 */
            offline: false,

            networkHandler: null,
            leaveTimer: null
        }
    },
    computed: {
        /** 当前类型的在用目标（有 ⇒ 编辑模式） */
        currentGoal: function () {
            return this.existing[this.form.goal_type] || null
        },
        /** 是否编辑模式（**注意**：由"该类型是否已有在用目标"决定，不由传参决定） */
        editing: function () {
            return !!this.currentGoal
        },
        /** 导航栏标题（A 类系统导航栏，动态设置） */
        title: function () {
            return this.editing ? '编辑目标' : '新建目标'
        },
        /** 该目标是否已暂停（`status` 是**数字** 0/1，不是英文 `status_text`） */
        suspended: function () {
            const goal = this.currentGoal
            if (!goal) {
                return false
            }
            return Number(goal.status) === 0
        },
        /** 4 类类型选项（已存在 ⇒ `exists` ⇒ 置灰 + 「已存在」） */
        typeOptions: function () {
            const self = this
            return GOAL_TYPE_ORDER.map(function (type) {
                return {
                    value: type,
                    label: goalLabel(type),
                    exists: !!self.existing[type]
                }
            })
        },
        sportAttrOptions: function () {
            return SPORT_ATTR_OPTIONS
        },
        /** 目标值输入框的单位后缀（中文；随 sport 的计量口径变化） */
        unitCn: function () {
            const attr = this.form.goal_type === 'sport' ? this.form.attr_1 : null
            return goalUnitLabel(unitOf(this.form.goal_type, attr))
        },
        valuePlaceholder: function () {
            if (this.form.goal_type === 'sport') {
                return SPORT_PLACEHOLDER[this.form.attr_1] || ''
            }
            return VALUE_PLACEHOLDER[this.form.goal_type] || ''
        },
        /** 写操作（暂停 / 恢复 / 删除 / 保存）统一禁用条件 */
        actionDisabled: function () {
            return this.offline || this.saving || this.pausing || this.deleting
        },
        /** 保存按钮文案：软提示出现后，再点即为"确认并保存"（原样重发 + `acknowledge_warnings`） */
        saveLabel: function () {
            return this.softVisible ? '确认并保存' : '保存'
        },
        pauseHintText: function () {
            return this.suspended ? '恢复后重新计入完成度统计' : '暂停后不计入完成度统计'
        },
        offlineActionText: function () {
            return OFFLINE_ACTION_TEXT
        },
        /**
         * 离线且**无本地数据**可读 ⇒ 不展示空表单（避免让人以为"可以为某类型新建目标"）。
         * 仅当明确传了 `type` 且本地缓存里有该类型时才允许只读查看。
         */
        offlineBlocked: function () {
            if (!this.offline) {
                return false
            }
            if (!this.typeParam) {
                return true
            }
            return !this.existing[this.typeParam]
        }
    },
    onLoad: function (query) {
        // 未登录守卫（S1-C SC-13：需登录）
        if (!requireLogin()) {
            return
        }

        this.today = todayString()

        const rawType = query && query.type ? String(query.type) : ''
        this.typeParam = normalizeType(rawType)
        if (rawType && !this.typeParam) {
            // 明确传了非法类型 ⇒ 整页错误态（**不静默降级**，否则会以为打开的是"另一个目标"）
            this.invalidType = true
            this.loading = false
            return
        }

        const self = this
        this.networkHandler = function (res) {
            self.offline = !(res && res.isConnected)
        }
        uni.onNetworkStatusChange(this.networkHandler)
        isOnline().then(function (online) {
            self.offline = !online
        })

        this.load()
    },
    onUnload: function () {
        if (this.leaveTimer) {
            clearTimeout(this.leaveTimer)
            this.leaveTimer = null
        }
        if (this.networkHandler) {
            uni.offNetworkStatusChange(this.networkHandler)
            this.networkHandler = null
        }
    },
    methods: {
        /* ───────────── 载入 ───────────── */

        /**
         * 载入 G-01，确定模式与初始表单。
         *
         * ★ 离线兜底：读 SC-12 写入的 `cache.goal`（**只读**，本页不写缓存、不做写回）。
         */
        load: function () {
            const self = this
            this.loading = true
            this.loadError = ''

            const cached = loadCache(CACHE_KEYS.GOAL)
            const cachedRows = cached && cached.data && cached.data.items ? cached.data.items : null

            return fetchGoals().then(function (res) {
                const rows = (res && res.data && res.data.items) || []
                self.offline = false
                self.applyRows(rows)
            }, function (err) {
                if (err && err.isNetwork) {
                    // 离线：能用本地缓存就只读渲染；否则按"无数据"处理（**绝不伪造目标**）
                    self.offline = true
                    self.applyRows(cachedRows || [])
                    return
                }
                self.loading = false
                self.loadError = errorText(err)
            })
        },

        /** 手动重试 / 写操作后刷新（同时清掉软提示与字段错误，避免残留过期提示） */
        reload: function () {
            this.softVisible = false
            this.softText = ''
            this.valueError = ''
            this.fieldErrors = {}
            this.load()
        },

        /** 落地一次载入结果：建映射 → 定模式 → 关加载 */
        applyRows: function (rows) {
            const map = {}
            const list = rows || []
            for (let i = 0; i < list.length; i++) {
                const row = list[i]
                if (row && row.goal_type) {
                    map[row.goal_type] = row
                }
            }
            this.existing = map
            this.applyMode()
            this.loading = false
        },

        /**
         * 依据 `?type=` 与"哪些类型已有在用目标"决定模式与初始表单。
         *   · `?type=` 指向的类型**已存在** → 编辑模式（预填该目标当前值）；
         *   · `?type=` 指向的类型**不存在** / 未传 → 新建模式，默认选中第一个尚不存在的类型。
         */
        applyMode: function () {
            const wanted = this.typeParam
            if (wanted) {
                this.form.goal_type = wanted
            } else {
                this.form.goal_type = this.firstFreeType() || GOAL_TYPE_ORDER[0]
            }

            const goal = this.existing[this.form.goal_type]
            if (goal) {
                this.form.target_value = goal.target_value === null || goal.target_value === undefined
                    ? ''
                    : String(goal.target_value)
                this.form.attr_1 = goal.attr_1 ? String(goal.attr_1) : SPORT_ATTR_OPTIONS[1].value
                this.form.target_date = goal.target_date ? String(goal.target_date) : ''
            }

            // A 类系统导航栏标题（模式确定后才能定）
            uni.setNavigationBarTitle({ title: this.title })
        },

        /** 第一个"尚无在用目标"的类型（未传 `?type=` 时作为默认选中项） */
        firstFreeType: function () {
            for (let i = 0; i < GOAL_TYPE_ORDER.length; i++) {
                if (!this.existing[GOAL_TYPE_ORDER[i]]) {
                    return GOAL_TYPE_ORDER[i]
                }
            }
            return ''
        },

        /* ───────────── 表单交互 ───────────── */

        /** 类型选择（**仅新建模式**；已存在的类型置灰不可选 —— 只能去编辑它） */
        onTypeSelect: function (item) {
            if (!item || item.exists || item.value === this.form.goal_type) {
                return
            }
            this.form.goal_type = item.value
            // 切换类型必须清空目标值：单位与量纲随类型变化，沿用旧值会造成口径错配
            this.form.target_value = ''
            this.form.attr_1 = SPORT_ATTR_OPTIONS[1].value
            this.form.target_date = ''
            this.valueError = ''
            this.fieldErrors = {}
            this.softVisible = false
        },

        /** 运动口径二选一（切换时同样清空目标值：周次数与周分钟量纲不同） */
        onAttrSelect: function (item) {
            if (this.offline || !item || item.value === this.form.attr_1) {
                return
            }
            this.form.attr_1 = item.value
            this.form.target_value = ''
            this.valueError = ''
            this.softVisible = false
        },

        onValueInput: function (value) {
            this.form.target_value = value === null || value === undefined ? '' : String(value)
            // 用户重新输入即清掉旧错误，避免"改了还红着"
            this.valueError = ''
            this.fieldErrors = {}
            this.softVisible = false
        },

        onTargetDateChange: function (value) {
            this.form.target_date = value ? String(value) : ''
            this.fieldErrors = {}
            this.softVisible = false
        },

        /** 类型行右侧文案：已存在（置灰）优先于"已选择" */
        typeRowValue: function (item) {
            if (item.exists) {
                return '已存在'
            }
            return item.value === this.form.goal_type ? '已选择' : ''
        },

        /* ───────────── 保存 ───────────── */

        /** 主按钮：软提示已显示时，本次点击等同"确认并保存" */
        onSave: function () {
            this.doSave(this.softVisible)
        },

        /**
         * 提交（新建 → G-02；编辑 → G-03）。
         * @param {boolean} acknowledge 是否带 `acknowledge_warnings: true`（软提示确认后重发）
         */
        doSave: function (acknowledge) {
            const self = this
            if (this.offline) {
                showToast('info', OFFLINE_ACTION_TEXT)
                return
            }
            if (this.saving || this.pausing || this.deleting) {
                return
            }
            if (!this.validateForm()) {
                return
            }

            this.saving = true
            this.valueError = ''
            this.fieldErrors = {}

            const value = toNumber(this.form.target_value)
            const goal = this.currentGoal
            const task = goal
                ? updateGoal(goal.id, this.patchPayload(value, acknowledge))
                : createGoal(this.createPayload(this.form.goal_type, value, acknowledge))

            return task.then(function (res) {
                self.saving = false
                if (res && res.code === 'SOFT_WARNING') {
                    // 服务端要求确认（**本次未写入**）：展示校验条，等用户"确认并保存"后原样重发
                    self.softVisible = true
                    self.softText = softTextOf(res.data)
                    return
                }
                self.softVisible = false
                showToast('success', '已保存')
                self.leaveLater()
            }, function (err) {
                self.saving = false
                self.handleWriteError(err)
            })
        },

        /** 本地预检：**只判"必填 + 大于 0"**；区间判断（硬拦截 / 软提示）一律交服务端 */
        validateForm: function () {
            const raw = this.form.target_value
            if (raw === '' || raw === null || raw === undefined) {
                this.valueError = VALUE_REQUIRED_TEXT
                return false
            }
            const value = toNumber(raw)
            if (value === null || isNaN(value) || value <= 0) {
                this.valueError = VALUE_POSITIVE_TEXT
                return false
            }
            return true
        },

        /** 新建请求体（G-02；`unit` / `period_type` 由 `api/goals.js` 按服务端口径推导） */
        createPayload: function (type, value, acknowledge) {
            const payload = {
                goal_type: type,
                target_value: value,
                // 裁定 ①：开始日期只读显示今天（不开放修改）
                start_date: this.today,
                acknowledge_warnings: acknowledge === true
            }
            if (type === 'sport') {
                payload.attr_1 = this.form.attr_1
            }
            if (type === 'weight') {
                if (this.form.target_date) {
                    payload.target_date = this.form.target_date
                }
                // 裁定 ②：起始体重由服务端取"最近一条体重记录"（不设输入框、不估算）
                payload.auto_start_weight = true
            }
            return payload
        },

        /**
         * 修改请求体（G-03，**局部更新**）。
         *
         * ★ 只携带"本类型表单真正渲染出的字段"：
         *   **绝不出现** `goal_type` / `start_weight_kg`（出现即 422）；
         *   `target_date` 显式传 `null` 表示"清空"（省略 = 保持原值）。
         */
        patchPayload: function (value, acknowledge) {
            const type = this.form.goal_type
            const payload = {
                target_value: value,
                acknowledge_warnings: acknowledge === true
            }
            if (type === 'sport') {
                payload.attr_1 = this.form.attr_1
            }
            if (type === 'weight') {
                payload.target_date = this.form.target_date ? this.form.target_date : null
            }
            return payload
        },

        /** 写操作失败的统一处理：409 → 重新加载进编辑态；422 → 落到对应字段；其余 → 中性提示 */
        handleWriteError: function (err) {
            const code = err && err.code ? err.code : ''
            if (code === 'GOAL_TYPE_EXISTS') {
                showToast('error', CONFLICT_TEXT)
                this.reload()
                return
            }
            const valueMsg = fieldErrorText(err, 'target_value')
            if (valueMsg) {
                this.valueError = valueMsg
                return
            }
            const dateMsg = fieldErrorText(err, 'target_date')
            if (dateMsg) {
                this.fieldErrors = { target_date: dateMsg }
                return
            }
            const attrMsg = fieldErrorText(err, 'attr_1')
            if (attrMsg) {
                this.fieldErrors = { attr_1: attrMsg }
                return
            }
            showToast('error', errorText(err))
        },

        /* ───────────── 暂停 / 恢复 ───────────── */

        onTogglePause: function () {
            const self = this
            const goal = this.currentGoal
            if (!goal) {
                return
            }
            if (this.offline) {
                showToast('info', OFFLINE_ACTION_TEXT)
                return
            }
            if (this.actionDisabled) {
                return
            }

            // 操作前的状态决定本次是"暂停"还是"恢复"（成功提示用）
            const wasSuspended = this.suspended
            this.pausing = true
            const task = wasSuspended ? resumeGoal(goal.id) : pauseGoal(goal.id)

            return task.then(function () {
                self.pausing = false
                // 后端幂等：已处于目标状态时会回 changed=false 且**不报错** ⇒ 提示不区分
                showToast('success', wasSuspended ? '已恢复' : '已暂停，不计入完成度')
                self.reload()
            }, function (err) {
                self.pausing = false
                if (err && err.code === 'GOAL_TYPE_EXISTS') {
                    showToast('error', CONFLICT_TEXT)
                    return
                }
                showToast('error', errorText(err))
            })
        },

        /* ───────────── 删除 ───────────── */

        onDeleteTap: function () {
            if (this.offline) {
                showToast('info', OFFLINE_ACTION_TEXT)
                return
            }
            if (this.actionDisabled) {
                return
            }
            this.deleteVisible = true
        },

        onDeleteShow: function (value) {
            this.deleteVisible = value === true
        },

        doDelete: function () {
            const self = this
            const goal = this.currentGoal
            if (!goal) {
                this.deleteVisible = false
                return
            }
            if (this.offline) {
                this.deleteVisible = false
                showToast('info', OFFLINE_ACTION_TEXT)
                return
            }
            if (this.deleting) {
                return
            }

            this.deleting = true
            return deleteGoal(goal.id).then(function () {
                self.deleting = false
                self.deleteVisible = false
                showToast('success', '已删除')
                self.leaveLater()
            }, function (err) {
                self.deleting = false
                self.deleteVisible = false
                if (err && (err.code === 'RESOURCE_NOT_FOUND' || err.httpStatus === 404)) {
                    // 重复删除 → 404：与本页意图一致，按"已删除"处理（不把 404 当错误惊吓用户）
                    showToast('success', '已删除')
                    self.leaveLater()
                    return
                }
                showToast('error', errorText(err))
            })
        },

        /* ───────────── 出口 ───────────── */

        /** 提示后延迟返回（原因见 `BACK_DELAY_MS` 注释） */
        leaveLater: function () {
            const self = this
            if (this.leaveTimer) {
                clearTimeout(this.leaveTimer)
            }
            this.leaveTimer = setTimeout(function () {
                self.leaveTimer = null
                self.goBackToGoal()
            }, BACK_DELAY_MS)
        },

        /** 回 SC-12：有返回栈则返回（其 `onShow` 会自动刷新）；无栈（预览器等）则清栈直达 */
        goBackToGoal: function () {
            const pages = getCurrentPages()
            if (pages && pages.length > 1) {
                navigateBack()
                return
            }
            reLaunch(ROUTES.GOAL)
        }
    }
}
</script>

<style scoped lang="scss">
.gedit {
    min-height: 100vh;
    background-color: var(--s-page);
}

/* A 类系统导航栏占位由平台负责，此处只留内容区节奏 */
.gedit__body {
    padding-top: var(--page-pad-t);
    padding-bottom: var(--page-pad-b);
}

/* 内容最大宽居中（DESIGN.md §10.4③）+ 唯一水平边距来源 --gutter */
.gedit__inner {
    max-width: var(--content-max);
    margin-left: auto;
    margin-right: auto;
    padding-left: var(--gutter);
    padding-right: var(--gutter);
}

.gedit__block {
    margin-bottom: var(--card-gap);
}

/* 字段级错误（服务端 422 的 `errors[].message`，中性技术文案） */
.gedit__field-error {
    display: block;
    margin-top: var(--sp-2);
    font-size: var(--fs-caption);
    line-height: $lh-caption;
    color: var(--c-danger);
    letter-spacing: 0;
}

/* 状态提示：说明暂停 / 恢复对统计口径的影响（中性陈述，不含评价） */
.gedit__op-hint {
    display: block;
    margin-top: var(--sp-3);
    font-size: var(--fs-caption);
    line-height: $lh-caption;
    color: var(--t-3);
    letter-spacing: 0;
}

/* 离线时的写操作说明 */
.gedit__offline-hint {
    display: block;
    margin-top: var(--sp-2);
    font-size: var(--fs-caption);
    line-height: $lh-caption;
    color: var(--t-3);
    letter-spacing: 0;
}
</style>
