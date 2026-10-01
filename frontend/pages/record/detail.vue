<template>
    <!--
      SC-09 记录详情页（pages/record/detail?id=&type=）
      依据：S1-C §二 SC-09（六节结构 / ⑨~⑰ 状态与接口）｜DESIGN.md §8 / §10.3 / §12 / §13
      顶栏：**A 类系统导航栏**（DESIGN.md §10.3：B 类自绘顶栏不含 SC-09）——
            标题「<指标名> 详情」由 `uni.setNavigationBarTitle` 动态设置。

      结构（与 S1-C 逐项对应）：
        [① 顶部栏]   系统导航栏 + 标题
        [② 数值区]   C-22 `MetricValueDisplay`：主值 + 单位 + 副值（舒张压 / 脉搏）+ 派生值（BMI / 睡眠时长）
        [③ 字段列表] C-20 `AppListRow`：时间行 / 专属字段（测量时机 · 运动类型 · 强度）/ 感受标签 / 备注
        [④ 元信息]   创建时间（★ 按冻结决策：**只显示创建时间**，`updated_at` 不展示）
        [⑤ 底部]     [编辑] [删除]（危险色）
        [⑥ 离线]     离线条 + 编辑 / 删除置灰 + 明确提示

      接口（**只用已封板接口，未改后端**）：
        · `R-03 GET /records/{id}` 详情（返回 `{ record, derived }`）；
        · `R-05 DELETE /records/{id}` 单条删除（软删；**重复删除 → 404**）。
        ★ 本轮**不使用** R-06 / R-07（属 S3-8），也**不新增任何接口**。

      ★ 冻结决策落地（用户 2026-09-15 拍板，不得偏离）：
        1. **SC-09 时间**：后端 `_view()` 只回 `created_at` ⇒ 本页**只显示创建时间**，
           **不为"最后修改时间"修改后端 / 模型 / 数据库 / 接口契约**；`updated_at` 作为未来合同清理项。
        2. **SC-09 删除**：使用现有 C-12 `AppModal` 的 `danger` 模式（红钮 + 不可点遮罩关闭）；
           **不增加密码输入、不增加"确认删除"文字输入**（R-05 本身不需要密码）；**不改 C-12**。
        3. **枚举来源**：指标中文名 / 单位来自本地冻结字典（`utils/metrics.js`，零请求）；
           枚举标签（测量时机 / 运动类型 / 强度 / 感受标签）**只读 `R-08` 缓存**
           （`kj:cache.record_options`）；**缓存无对应枚举 → 静默隐藏该辅助行**，不新增接口请求。

      红线（DESIGN.md §12）：**不出现**医疗诊断 / 正常·异常 / 偏高·偏低 / 参考范围 / 风险等级；
        派生值只给数字（BMI 不带分级）。

      状态覆盖（DESIGN.md §13）：
        正常 ✅ ｜ 空态 **N/A**（详情页必有数据；`id` 不存在 → 错误态）｜ 加载 ✅ 骨架屏
        失败 ✅ 加载失败 → `AppErrorState` + 重试；**记录不存在 → 统一文案 + 「返回记录中心」**
        未登录 ✅ 守卫 → SC-03 ｜ 离线 ✅ 缓存只读（从 SC-10 列表缓存兜底）+ 离线条 + 编辑/删除置灰
        401 ✅ 统一请求层（单次 refresh + replay；失败清栈回 SC-03）
        提交防重 ✅ 删除中按钮禁用（`confirmDisabled`）｜ 高风险 ✅ C-12 danger 二次确认

      ★ 返回拦截铁律（S3-2 实测，必须遵守）：本页**不实现 `onBackPress`** ——
        删除成功 / 保存返回均走 `uni.navigateBack()` 或 `uni.redirectTo()`；
        未写该钩子即不存在"自我拦截 → `navigateBack:fail onBackPress`"的风险。
    -->
    <view class="detail">
        <view class="detail__body">
            <view class="detail__inner">
                <!-- 参数非法（缺失 / 未知 id）→ 整页错误态 -->
                <view v-if="invalidParam" class="detail__block">
                    <AppErrorState
                        variant="full"
                        text="记录参数不正确，请从记录列表进入"
                        retry-text="返回记录中心"
                        @retry="backToRecord"
                    />
                </view>

                <template v-else>
                    <!-- ⑥ 离线提示条 -->
                    <view v-if="offline" class="detail__block">
                        <AppOfflineBar variant="offline" :text="offlineBarText" />
                    </view>

                    <!-- ⑪ 加载态：骨架屏（禁整页白屏） -->
                    <view v-if="loading" class="detail__block">
                        <AppSkeleton variant="card" />
                    </view>
                    <view v-if="loading" class="detail__block">
                        <AppSkeleton variant="list" />
                    </view>

                    <!-- ⑫ 错误态：记录不存在 / 加载失败 -->
                    <view v-else-if="errorText" class="detail__block">
                        <AppErrorState
                            variant="full"
                            :text="errorText"
                            :retry-text="errorRetryText"
                            @retry="onErrorRetry"
                        />
                    </view>

                    <template v-else>
                        <!-- ② 数值区 -->
                        <AppCard class="detail__block">
                            <view class="detail__head">
                                <text class="detail__type">{{ typeLabel }}</text>
                            </view>
                            <MetricValueDisplay
                                :value="mainValue"
                                :unit="mainUnit"
                                :subs="subValues"
                                :derived="derivedValues"
                            />
                        </AppCard>

                        <!-- ③ 字段列表 -->
                        <AppCard v-if="detailRows.length" title="记录信息" class="detail__block">
                            <AppListRow
                                v-for="(row, index) in detailRows"
                                :key="row.key"
                                :title="row.label"
                                :value="row.value"
                                :last="index === detailRows.length - 1"
                            />
                        </AppCard>

                        <!-- ④ 元信息（只显示创建时间） -->
                        <AppCard v-if="metaRows.length" title="元信息" class="detail__block">
                            <AppListRow
                                v-for="(row, index) in metaRows"
                                :key="row.key"
                                :title="row.label"
                                :value="row.value"
                                :last="index === metaRows.length - 1"
                            />
                        </AppCard>

                        <!-- ⑤ 底部操作（离线 → 置灰 + 下方明确提示） -->
                        <view class="detail__foot">
                            <view class="detail__foot-item">
                                <AppButton
                                    label="编辑"
                                    block
                                    :disabled="offline"
                                    @tap="onEdit"
                                />
                            </view>
                            <view class="detail__foot-item">
                                <AppButton
                                    label="删除"
                                    type="danger"
                                    block
                                    :disabled="offline || deleting"
                                    @tap="onDeleteTap"
                                />
                            </view>
                        </view>
                        <text v-if="offline" class="detail__offline-hint">{{ offlineActionText }}</text>
                    </template>
                </template>
            </view>
        </view>

        <!-- ⑮ 高风险确认：删除单条（C-12 danger，不可点遮罩关闭） -->
        <AppModal
            :show="deleteVisible"
            mode="danger"
            title="删除这条记录？"
            content="删除后无法恢复"
            confirm-text="删除"
            cancel-text="取消"
            :confirm-disabled="deleting"
            @confirm="onDeleteConfirm"
            @cancel="onDeleteCancel"
        />

        <!-- 轻提示宿主（成功 / 失败 / 会话失效提示经此渲染） -->
        <AppToast />
    </view>
</template>

<script>
import AppCard from '../../components/AppCard.vue'
import AppButton from '../../components/AppButton.vue'
import AppListRow from '../../components/AppListRow.vue'
import MetricValueDisplay from '../../components/MetricValueDisplay.vue'
import AppModal from '../../components/AppModal.vue'
import AppToast from '../../components/AppToast.vue'
import AppSkeleton from '../../components/AppSkeleton.vue'
import AppErrorState from '../../components/AppErrorState.vue'
import AppOfflineBar from '../../components/AppOfflineBar.vue'

import { ROUTES, navigateTo, navigateBack, reLaunch, requireLogin } from '../../utils/route'
import { metricLabel, metricUnit, toMinute, VALUE_FIELD_LABEL } from '../../utils/metrics'
import { CACHE_KEYS, loadCache, recordListKey } from '../../utils/cache'
import { isOnline, offlineText } from '../../utils/network'
import { showToast } from '../../utils/toast'
import { errorText } from '../../utils/request'
import { fieldLabel, fieldUnit, enumKeyOf } from '../../utils/recordForm'
import { getRecord, deleteRecord } from '../../api/records'

/** 记录不存在（S1-C ⑫①：不存在 / 已删除 / 越权 → **统一按"记录不存在"提示**） */
const NOT_FOUND_TEXT = '记录不存在'
/** 加载失败（中性技术文案，非医学表述） */
const LOAD_FAIL_TEXT = '加载失败，请稍后重试'
/** 离线且无本地缓存（不假装有数据） */
const OFFLINE_NO_CACHE_TEXT = '当前离线，且没有该记录的本地缓存'
/** 离线禁止编辑（S1-C ⑭② 固定文案） */
const OFFLINE_EDIT_TEXT = '离线状态暂不可编辑，请联网后重试'

/** 元信息标签（页面级文案；取值口径由 S1-C ④ 冻结） */
const CREATED_AT_LABEL = '创建时间'
/** 通用测量时间标签（与 SC-08 同口径；`sleep` 走「入睡 / 起床」两行） */
const MEASURE_TIME_LABEL = '测量时间'
/** 感受标签行标签 */
const TAGS_LABEL = '感受标签'
/** 备注行标签 */
const NOTE_LABEL = '备注'

export default {
    components: {
        AppCard: AppCard,
        AppButton: AppButton,
        AppListRow: AppListRow,
        MetricValueDisplay: MetricValueDisplay,
        AppModal: AppModal,
        AppToast: AppToast,
        AppSkeleton: AppSkeleton,
        AppErrorState: AppErrorState,
        AppOfflineBar: AppOfflineBar
    },
    data: function () {
        return {
            /** 记录 id（来自 `?id=`） */
            recordId: '',
            /** 指标类型（来自 `?type=`；缺失时由 R-03 返回的 `metric_type` 补齐） */
            metricType: '',
            /** 参数非法（缺失 id）→ 整页错误态 */
            invalidParam: false,

            /** R-03 结果 */
            record: null,
            /** R-03 的 `derived`（BMI / 睡眠时长 / 当日累计） */
            derivedInfo: {},

            /** R-08 字典缓存（**只读缓存，不新增请求**；用于枚举标签） */
            options: null,

            loading: false,
            errorText: '',
            /** 错误是否为「记录不存在」（决定重试按钮的去向） */
            notFound: false,

            /** 离线（只读 + 写操作置灰） */
            offline: false,
            /** 缓存写入时刻（离线命中的来源标记） */
            cacheSavedAt: '',

            /** 删除确认 / 删除中（防重复提交） */
            deleteVisible: false,
            deleting: false,

            /** 是否已完成首次 onShow（避免与 onLoad 双发请求，S3-2 时序纪律） */
            entered: false,

            /** 网络监听句柄 */
            networkHandler: null
        }
    },
    computed: {
        typeLabel: function () {
            return metricLabel(this.metricType)
        },
        unitText: function () {
            const record = this.record || {}
            return metricUnit(this.metricType, record.unit)
        },
        /** 主值是否缺失（缺失 → 不展示单位，避免出现「— score」这类无意义组合） */
        mainEmpty: function () {
            const raw = this.record ? this.record.value_1 : null
            return raw === null || raw === undefined || raw === ''
        },
        /**
         * 数值区主值。
         * ★ 口径（如实登记）：`sleep` 的 `value_1` 是「睡眠质量分（1–5）」，而 SC-08 的表单契约
         *   （`utils/recordForm.js` 的 `MAIN_FIELDS.sleep = []`）**不采集该项** ⇒ 睡眠记录通常
         *   没有 `value_1`。为避免整页主值恒为「—」，睡眠在 `value_1` 缺失时**以派生睡眠时长
         *   作为主值**（单位「小时」——与 SC-08 已封板的「睡眠时长 N 小时」逐字同口径）。
         */
        mainValue: function () {
            if (!this.mainEmpty) {
                return this.record.value_1
            }
            const hours = this.sleepHours
            return hours === null ? '' : hours
        },
        mainUnit: function () {
            if (!this.mainEmpty) {
                return this.unitText
            }
            return this.sleepHours === null ? '' : '小时'
        },
        /** 派生睡眠时长（小时，后端 `derived.sleep_duration_hours`；缺失 → null） */
        sleepHours: function () {
            if (this.metricType !== 'sleep') {
                return null
            }
            const hours = this.derivedInfo ? this.derivedInfo.sleep_duration_hours : null
            if (hours === null || hours === undefined || hours === '') {
                return null
            }
            return hours
        },
        /** 副值：`value_2`（血压舒张压 / 运动卡路里）/ `value_3`（血压脉搏）—— 标签缺登记则隐藏 */
        subValues: function () {
            const out = []
            const record = this.record
            if (!record) {
                return out
            }
            const labels = VALUE_FIELD_LABEL[this.metricType] || {}
            const fields = ['value_2', 'value_3']
            for (let i = 0; i < fields.length; i++) {
                const field = fields[i]
                const raw = record[field]
                if (raw === null || raw === undefined || raw === '') {
                    continue
                }
                const label = labels[field]
                if (!label) {
                    continue
                }
                out.push({
                    label: label,
                    value: String(raw),
                    unit: fieldUnit(this.metricType, field)
                })
            }
            return out
        },
        /** 派生值（只显示数字，无分级标签）；已提升为主值的项不重复展示 */
        derivedValues: function () {
            const out = []
            const info = this.derivedInfo || {}
            if (this.metricType === 'weight' && info.bmi !== null && info.bmi !== undefined) {
                out.push({ label: 'BMI', value: String(info.bmi) })
            }
            if (this.metricType === 'sleep' && this.sleepHours !== null) {
                // 睡眠时长已提升为主值（`value_1` 缺失时）⇒ 此处不重复展示
                if (!this.mainEmpty) {
                    out.push({ label: '睡眠时长', value: String(this.sleepHours) + ' 小时' })
                }
            }
            if (this.metricType === 'water' && info.today_total_ml !== null && info.today_total_ml !== undefined) {
                const unit = this.unitText
                out.push({
                    label: '当日累计',
                    value: unit ? String(info.today_total_ml) + ' ' + unit : String(info.today_total_ml)
                })
            }
            return out
        },
        /** ③ 字段列表（时间行 / 专属字段 / 标签 / 备注；空值不产生空行） */
        detailRows: function () {
            const rows = []
            const record = this.record
            if (!record) {
                return rows
            }
            const type = this.metricType

            if (type === 'sleep') {
                const startLabel = fieldLabel(type, 'time_start') || '入睡时间'
                const endLabel = fieldLabel(type, 'recorded_at') || '起床时间'
                const start = toMinute(record.time_start)
                const end = toMinute(record.recorded_at)
                if (start) {
                    rows.push({ key: 'time_start', label: startLabel, value: start })
                }
                if (end) {
                    rows.push({ key: 'recorded_at', label: endLabel, value: end })
                }
            } else {
                const measure = toMinute(record.recorded_at)
                if (measure) {
                    rows.push({ key: 'recorded_at', label: MEASURE_TIME_LABEL, value: measure })
                }
            }

            const extras = ['attr_1', 'attr_2']
            for (let i = 0; i < extras.length; i++) {
                const field = extras[i]
                const raw = record[field]
                if (raw === null || raw === undefined || raw === '') {
                    continue
                }
                const label = fieldLabel(type, field)
                if (!label) {
                    continue
                }
                const text = this.enumLabel(enumKeyOf(type, field), raw)
                if (!text) {
                    // 缓存无对应枚举 → **静默隐藏**（不显示原始英文枚举值，不新增请求）
                    continue
                }
                rows.push({ key: field, label: label, value: text })
            }

            const tags = record.tags && record.tags.length ? record.tags : []
            if (tags.length) {
                const labels = []
                for (let i = 0; i < tags.length; i++) {
                    const text = this.enumLabel(enumKeyOf(type, 'tags'), tags[i])
                    if (text) {
                        labels.push(text)
                    }
                }
                if (labels.length) {
                    rows.push({ key: 'tags', label: TAGS_LABEL, value: labels.join('、') })
                }
            }

            if (record.note) {
                rows.push({ key: 'note', label: NOTE_LABEL, value: String(record.note) })
            }

            return rows
        },
        /** ④ 元信息（**只显示创建时间**；`updated_at` 按冻结决策不展示） */
        metaRows: function () {
            const rows = []
            const record = this.record
            if (!record) {
                return rows
            }
            const created = toMinute(record.created_at)
            if (created) {
                rows.push({ key: 'created_at', label: CREATED_AT_LABEL, value: created })
            }
            return rows
        },
        offlineBarText: function () {
            if (this.cacheSavedAt) {
                return '离线数据 · 更新于 ' + this.cacheSavedAt
            }
            return offlineText('')
        },
        offlineActionText: function () {
            return OFFLINE_EDIT_TEXT
        },
        errorRetryText: function () {
            return this.notFound ? '返回记录中心' : '重试'
        }
    },
    onLoad: function (query) {
        // 未登录守卫（S1-C ⑬：需登录）
        if (!requireLogin()) {
            return
        }

        const id = query && query.id !== undefined && query.id !== null ? String(query.id) : ''
        const type = query && query.type ? String(query.type) : ''
        if (!id) {
            this.invalidParam = true
            return
        }
        this.recordId = id
        this.metricType = type

        // R-08 字典：**只读缓存**（用于枚举标签；缓存缺失即静默隐藏相关行，不发请求）
        const cachedOptions = loadCache(CACHE_KEYS.RECORD_OPTIONS)
        this.options = cachedOptions && cachedOptions.data ? cachedOptions.data : null

        this.load()

        // 网络状态（离线 → 只读 + 写操作置灰；恢复 → 解除置灰，**不自动重放**）
        const self = this
        this.networkHandler = function (res) {
            self.offline = !(res && res.isConnected)
        }
        uni.onNetworkStatusChange(this.networkHandler)
        isOnline().then(function (online) {
            self.offline = !online
        })
    },
    onUnload: function () {
        if (this.networkHandler) {
            uni.offNetworkStatusChange(this.networkHandler)
            this.networkHandler = null
        }
    },
    onShow: function () {
        // 从 SC-08 编辑返回：重新拉取详情（保证展示的是最新值）
        if (this.recordId && this.entered) {
            this.load()
        }
        this.entered = true
    },
    methods: {
        /* ───────────── 数据加载（R-03） ───────────── */

        /**
         * 加载详情。
         * 失败分支（S1-C ⑫ / ⑭）：① 网络失败 → 命中列表缓存则只读展示，否则明确提示；
         * ② 404 → **统一按「记录不存在」**；③ 其他 → 中性失败文案 + 重试。
         */
        load: function () {
            const self = this
            this.loading = true
            this.errorText = ''
            this.notFound = false
            this.cacheSavedAt = ''

            return getRecord(this.recordId).then(function (res) {
                self.loading = false
                const data = res && res.data ? res.data : null
                if (!data || !data.record) {
                    self.errorText = LOAD_FAIL_TEXT
                    return
                }
                self.applyRecord(data.record, data.derived)
            }, function (err) {
                self.loading = false

                if (err && err.isNetwork) {
                    self.offline = true
                    const cached = self.findInListCache()
                    if (cached) {
                        self.applyRecord(cached.record, {})
                        return
                    }
                    self.errorText = OFFLINE_NO_CACHE_TEXT
                    return
                }

                if (self.isNotFound(err)) {
                    self.notFound = true
                    self.errorText = NOT_FOUND_TEXT
                    return
                }

                self.errorText = errorText(err)
            })
        },

        applyRecord: function (record, derived) {
            this.record = record
            this.derivedInfo = derived || {}
            if (!this.metricType && record && record.metric_type) {
                this.metricType = String(record.metric_type)
            }
            this.applyTitle()
        },

        /** 导航栏标题：「<指标名> 详情」（A 类系统导航栏，标题按 type 动态设置） */
        applyTitle: function () {
            const label = metricLabel(this.metricType)
            uni.setNavigationBarTitle({ title: label ? label + ' 详情' : '记录详情' })
        },

        /** 404 判定（记录不存在 / 非本人 / 已软删 —— 后端统一 404 `RESOURCE_NOT_FOUND`） */
        isNotFound: function (err) {
            if (!err) {
                return false
            }
            return err.httpStatus === 404 || err.code === 'RESOURCE_NOT_FOUND'
        },

        /**
         * 离线兜底：从 SC-10 的**列表缓存**（`cache.record_list.<metric>`）中按 id 找该条。
         * 只读、不写回；找不到 → null（由调用方给明确提示，不假装有数据）。
         */
        findInListCache: function () {
            if (!this.metricType) {
                return null
            }
            const cached = loadCache(recordListKey(this.metricType))
            const items = cached && cached.data && cached.data.items ? cached.data.items : null
            if (!items || !items.length) {
                return null
            }
            for (let i = 0; i < items.length; i++) {
                if (String(items[i].id) === String(this.recordId)) {
                    this.cacheSavedAt = cached.savedAt
                    return { record: items[i], derived: {} }
                }
            }
            return null
        },

        /** R-08 字典缓存 → 枚举标签（缺失 → ''，由调用方静默隐藏该行） */
        enumLabel: function (enumKey, value) {
            const enums = this.options && this.options.enums
            const list = enums && enumKey ? enums[enumKey] : null
            if (!list || !list.length) {
                return ''
            }
            for (let i = 0; i < list.length; i++) {
                if (String(list[i].value) === String(value)) {
                    return list[i].label
                }
            }
            return ''
        },

        onErrorRetry: function () {
            if (this.notFound) {
                this.backToRecord()
                return
            }
            this.load()
        },

        /* ───────────── ⑤ 编辑 / 删除 ───────────── */

        /** 编辑 → SC-08 编辑模式（`?type=&id=`） */
        onEdit: function () {
            if (this.offline) {
                showToast('error', OFFLINE_EDIT_TEXT)
                return
            }
            if (!this.metricType) {
                return
            }
            navigateTo(ROUTES.RECORD_ADD + '?type=' + this.metricType + '&id=' + this.recordId)
        },

        onDeleteTap: function () {
            if (this.offline || this.deleting) {
                return
            }
            this.deleteVisible = true
        },

        onDeleteCancel: function () {
            this.deleteVisible = false
        },

        /**
         * 删除确认（R-05）。
         * ★ 重复删除（404）→ **统一按「记录不存在」处理**，不制造异常页面（S1-C ⑫①）。
         * ★ 失败**绝不静默**：明确 Toast + 数据保持原状。
         */
        onDeleteConfirm: function () {
            const self = this
            if (this.deleting) {
                return
            }
            if (this.offline) {
                this.deleteVisible = false
                showToast('error', offlineText(''))
                return
            }

            this.deleting = true
            return deleteRecord(this.recordId).then(function () {
                self.deleting = false
                self.deleteVisible = false
                showToast('success', '已删除')
                self.afterDelete()
            }, function (err) {
                self.deleting = false
                self.deleteVisible = false

                if (self.isNotFound(err)) {
                    // 重复删除 / 已被删除：按"记录不存在"统一处理（与 ⑫① 同口径）
                    self.notFound = true
                    self.record = null
                    self.errorText = NOT_FOUND_TEXT
                    showToast('info', NOT_FOUND_TEXT)
                    return
                }
                if (err && err.isNetwork) {
                    showToast('error', '删除失败，请重试')
                    return
                }
                showToast('error', '删除失败，请重试')
            })
        },

        /**
         * 删除成功后的去向（S1-C ⑦：「删除成功 → **返回 SC-10 并刷新**」）。
         * ① 来源即 SC-10 → `navigateBack()`（SC-10 的 `onShow` 自动刷新，被删条目消失）；
         * ② 来源为其他页（SC-06 等）→ `redirectTo` SC-10（用当前页替换，栈内不留"已删除的详情页"）。
         */
        afterDelete: function () {
            const pages = getCurrentPages()
            const prev = pages && pages.length > 1 ? pages[pages.length - 2] : null
            const prevRoute = prev && prev.route ? String(prev.route) : ''
            const url = ROUTES.RECORD_HISTORY + '?type=' + this.metricType
            if (prevRoute.indexOf('record/history') >= 0) {
                navigateBack()
                return
            }
            uni.redirectTo({ url: url })
        },

        /** 参数非法 / 记录不存在时的出口 → 记录中心 */
        backToRecord: function () {
            reLaunch(ROUTES.RECORD)
        }
    }
}
</script>

<style scoped lang="scss">
.detail {
    min-height: 100vh;
    background-color: var(--s-page);
}

.detail__body {
    /* A 类系统导航栏占位由平台负责，此处只留内容区节奏 */
    padding-top: var(--page-pad-t);
    padding-bottom: var(--page-pad-b);
}

/* 内容最大宽居中（DESIGN.md §10.4③） */
.detail__inner {
    max-width: var(--content-max);
    margin-left: auto;
    margin-right: auto;
    padding-left: var(--gutter);
    padding-right: var(--gutter);
}

.detail__block {
    margin-bottom: var(--card-gap);
}

.detail__head {
    display: flex;
    flex-direction: row;
    align-items: baseline;
    margin-bottom: var(--sp-5);
}

.detail__type {
    font-size: var(--fs-h3);
    line-height: $lh-h3;
    font-weight: $fw-medium;
    color: var(--t-2);
    letter-spacing: 0;
}

/* 底部按钮（文档流内布局，**不用 fixed** ⇒ 任何屏宽下都不会遮挡内容） */
.detail__foot {
    margin-top: var(--sp-6);
}

.detail__foot-item {
    margin-bottom: var(--sp-3);
}

.detail__offline-hint {
    display: block;
    margin-top: var(--sp-2);
    font-size: var(--fs-caption);
    line-height: $lh-caption;
    color: var(--t-3);
    letter-spacing: 0;
}
</style>
