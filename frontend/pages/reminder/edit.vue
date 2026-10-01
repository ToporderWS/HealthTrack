<template>
    <!--
      SC-15 提醒编辑页（pages/reminder/edit?id=）
      依据：S1-C §二 SC-15（① 顶部栏 / ② 类型 5 类 / ③ 多时间点 / ④ 重复规则 / ⑤ 类型专属 /
            ⑥ 权限引导弹窗 / ⑦ 保存 / ⑧ 底部说明）｜DESIGN.md §8（C-02/C-03/C-08/C-12/C-19/C-20/C-30）/
            §10.3（**A 类系统导航栏**）/ §11 / §12 / §13

      顶栏：**A 类系统导航栏**，标题由 `uni.setNavigationBarTitle` 动态设置（「新建提醒」/「编辑提醒」）；
            原型 ① 的【删除】在导航栏放不下 ⇒ **照 SC-09 / SC-13 先例落内容区底部**（危险色）。

      模式判定：**有 `?id=` 且该条存在 ⇒ 编辑模式；否则新建模式**。
        ★ 如实登记：「`?id=` 指向不存在的提醒」**不构造产品状态**（冻结清单里 SC-15 ⑩ 明确"空状态不适用"，
          也没有对应的错误态条目）⇒ 按**新建模式**打开。该状态**无法从产品路径到达**
          （SC-14 只会传真实存在 id），只会由外部构造 URL 或预览器产生。

      数据来源：**纯本地，0 个接口**（S1-C §五 / S1-D：提醒表 0 张、无提醒接口）⇒
        本页**不发任何请求**，也没有服务端加载 / 失败 / 离线分支（SC-15 ⑭：完全可用，保存不需要网络）。

      状态覆盖（DESIGN.md §13 底线清单）：
        正常 → 表单完整可填；
        空 → **N/A**（S1-C SC-15 ⑩ 明确「不适用」—— 表单页没有"无数据"形态）；
        加载 → **N/A**（本地同步读取；S1-C SC-15 ⑪「无网络加载（本地读取）」，不设骨架屏）；
        失败 → 字段级提示（未设时间 / 自定义标题为空 / 未选周几 / 未绑定指标）+ 保存失败 Toast；
        未登录 → 路由守卫 → SC-03；
        离线 → **完全可用**（不置灰、不提示联网，SC-15 ⑭）；
        高风险确认 → 删除提醒走 C-12 `mode="danger"` 二次确认（文案取自 SC-14 ⑮）；
        提交防重 → `saving` / `deleting` 双闸 + 按钮 `disabled` + `loading`（**0 请求 ⇒ 无幂等键**）。

      ★ 如实登记（本轮不做、不伪造）：
        ① 权限引导弹窗按 ⑥「**首次创建时**」触发：用一个本地标记记录"是否已引导过"；
           [去设置] / [暂不] **都继续保存**（SC-15 ⑫③：权限被拒 ⇒ 保存仍成功）。
        ② H5 下 `canNotify()` 恒 false（裁定 A + 裁定 4）⇒ 顶部黄条常驻，且**保存成功文案恒为**
           「提醒已保存，但需开启通知权限才会生效」（SC-15 ⑯ 的权限分支）。这是裁定的必然结果，不是缺陷。
        ③ 时间选择用 uni 内置 `<picker mode="time">`（**页面内实现**）：
           `DESIGN.md §8` 的 C-06 `AppDatePicker` 只登记 `date` / `datetime` 两种 mode，**没有 time-only**，
           而扩展 C-06 属**未授权文件**（本批授权清单不含它）⇒ 按 `AppDatePicker` 内部的同一技术路线
           （它自身也用 `<picker mode="time">`）在本页落一个时间选择行，**不新增组件、不改冻结组件**。
    -->
    <view class="redit">
        <view class="redit__body">
            <view class="redit__inner">
                <!-- 通知权限引导条（SC-15 ⑫③：权限被拒时顶部黄条引导） -->
                <view v-if="permissionVisible" class="redit__block">
                    <NotifyPermissionBar visible @action="onPermissionAction" />
                </view>

                <!-- ② 提醒类型（5 类；**编辑模式下同样可改**，见文件尾「决策登记 D-1」） -->
                <AppCard title="提醒类型" class="redit__block">
                    <view
                        v-for="(t, i) in typeOptions"
                        :key="t"
                        hover-class="none"
                        @tap="onTypeSelect(t)"
                    >
                        <AppListRow
                            :title="typeLabel(t)"
                            :value="t === form.type ? '已选择' : ''"
                            :last="i === typeOptions.length - 1"
                        />
                    </view>
                </AppCard>

                <!-- ③ 提醒时间（多时间点，可删；上限 5 个 —— 裁定 ⑤） -->
                <AppCard title="提醒时间" class="redit__block">
                    <view v-for="(t, i) in form.times" :key="'t' + i" class="redit__time-row">
                        <picker
                            class="redit__time-picker"
                            mode="time"
                            :value="t"
                            @change="onTimeChange(i, $event)"
                        >
                            <view class="redit__time-value" hover-class="redit__time-value--press" :hover-start-time="0" :hover-stay-time="80">
                                <text class="redit__time-text">{{ t }}</text>
                            </view>
                        </picker>
                        <view class="redit__time-del" hover-class="redit__link--press" :hover-start-time="0" :hover-stay-time="80" @tap="onTimeRemove(i)">
                            <text class="redit__link">删除</text>
                        </view>
                    </view>

                    <!-- 空时间点时的字段提示（文案取自 SC-15 ⑫①，**只在提交后显示**，不提前报错） -->
                    <text v-if="errors.times" class="redit__field-error">{{ errors.times }}</text>

                    <view class="redit__add" hover-class="none" @tap="onTimeAdd">
                        <AppButton label="添加时间点" type="secondary" size="m" block :disabled="timesFull" />
                    </view>
                    <text v-if="timesFull" class="redit__hint">{{ maxTimesHint }}</text>
                </AppCard>

                <!-- ④ 重复规则（每天 / 工作日 / 自定义；自定义 ⇒ 7 个周几 chip） -->
                <AppCard title="重复规则" class="redit__block">
                    <AppSegmented
                        :model-value="form.repeat"
                        :options="repeatOptions"
                        @update:model-value="onRepeatChange"
                    />

                    <view v-if="form.repeat === 'custom'" class="redit__chips">
                        <view
                            v-for="d in weekdays"
                            :key="d"
                            class="redit__chip"
                            :class="{ 'redit__chip--on': isDayOn(d), 'redit__chip--last': d === lastWeekday }"
                            hover-class="redit__chip--press"
                            :hover-start-time="0"
                            :hover-stay-time="80"
                            @tap="onDayToggle(d)"
                        >
                            <text class="redit__chip-text" :class="{ 'redit__chip-text--on': isDayOn(d) }">{{ dayLabel(d) }}</text>
                        </view>
                    </view>

                    <text v-if="errors.weekdays" class="redit__field-error">{{ errors.weekdays }}</text>
                </AppCard>

                <!-- ⑤ 类型专属 -->
                <AppCard v-if="typeSectionTitle" :title="typeSectionTitle" class="redit__block">
                    <!-- 测量类：绑定指标（血压 / 血糖 / 体重） -->
                    <template v-if="form.type === 'measure'">
                        <view
                            v-for="(m, i) in measureOptions"
                            :key="m"
                            hover-class="none"
                            @tap="onMetricSelect(m)"
                        >
                            <AppListRow
                                :title="metricName(m)"
                                :value="m === form.metric ? '已选择' : ''"
                                :last="i === measureOptions.length - 1"
                            />
                        </view>
                        <text v-if="errors.metric" class="redit__field-error">{{ errors.metric }}</text>
                    </template>

                    <!-- 睡眠类：睡前 N 分钟 -->
                    <template v-else-if="form.type === 'sleep'">
                        <view
                            v-for="(n, i) in sleepOptions"
                            :key="n"
                            hover-class="none"
                            @tap="onSleepSelect(n)"
                        >
                            <AppListRow
                                :title="sleepLabel(n)"
                                :value="n === form.sleepBeforeMin ? '已选择' : ''"
                                :last="i === sleepOptions.length - 1"
                            />
                        </view>
                    </template>

                    <!-- 自定义：提醒标题 -->
                    <template v-else>
                        <AppInput
                            label="提醒标题"
                            :model-value="form.title"
                            placeholder="如：量血压前静坐"
                            :maxlength="titleMaxlength"
                            :error="errors.title || ''"
                            @update:model-value="onTitleInput"
                        />
                    </template>
                </AppCard>

                <!-- ⑦ 保存 -->
                <view class="redit__block" hover-class="none" @tap="onSave">
                    <AppButton :label="saveLabel" block :disabled="saving" :loading="saving" />
                </view>

                <!-- ① [删除]（仅编辑模式；A 类页导航栏放不下 ⇒ 照 SC-09 / SC-13 先例落内容区底部） -->
                <view v-if="editing" class="redit__block">
                    <view hover-class="none" @tap="onDeleteTap">
                        <AppButton label="删除提醒" type="danger" block :disabled="deleting" />
                    </view>
                </view>

                <!-- ⑧ 底部说明 -->
                <text class="redit__note">提醒可能延迟或不触发，请以系统实际通知为准</text>
            </view>
        </view>

        <!-- ⑥ 权限引导弹窗（首次创建时；[去设置] / [暂不] 均继续保存） -->
        <AppModal
            :show="permVisible"
            mode="info"
            :title="promptTitle"
            :content="promptContent"
            confirm-text="去设置"
            cancel-text="暂不"
            @update:show="onPromptShow"
            @confirm="onPromptConfirm"
            @cancel="onPromptCancel"
        />

        <!-- 高风险确认：删除提醒（C-12 danger；文案逐字取自 SC-14 ⑮，不可点遮罩关闭） -->
        <AppModal
            :show="deleteVisible"
            mode="danger"
            title="删除这条提醒？"
            content="删除后不再提醒"
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
import AppButton from '../../components/AppButton.vue'
import AppCard from '../../components/AppCard.vue'
import AppListRow from '../../components/AppListRow.vue'
import AppInput from '../../components/AppInput.vue'
import AppSegmented from '../../components/AppSegmented.vue'
import AppModal from '../../components/AppModal.vue'
import AppToast from '../../components/AppToast.vue'
import NotifyPermissionBar from '../../components/NotifyPermissionBar.vue'
import DevPagePreviewer from '../../components/DevPagePreviewer.vue'

import { navigateBack, requireLogin } from '../../utils/route'
import { showToast } from '../../utils/toast'
import { canNotify, cancelLocal, openSystemSettings, syncAll } from '../../utils/notify'
import { KEYS, readRaw, writeRaw } from '../../utils/storage'
import {
    REMINDER_TYPES,
    REPEAT_OPTIONS,
    WEEKDAYS,
    WEEKDAY_LABEL,
    MAX_TIMES,
    MEASURE_METRICS,
    MEASURE_METRIC_LABEL,
    SLEEP_BEFORE_OPTIONS,
    getItem,
    upsertItem,
    removeItem,
    validateItem,
    isValidTime,
    upcomingTriggers
} from '../../utils/reminder'

/** 成功 Toast 停留后再返回（`AppToast` 是页面级宿主，立即返回会把提示一起卸载掉） */
const BACK_DELAY_MS = 800

/** 新建模式的默认时间点个数（0 = 由用户显式添加；**不编造默认时刻**） */
const TITLE_MAXLENGTH = 20

/**
 * 排程同步：**对账式全量重建**（清空 → 按 24h 滚动窗口重排）。
 * 档 1 定档：**不做逐条 diff、不做精确撤销承诺**；失败不阻断交互。
 */
function syncSchedules() {
    try {
        syncAll(upcomingTriggers())
    } catch (e) {
        // 通知通道异常不应影响页面主流程
    }
}

/** 保存成功文案（逐字取自 SC-15 ⑯：普通成功 / 权限未开两分支） */
const TOAST_SAVED = '已保存'
const TOAST_SAVED_NO_PERMISSION = '提醒已保存，但需开启通知权限才会生效'
const TOAST_DELETED = '已删除'
const TOAST_SAVE_FAILED = '保存失败，请重试'
const TOAST_DELETE_FAILED = '删除失败，请重试'
const TOAST_SETTING_UNSUPPORTED = '当前环境暂不支持系统通知设置'

export default {
    components: {
        AppButton: AppButton,
        AppCard: AppCard,
        AppListRow: AppListRow,
        AppInput: AppInput,
        AppSegmented: AppSegmented,
        AppModal: AppModal,
        AppToast: AppToast,
        NotifyPermissionBar: NotifyPermissionBar,
        DevPagePreviewer: DevPagePreviewer
    },
    data: function () {
        return {
            /** 编辑模式（有 ?id= 且该条存在） */
            editing: false,
            itemId: '',

            /** 表单（字段名与 utils/reminder.js 的数据模型一致） */
            form: {
                type: 'water',
                times: [],
                repeat: 'daily',
                weekdays: [],
                metric: '',
                sleepBeforeMin: 30,
                title: ''
            },
            /** 字段级错误（文案逐字取自 SC-15 ⑫） */
            errors: {},

            /** 弹窗与提交闸 */
            permVisible: false,
            deleteVisible: false,
            saving: false,
            deleting: false,

            /** 系统通知能力（H5 恒 false，裁定 A） */
            notifyReady: false,

            typeOptions: REMINDER_TYPES,
            repeatOptions: REPEAT_OPTIONS,
            weekdays: WEEKDAYS,
            lastWeekday: WEEKDAYS[WEEKDAYS.length - 1],
            measureOptions: MEASURE_METRICS,
            sleepOptions: SLEEP_BEFORE_OPTIONS,
            titleMaxlength: TITLE_MAXLENGTH,
            maxTimesHint: '每条提醒最多 ' + MAX_TIMES + ' 个时间点'
        }
    },
    computed: {
        permissionVisible: function () {
            return !this.notifyReady
        },
        saveLabel: function () {
            return this.editing ? '保存修改' : '保存'
        },
        timesFull: function () {
            return this.form.times.length >= MAX_TIMES
        },
        /** ⑤ 的分区标题随类型变化（空串 ⇒ 整块不渲染，避免出现空标题卡） */
        typeSectionTitle: function () {
            if (this.form.type === 'measure') {
                return '测量指标'
            }
            if (this.form.type === 'sleep') {
                return '提前时间'
            }
            if (this.form.type === 'custom') {
                return '提醒标题'
            }
            return ''
        },
        /** 权限弹窗标题（空标题 ⇒ 只显示正文，保持与原型 ⑥ 一致） */
        promptTitle: function () {
            return ''
        },
        promptContent: function () {
            return '需要通知权限才能提醒'
        }
    },
    onLoad: function (options) {
        // 未登录守卫（S1-C SC-15 ⑬：需登录）
        if (!requireLogin()) {
            return
        }
        this.notifyReady = canNotify()

        const id = options && options.id ? String(options.id) : ''
        const item = id ? getItem(id) : null
        if (item) {
            this.editing = true
            this.itemId = item.id
            this.form = {
                type: item.type,
                times: item.times.slice(0),
                repeat: item.repeat,
                weekdays: item.weekdays.slice(0),
                metric: item.metric || '',
                sleepBeforeMin: item.sleepBeforeMin || SLEEP_BEFORE_OPTIONS[1],
                title: item.title || ''
            }
        }
        uni.setNavigationBarTitle({ title: this.editing ? '编辑提醒' : '新建提醒' })
    },
    onUnload: function () {
        if (this.leaveTimer) {
            clearTimeout(this.leaveTimer)
            this.leaveTimer = null
        }
    },
    methods: {
        /* ───────────── 展示辅助 ───────────── */

        typeLabel: function (type) {
            const map = {
                water: '喝水',
                sport: '运动',
                measure: '测量',
                sleep: '睡眠',
                custom: '自定义'
            }
            return map[type] || String(type || '')
        },
        metricName: function (m) {
            return MEASURE_METRIC_LABEL[m] || String(m || '')
        },
        sleepLabel: function (n) {
            return '睡前 ' + n + ' 分钟'
        },
        dayLabel: function (d) {
            return WEEKDAY_LABEL[d] || String(d)
        },
        isDayOn: function (d) {
            return this.form.weekdays.indexOf(d) >= 0
        },

        /* ───────────── 表单交互 ───────────── */

        /**
         * 切换类型。
         * ★ 同时**清空类型专属字段**（与 SC-13 切换口径时清空目标值同一理由：
         *   不同量纲 / 不同语义的值不能跨类型沿用，否则会静默存下错配数据）。
         * 「时间点与重复规则」属类型无关字段 ⇒ **保留**。
         */
        onTypeSelect: function (type) {
            if (this.form.type === type) {
                return
            }
            this.form.type = type
            this.form.metric = ''
            this.form.sleepBeforeMin = SLEEP_BEFORE_OPTIONS[1]
            this.form.title = ''
            this.errors = {}
        },
        onMetricSelect: function (m) {
            this.form.metric = m
            this.errors = Object.assign({}, this.errors, { metric: '' })
        },
        onSleepSelect: function (n) {
            this.form.sleepBeforeMin = n
        },
        onTitleInput: function (value) {
            this.form.title = value === undefined || value === null ? '' : String(value)
            this.errors = Object.assign({}, this.errors, { title: '' })
        },
        onRepeatChange: function (value) {
            this.form.repeat = value
            if (value !== 'custom') {
                this.errors = Object.assign({}, this.errors, { weekdays: '' })
            }
        },
        onDayToggle: function (d) {
            const list = this.form.weekdays.slice(0)
            const at = list.indexOf(d)
            if (at >= 0) {
                list.splice(at, 1)
            } else {
                list.push(d)
            }
            list.sort(function (a, b) { return a - b })
            this.form.weekdays = list
            this.errors = Object.assign({}, this.errors, { weekdays: '' })
        },

        /* ───────────── 时间点 ───────────── */

        onTimeAdd: function () {
            if (this.timesFull) {
                // 上限提示（裁定 ⑤：每条最多 5 个时间点）—— 外层容器接管点击，故此处可给明确原因
                showToast('info', this.maxTimesHint)
                return
            }
            const list = this.form.times.slice(0)
            list.push(this.nextTime(list))
            this.form.times = list
            this.errors = Object.assign({}, this.errors, { times: '' })
        },
        /** 新增行的初始时刻：在已有时间点之后顺延（跳过重复；全占满时回退当前时刻） */
        nextTime: function (list) {
            for (let h = 8; h <= 21; h++) {
                const t = (h < 10 ? '0' + h : String(h)) + ':00'
                if (list.indexOf(t) < 0) {
                    return t
                }
            }
            const now = new Date()
            const hh = now.getHours() < 10 ? '0' + now.getHours() : String(now.getHours())
            return hh + ':00'
        },
        onTimeChange: function (index, e) {
            const value = e && e.detail ? String(e.detail.value || '') : ''
            if (!isValidTime(value)) {
                return
            }
            const list = this.form.times.slice(0)
            const dup = list.some(function (t, i) { return i !== index && t === value })
            if (dup) {
                // 不静默改写用户输入：明确告知并保持原值
                showToast('info', '该时间点已存在')
                return
            }
            list[index] = value
            list.sort()
            this.form.times = list
            this.errors = Object.assign({}, this.errors, { times: '' })
        },
        onTimeRemove: function (index) {
            const list = this.form.times.slice(0)
            list.splice(index, 1)
            this.form.times = list
        },

        /* ───────────── 保存 ───────────── */

        onSave: function () {
            if (this.saving) {
                return
            }
            const check = validateItem(this.form)
            if (!check.ok) {
                this.errors = check.errors
                showToast('info', this.firstError(check.errors))
                return
            }
            this.errors = {}

            // ⑥ 权限引导弹窗：**仅首次创建时**（用一个本地标记保证"只引导一次"）
            if (!this.editing && readRaw(KEYS.REMINDER_PROMPT) === null) {
                this.permVisible = true
                return
            }
            this.doSave()
        },
        firstError: function (errors) {
            const keys = Object.keys(errors || {})
            return keys.length ? String(errors[keys[0]]) : '请检查填写内容'
        },
        onPromptShow: function (visible) {
            this.permVisible = visible === true
        },
        onPromptConfirm: function () {
            this.permVisible = false
            this.markPrompted()
            const res = openSystemSettings()
            if (!res || !res.ok) {
                showToast('info', TOAST_SETTING_UNSUPPORTED)
            }
            // 无论权限结果如何都继续保存（SC-15 ⑫③）
            this.doSave()
        },
        onPromptCancel: function () {
            this.permVisible = false
            this.markPrompted()
            this.doSave()
        },
        markPrompted: function () {
            writeRaw(KEYS.REMINDER_PROMPT, '1')
        },
        /**
         * 落盘。
         * ★ `saving` 置 true 后**在成功路径上不复位**：返回列表有 `BACK_DELAY_MS` 停留窗口，
         *   若此时复位，用户连点两次会新建两条（本地新增无幂等键保护）。
         */
        doSave: function () {
            this.saving = true
            const res = upsertItem(this.form, this.editing ? this.itemId : '')
            if (!res.ok) {
                this.saving = false
                this.errors = res.errors || {}
                showToast('error', TOAST_SAVE_FAILED)
                return
            }
            if (this.editing) {
                this.itemId = res.id
            }
            // 保存成功 ⇒ 重建全量排程（档 1：清空 + 按 24h 窗口重排）
            syncSchedules()
            const reachable = canNotify()
            showToast(reachable ? 'success' : 'info', reachable ? TOAST_SAVED : TOAST_SAVED_NO_PERMISSION)
            this.leaveAfterDelay()
        },

        /* ───────────── 删除 ───────────── */

        onDeleteTap: function () {
            if (this.deleting) {
                return
            }
            this.deleteVisible = true
        },
        onDeleteShow: function (visible) {
            if (!visible) {
                this.deleteVisible = false
            }
        },
        doDelete: function () {
            if (this.deleting) {
                return
            }
            this.deleting = true
            const ok = removeItem(this.itemId)
            if (!ok) {
                this.deleting = false
                this.deleteVisible = false
                showToast('error', TOAST_DELETE_FAILED)
                return
            }
            // 同时撤销该条已注册的系统通知（否则删除后仍会响，与 I-01 同一性质）
            try {
                cancelLocal(this.itemId)
            } catch (e) {
                // 通知通道异常不影响删除结果
            }
            // ★ 档 1：`cancelLocal` 只剔台账（**不调 remove** —— A2 真机已证伪精确撤销）；
            //   系统侧的实际收敛靠紧随其后的全量重建完成。
            syncSchedules()
            this.deleteVisible = false
            showToast('success', TOAST_DELETED)
            this.leaveAfterDelay()
        },

        /* ───────────── 出口 ───────────── */

        /** 延迟返回：保证 Toast 可见（`AppToast` 随页面卸载即注销） */
        leaveAfterDelay: function () {
            const self = this
            this.leaveTimer = setTimeout(function () {
                self.leaveTimer = null
                navigateBack()
            }, BACK_DELAY_MS)
        },
        onPermissionAction: function () {
            const res = openSystemSettings()
            if (!res || !res.ok) {
                showToast('info', TOAST_SETTING_UNSUPPORTED)
            }
        }
    }
}
</script>

<style scoped lang="scss">
.redit {
    min-height: 100vh;
    background-color: var(--s-page);
}

.redit__body {
    padding-top: var(--page-pad-t);
    padding-bottom: var(--page-pad-b);
}

.redit__inner {
    max-width: var(--content-max);
    margin-left: auto;
    margin-right: auto;
    padding-left: var(--gutter);
    padding-right: var(--gutter);
}

.redit__block {
    margin-bottom: var(--card-gap);
}

/* ── 时间点行 ── */
.redit__time-row {
    display: flex;
    flex-direction: row;
    align-items: center;
    min-height: var(--row-h);
    border-bottom: 1rpx solid var(--b-line);
}

.redit__time-picker {
    flex: 1;
    display: flex;
    flex-direction: row;
    align-items: center;
}

.redit__time-value {
    display: flex;
    flex-direction: row;
    align-items: center;
    min-height: var(--tap-min);
    padding-left: var(--sp-2);
    transition: transform var(--d-fast) var(--ease-std), opacity var(--d-fast) var(--ease-std);
}

.redit__time-value--press {
    transform: scale(var(--press-scale));
    opacity: var(--press-opacity);
}

.redit__time-text {
    font-size: var(--fs-h3);
    line-height: $lh-h3;
    font-weight: $fw-medium;
    color: var(--t-1);
    letter-spacing: 0;
}

.redit__time-del {
    display: flex;
    flex-direction: row;
    align-items: center;
    justify-content: flex-end;
    min-width: var(--tap-min);
    min-height: var(--tap-min);
    padding-left: var(--sp-4);
    transition: transform var(--d-fast) var(--ease-std), opacity var(--d-fast) var(--ease-std);
}

.redit__link--press {
    transform: scale(var(--press-scale));
    opacity: var(--press-opacity);
}

.redit__link {
    font-size: var(--fs-btn-m);
    line-height: $lh-btn-m;
    font-weight: $fw-medium;
    color: var(--t-link);
    letter-spacing: 0;
}

.redit__add {
    margin-top: var(--sp-4);
}

.redit__hint {
    display: block;
    margin-top: var(--sp-2);
    font-size: var(--fs-caption);
    line-height: $lh-caption;
    color: var(--t-3);
    letter-spacing: 0;
}

/* ── 周几 chips（页面内 7 个圆形 chip；边长 = --tap-min 以满足最小触摸目标） ── */
.redit__chips {
    display: flex;
    flex-direction: row;
    align-items: center;
    margin-top: var(--sp-5);
}

.redit__chip {
    width: var(--tap-min);
    height: var(--tap-min);
    margin-right: var(--sp-2);
    border-radius: var(--r-full);
    background-color: var(--s-sunken);
    display: flex;
    flex-direction: row;
    align-items: center;
    justify-content: center;
    transition: background-color var(--d-fast) var(--ease-std),
        transform var(--d-fast) var(--ease-std),
        opacity var(--d-fast) var(--ease-std);
}

.redit__chip--last {
    margin-right: 0;
}

/* 选中：品牌浅底 + 品牌文字（与 C-08 同一视觉口径，DESIGN.md §8.1） */
.redit__chip--on {
    background-color: var(--c-p-100);
}

.redit__chip--press {
    transform: scale(var(--press-scale));
    opacity: var(--press-opacity);
}

.redit__chip-text {
    font-size: var(--fs-sub);
    line-height: $lh-sub;
    font-weight: $fw-regular;
    color: var(--t-2);
    letter-spacing: 0;
}

.redit__chip-text--on {
    font-weight: $fw-medium;
    color: var(--c-p-600);
}

/* ── 字段级错误 ── */
.redit__field-error {
    display: block;
    margin-top: var(--sp-2);
    font-size: var(--fs-caption);
    line-height: $lh-caption;
    color: var(--t-danger);
    letter-spacing: 0;
}

/* ── ⑧ 底部说明 ── */
.redit__note {
    display: block;
    padding: var(--sp-2);
    font-size: var(--fs-caption);
    line-height: $lh-caption;
    color: var(--t-3);
    letter-spacing: 0;
}
</style>
