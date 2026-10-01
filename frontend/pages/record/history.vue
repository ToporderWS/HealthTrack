<template>
    <!--
      SC-10 记录历史列表（pages/record/history?type=）
      依据：S1-C §二 SC-10（五节结构 / ⑨~⑰ 状态与接口）｜DESIGN.md §8 / §10.3 / §11 / §12 / §13
      顶栏：**A 类系统导航栏**（DESIGN.md §10.3：B 类自绘顶栏不含 SC-10）——
            标题「<指标名> 历史」由 `uni.setNavigationBarTitle` 动态设置。

      结构（与 S1-C 逐项对应）：
        [① 顶部栏]   系统导航栏
        [② 筛选条]   C-08 `AppSegmented` 时间范围（近 7 / 30 / 90 天 / 自定义）
                      + C-09 `AppChipTabs` 指标切换（默认锁定 `?type=`，可切）
        [③ 列表]     C-27 `RecordItem`（variant=list）：主值 + 单位 + 测量时间（+ 次值小字）→ 点击进 SC-09
                      游标分页：触底加载更多（「加载中…」/「没有更多了」）
                      ★ 点击载荷由模板**显式传入**（`@tap="onItemTap(item)"`）—— 本工程既有约定，
                        原因见 `onItemTap` 注释（uni-app H5 会把组件上的 `@tap` 编译为 DOM `onClick`）。
                      ★ 睡眠行（S3-3 修复，见 `rowRecord` / `subValueOf`）：
                        主值 = 睡眠时长（`value_1` 缺失时，与 SC-08 / SC-09 同口径，单位「小时」）；
                        次值 = **入睡时间**（`time_start`，标注「入睡」）；
                        行左侧时间 = `recorded_at` = **起床时间**（S0 9.4 跨天归属口径，绝不当成入睡时间）。
        [④ 空状态区] C-14 `AppEmpty`：「该时间段还没有记录」+「去记录」→ SC-08
        [⑤ 顶部离线标记条] C-17 `AppOfflineBar`

      接口（**只用已封板接口，未改后端**）：
        · `R-02 GET /records`（游标分页；**不返回 total**；时间范围为**半开区间 `[start, end)`**）。
        ★ 本轮**不使用** R-06 / R-07（属 S3-8），也**不新增任何接口**。

      ★ 冻结决策落地（用户 2026-09-15 拍板，不得偏离）：
        3. **SC-10 自定义时间范围**：沿用 C-08 四段；「自定义」**不新增日期范围组件** ——
           直接用 C-12 `AppModal` 抽屉 + 两把 C-06 `AppDatePicker`（开始 / 结束日期）。
           请求后端**严格用半开区间 `[start, end)`**：`end` 取「结束日期 **+1 天**」的 `YYYY-MM-DD`，
           **绝不把结束日期拼成 `23:59:59`**（避免漏掉结束日当天 00:00 之后的所有记录）。
        · 时间窗口（`近 N 天`，含今天）＝ `start = 今天 −(N−1) 天`、`end = 明天`
          （即 `[今天−N+1, 明天)` 恰好覆盖 N 个自然日）。
        · **默认「近 30 天」**：与本地缓存的保留窗口（每指标近 30 天）一致，
          使离线首屏能直接命中缓存。

      ★ 排序口径（用户明令）：**默认按后端返回顺序展示，不自行改变排序** ——
        后端固定 `recorded_at DESC, id DESC`，本页**不做任何客户端 sort**。

      ★ 枚举口径：指标中文名 / 单位来自本地冻结字典（`utils/metrics.js`，零请求）；
        本页**不需要**枚举标签（不读 R-08），故不产生任何额外请求。

      红线（DESIGN.md §12）：**不出现**医疗诊断 / 正常·异常 / 偏高·偏低 / 参考范围 / 风险等级。

      状态覆盖（DESIGN.md §13 SC-10 清单，逐项映射）：
        正常 ✅ 游标分页 + 触底加载
        空态 ✅ 「该时间段还没有记录」+「去记录」（**不自创"首次使用"文案**）
        加载 ✅ 首屏骨架屏；触底显示「加载中…」
        失败 ✅ 首屏失败 → C-16 整页失败态 + 重试；
              **分页失败 → 列表底部「加载失败，点击重试」（不清空已有列表）**
        未登录 ✅ 守卫 → SC-03
        离线 ✅ 缓存只读（每指标 ≤200 条 / 近 30 天）+ 离线条；**「加载更多」置灰**并提示
              「离线状态仅可查看已缓存记录」
        401 ✅ 统一请求层（单次 refresh + replay；失败清栈回 SC-03）
        提交防重 **N/A**（本页无写操作；删除在 SC-09 详情页执行）
        高风险确认 **N/A**（S1-C ⑮：无危险操作）

      ★ 返回拦截铁律（S3-2 实测，必须遵守）：本页**不实现 `onBackPress`** ——
        返回箭头走系统导航栏、删除后返回走 `navigateBack()`；
        未写该钩子即不存在"自我拦截 → `navigateBack:fail onBackPress`"的风险。
    -->
    <view class="history">
        <view class="history__body">
            <view class="history__inner">
                <!-- ⑤ 离线标记条 -->
                <view v-if="offline" class="history__block">
                    <AppOfflineBar variant="offline" :text="offlineBarText" />
                </view>

                <!-- 网络恢复横幅（3s 后自行撤下，DESIGN.md §8.2 C-17） -->
                <view v-if="restoredVisible" class="history__block">
                    <AppOfflineBar variant="restored" text="网络已恢复" />
                </view>

                <!-- ② 筛选条：时间范围 + 指标 -->
                <view class="history__filter">
                    <AppSegmented
                        :model-value="rangeMode"
                        :options="rangeOptions"
                        :disabled="loading || offline"
                        @change="onRangeChange"
                    />
                </view>
                <view class="history__metrics">
                    <AppChipTabs
                        :model-value="metricType"
                        :options="metricOptions"
                        :disabled="loading"
                        @change="onMetricChange"
                    />
                </view>

                <!-- ⑪ 首屏加载：骨架屏（禁整页白屏） -->
                <view v-if="loading" class="history__block">
                    <AppSkeleton variant="list" />
                </view>

                <!-- ⑫ 首屏失败 / 离线且无缓存 -->
                <view v-else-if="errorText" class="history__block">
                    <AppErrorState variant="full" :text="errorText" retry-text="重试" @retry="load" />
                </view>

                <!-- ⑩ 空状态（固定文案，逐字取自 DESIGN.md §13） -->
                <view v-else-if="!items.length" class="history__block">
                    <AppEmpty text="该时间段还没有记录" action-text="去记录" @action="onGoRecord" />
                </view>

                <!-- ③ 列表 -->
                <template v-else>
                    <AppCard class="history__block">
                        <RecordItem
                            v-for="(item, index) in items"
                            :key="item.id"
                            :record="rowRecord(item)"
                            variant="list"
                            :sub-value="subValueOf(item)"
                            :last="index === items.length - 1"
                            @tap="onItemTap(item)"
                        />
                    </AppCard>

                    <!-- 触底加载更多状态区（四种互斥文案；**失败不清空列表**） -->
                    <view class="history__more">
                        <view v-if="loadingMore" class="history__more-plain">
                            <text class="history__more-text">加载中…</text>
                        </view>
                        <view
                            v-else-if="moreError"
                            class="history__more-retry"
                            hover-class="history__more-retry--press"
                            :hover-start-time="0"
                            :hover-stay-time="80"
                            @tap="onRetryMore"
                        >
                            <text class="history__more-retry-text">加载失败，点击重试</text>
                        </view>
                        <view v-else-if="offline" class="history__more-plain">
                            <text class="history__more-text history__more-text--muted">{{ offlineMoreText }}</text>
                        </view>
                        <view v-else-if="!hasMore" class="history__more-plain">
                            <text class="history__more-text">没有更多了</text>
                        </view>
                    </view>
                </template>
            </view>
        </view>

        <!-- 决策 3：自定义时间范围（C-12 抽屉 + 两把 C-06 日期选择器，**不新增范围组件**） -->
        <AppModal
            :show="rangeVisible"
            title="自定义时间范围"
            confirm-text="确定"
            cancel-text="取消"
            @confirm="onRangeConfirm"
            @cancel="onRangeCancel"
        >
            <view class="history__range">
                <view class="history__range-item">
                    <AppDatePicker
                        v-model="draftStart"
                        mode="date"
                        label="开始日期"
                        placeholder="请选择开始日期"
                        :end="today"
                    />
                </view>
                <view class="history__range-item">
                    <AppDatePicker
                        v-model="draftEnd"
                        mode="date"
                        label="结束日期"
                        placeholder="请选择结束日期"
                        :end="today"
                    />
                </view>
                <text class="history__range-hint">按所选日期范围查询（含首尾两天）</text>
            </view>
        </AppModal>

        <!-- 轻提示宿主（成功 / 失败 / 会话失效提示经此渲染） -->
        <AppToast />
    </view>
</template>

<script>
import AppCard from '../../components/AppCard.vue'
import AppSegmented from '../../components/AppSegmented.vue'
import AppChipTabs from '../../components/AppChipTabs.vue'
import AppDatePicker from '../../components/AppDatePicker.vue'
import AppModal from '../../components/AppModal.vue'
import AppToast from '../../components/AppToast.vue'
import AppSkeleton from '../../components/AppSkeleton.vue'
import AppEmpty from '../../components/AppEmpty.vue'
import AppErrorState from '../../components/AppErrorState.vue'
import AppOfflineBar from '../../components/AppOfflineBar.vue'
import RecordItem from '../../components/RecordItem.vue'

import { ROUTES, navigateTo, requireLogin } from '../../utils/route'
import { METRIC_TYPES, metricLabel, toShortMinute, VALUE_FIELD_LABEL } from '../../utils/metrics'
import { sleepDurationHours } from '../../utils/recordForm'
import {
    CACHE_KEYS, loadCache, saveCache, recordListKey,
    RECORD_LIST_MAX_ITEMS, RECORD_LIST_MAX_DAYS
} from '../../utils/cache'
import { isOnline } from '../../utils/network'
import { showToast } from '../../utils/toast'
import { errorText } from '../../utils/request'
import { pad2, todayString } from '../../utils/validate'
import { NETWORK_BANNER_MS } from '../../utils/config'
import { listRecords } from '../../api/records'

/** 每页条数（后端 `paging.DEFAULT_LIMIT`；合法值仅 20 / 50 / 100） */
const PAGE_SIZE = 20

/** 首屏失败（中性技术文案，非医学表述） */
const LOAD_FAIL_TEXT = '加载失败，请稍后重试'

/** 离线且无本地缓存（不假装有数据、不显示误导性空态） */
const OFFLINE_NO_CACHE_TEXT = '当前离线，且没有本地缓存记录'

/** 离线时的「加载更多」提示（S1-C ⑭ 固定口径） */
const OFFLINE_MORE_TEXT = '离线状态仅可查看已缓存记录'

/** 睡眠行的次值前缀（次值 = **入睡时间**；行左侧时间 = `recorded_at` = 起床时间） */
const SLEEP_START_PREFIX = '入睡 '
/** 睡眠时长单位（与 SC-08 录入页 / SC-09 详情页同口径） */
const SLEEP_HOURS_UNIT = '小时'

/** 时间范围的默认值（近 30 天 —— 与缓存保留窗口一致，离线首屏可直接命中） */
const DEFAULT_RANGE = '30'

/** 时间范围选项（C-08 四段，顺序即展示顺序） */
const RANGE_OPTIONS = [
    { value: '7', label: '近 7 天' },
    { value: '30', label: '近 30 天' },
    { value: '90', label: '近 90 天' },
    { value: 'custom', label: '自定义' }
]

/** `Date` → `YYYY-MM-DD`（本地墙上时间，S1-D D-4） */
function dayString(date) {
    return String(date.getFullYear()) + '-' + pad2(date.getMonth() + 1) + '-' + pad2(date.getDate())
}

/** 今天 ± N 天的 `YYYY-MM-DD`（N 为负即往前） */
function shiftDay(days) {
    const d = new Date()
    d.setDate(d.getDate() + days)
    return dayString(d)
}

/** `YYYY-MM-DD` 偏移 N 天（用于把「结束日期」变成半开区间的开区端点） */
function addDays(dayText, days) {
    const parts = String(dayText || '').split('-')
    if (parts.length !== 3) {
        return ''
    }
    const d = new Date(Number(parts[0]), Number(parts[1]) - 1, Number(parts[2]))
    d.setDate(d.getDate() + days)
    return dayString(d)
}

export default {
    components: {
        AppCard: AppCard,
        AppSegmented: AppSegmented,
        AppChipTabs: AppChipTabs,
        AppDatePicker: AppDatePicker,
        AppModal: AppModal,
        AppToast: AppToast,
        AppSkeleton: AppSkeleton,
        AppEmpty: AppEmpty,
        AppErrorState: AppErrorState,
        AppOfflineBar: AppOfflineBar,
        RecordItem: RecordItem
    },
    data: function () {
        return {
            /** 当前指标（默认锁定 `?type=`；非法 / 缺失 → 回落第一个指标） */
            metricType: '',
            /** 当前生效的时间范围：'7' | '30' | '90' | 'custom' */
            rangeMode: DEFAULT_RANGE,
            /** 自定义范围的已生效取值（`YYYY-MM-DD`） */
            customStart: '',
            customEnd: '',
            /** 自定义抽屉的草稿值（确认后才生效） */
            draftStart: '',
            draftEnd: '',
            rangeVisible: false,

            /** 列表数据（**保持后端返回顺序，不重排**） */
            items: [],
            /** 游标分页状态 */
            nextCursor: '',
            hasMore: false,

            loading: false,
            loadingMore: false,
            /** 分页失败标记（**绝不清空 items**） */
            moreError: false,
            errorText: '',

            /** 离线（只读缓存 + 加载更多置灰） */
            offline: false,
            /** 缓存写入时刻（离线命中时的来源标记） */
            cacheSavedAt: '',
            /** 网络恢复横幅是否可见（3s） */
            restoredVisible: false,

            /** 是否已完成首次 onShow（避免与 onLoad 双发请求，S3-2 时序纪律） */
            entered: false,

            /** 网络监听句柄 / 横幅定时器 */
            networkHandler: null,
            bannerTimer: null,

            rangeOptions: RANGE_OPTIONS
        }
    },
    computed: {
        /** 8 类指标切换项（顺序 = 后端 `METRIC_TYPES`，确定性渲染） */
        metricOptions: function () {
            return METRIC_TYPES.map(function (type) {
                return { value: type, label: metricLabel(type) }
            })
        },
        /** 今天的 `YYYY-MM-DD`（作为日期选择器的上界：**记录不可能发生在未来**） */
        today: function () {
            return todayString()
        },
        /**
         * 请求窗口（**半开区间 `[start, end)`**）。
         *   · 近 N 天（含今天）：`start = 今天−(N−1)`、`end = 明天`；
         *   · 自定义：`start = 开始日期`、`end = 结束日期 + 1 天`（**不拼 23:59:59**）。
         */
        windowRange: function () {
            if (this.rangeMode === 'custom') {
                return {
                    start: this.customStart,
                    end: this.customEnd ? addDays(this.customEnd, 1) : ''
                }
            }
            const days = Number(this.rangeMode) || 30
            return {
                start: shiftDay(1 - days),
                end: shiftDay(1)
            }
        },
        offlineBarText: function () {
            if (this.cacheSavedAt) {
                return '离线数据 · 更新于 ' + this.cacheSavedAt
            }
            return '当前离线'
        },
        offlineMoreText: function () {
            return OFFLINE_MORE_TEXT
        }
    },
    onLoad: function (query) {
        // 未登录守卫（S1-C ⑬：需登录）
        if (!requireLogin()) {
            return
        }

        const raw = query && query.type ? String(query.type) : ''
        // 非法 / 缺失 → 回落第一个指标（列表页本身可自行切换，不制造错误页）
        this.metricType = METRIC_TYPES.indexOf(raw) >= 0 ? raw : METRIC_TYPES[0]
        this.applyTitle()

        // 网络监听（**必须在 onLoad 注册**，S3-2 时序纪律）
        const self = this
        this.networkHandler = function (res) {
            self.handleNetworkChange(res)
        }
        uni.onNetworkStatusChange(this.networkHandler)

        // 先判定网络再发首次请求（离线直接走缓存只读，不发无谓请求）
        isOnline().then(function (online) {
            self.offline = !online
            self.load()
        })
    },
    onShow: function () {
        // 从 SC-09 删除成功返回 → 重新加载首屏（被删条目消失，S1-C ⑯）
        if (this.metricType && this.entered) {
            this.load()
        }
        this.entered = true
    },
    onReachBottom: function () {
        // 触底加载更多（S1-C ⑨）
        this.loadMore()
    },
    onUnload: function () {
        if (this.bannerTimer) {
            clearTimeout(this.bannerTimer)
            this.bannerTimer = null
        }
        if (this.networkHandler) {
            uni.offNetworkStatusChange(this.networkHandler)
            this.networkHandler = null
        }
    },
    methods: {
        /* ───────────── 数据加载（R-02） ───────────── */

        /**
         * 加载首屏。
         * 离线分支：**只读缓存**，命中即展示（不写回、不自动重放）；
         *           未命中 → 明确提示（**不显示误导性的"还没有记录"空态**）。
         */
        load: function () {
            const self = this
            if (!this.metricType) {
                return Promise.resolve()
            }

            if (this.offline) {
                this.loading = false
                this.loadingMore = false
                this.moreError = false
                this.errorText = ''
                // 先清来源标记：切换指标后若新指标无缓存，离线条不应残留旧指标的"更新于"
                this.cacheSavedAt = ''
                if (!this.readListCache()) {
                    this.items = []
                    this.errorText = OFFLINE_NO_CACHE_TEXT
                }
                return Promise.resolve()
            }

            this.loading = true
            this.errorText = ''
            this.moreError = false
            this.loadingMore = false
            this.nextCursor = ''
            this.hasMore = false

            const range = this.windowRange
            return listRecords({
                metric_type: this.metricType,
                start: range.start,
                end: range.end,
                limit: PAGE_SIZE
            }).then(function (res) {
                self.loading = false
                const data = res && res.data ? res.data : null
                if (!data) {
                    self.items = []
                    self.errorText = LOAD_FAIL_TEXT
                    return
                }
                self.items = data.items && data.items.length ? data.items : []
                self.nextCursor = data.next_cursor ? String(data.next_cursor) : ''
                self.hasMore = !!data.has_more
                self.saveListCache()
            }, function (err) {
                self.loading = false
                if (err && err.isNetwork) {
                    self.offline = true
                    if (self.readListCache()) {
                        return
                    }
                    self.items = []
                    self.errorText = OFFLINE_NO_CACHE_TEXT
                    return
                }
                self.items = []
                self.errorText = errorText(err)
            })
        },

        /**
         * 加载下一页（触底）。
         * ★ 分页失败：**绝不清空已显示的列表**，仅在列表底部提示可重试（S1-C ⑫）。
         * ★ 失败时**保留 `nextCursor`**，使"点击重试"能重发同一游标。
         */
        loadMore: function () {
            const self = this
            if (this.loading || this.loadingMore || !this.hasMore || this.moreError) {
                return Promise.resolve()
            }
            if (this.offline) {
                showToast('info', OFFLINE_MORE_TEXT)
                return Promise.resolve()
            }

            this.loadingMore = true
            const range = this.windowRange
            return listRecords({
                metric_type: this.metricType,
                start: range.start,
                end: range.end,
                limit: PAGE_SIZE,
                cursor: this.nextCursor
            }).then(function (res) {
                self.loadingMore = false
                const data = res && res.data ? res.data : null
                const more = data && data.items && data.items.length ? data.items : []
                // 追加（**不清空既有列表**）
                self.items = self.items.concat(more)
                self.nextCursor = data && data.next_cursor ? String(data.next_cursor) : ''
                self.hasMore = !!(data && data.has_more)
                self.saveListCache()
            }, function (err) {
                self.loadingMore = false
                // 分页失败：列表保持原状，底部出现「加载失败，点击重试」
                self.moreError = true
                if (err && err.isNetwork) {
                    self.offline = true
                }
            })
        },

        /** 分页重试（清标记后重发同一游标） */
        onRetryMore: function () {
            this.moreError = false
            this.loadMore()
        },

        applyTitle: function () {
            const label = metricLabel(this.metricType)
            uni.setNavigationBarTitle({ title: label ? label + ' 历史' : '记录历史' })
        },

        /* ───────────── ② 筛选条 ───────────── */

        /**
         * 时间范围切换。
         * 「自定义」→ 打开抽屉（**此时不改变 `rangeMode`**，取消即回到原选项，界面不会停留在无效状态）。
         */
        onRangeChange: function (value) {
            const next = String(value)
            if (next === 'custom') {
                if (!this.draftStart) {
                    this.draftStart = shiftDay(1 - 30)
                }
                if (!this.draftEnd) {
                    this.draftEnd = this.today
                }
                this.rangeVisible = true
                return
            }
            if (next === this.rangeMode) {
                return
            }
            this.rangeMode = next
            this.load()
        },

        onRangeCancel: function () {
            this.rangeVisible = false
        },

        /** 自定义范围确认：本地校验 → 生效 → 重新加载 */
        onRangeConfirm: function () {
            if (!this.draftStart || !this.draftEnd) {
                showToast('error', '请选择开始与结束日期')
                return
            }
            if (this.draftStart > this.draftEnd) {
                showToast('error', '开始日期不能晚于结束日期')
                return
            }
            this.customStart = this.draftStart
            this.customEnd = this.draftEnd
            this.rangeMode = 'custom'
            this.rangeVisible = false
            this.load()
        },

        /** 指标切换（默认锁定 `?type=`，可切；切换后清空列表并重新加载首屏） */
        onMetricChange: function (value) {
            const next = String(value)
            if (next === this.metricType) {
                return
            }
            this.metricType = next
            this.items = []
            this.nextCursor = ''
            this.hasMore = false
            this.moreError = false
            this.errorText = ''
            this.cacheSavedAt = ''
            this.applyTitle()
            this.load()
        },

        /* ───────────── ③ 列表 ───────────── */

        /**
         * 行的**展示用记录对象**（不改变接口数据，只决定 C-27 的渲染取值）。
         *
         * ① 非睡眠：原样透传（`live` 语义与后端 `_view` 完全一致）。
         * ② 睡眠：`value_1`（睡眠质量分）**SC-08 表单不采集**（`MAIN_FIELDS.sleep = []`）
         *    ⇒ 直传会让主值恒为「—」并带出无意义的单位「score」。
         *    因此与 **SC-08 录入页 / SC-09 详情页同口径**：`value_1` 缺失时用
         *    `sleepDurationHours(入睡, 起床)`（与后端 `derived_for` 的 `sleep_duration_hours`
         *    同一公式，S3-2 已封板）作为主值，单位「小时」。
         *    ★ 仅在 `value_1` 确实有值时才回落到原值 —— **绝不覆盖接口下发的真实数据**。
         *    ★ 完整时间信息（入睡 / 起床）不在此处，见 `subValueOf` 与 SC-09 详情页。
         */
        rowRecord: function (item) {
            if (!item || item.metric_type !== 'sleep') {
                return item
            }
            const raw = item.value_1
            if (raw !== null && raw !== undefined && raw !== '') {
                return item
            }
            const hours = sleepDurationHours(item.time_start, item.recorded_at)
            if (hours === null) {
                return item
            }
            return Object.assign({}, item, { value_1: hours, unit: SLEEP_HOURS_UNIT })
        },

        /**
         * 次值小字（S1-C ③：「主值 + 单位 + 测量时间（+ 次值小字）」）。
         *
         * · 血压 → `value_2` 显示为「/80」；运动 → `value_2` 显示为「卡路里 120」
         *   （取值口径与 SC-09 详情页副值一致，来源 `utils/metrics.js` 的 `VALUE_FIELD_LABEL`）。
         * · 睡眠 → **`time_start`（入睡时间）**，显示为「入睡 MM-DD HH:mm」。
         *   ★ 语义铁律（S0 9.4 / S2 数据契约）：`recorded_at` = **起床时间**，`time_start` = **入睡时间**；
         *     行左侧的「时间」列就是 `recorded_at`（= 起床时间），因此右侧必须明确标注「入睡」，
         *     **绝不能把 `recorded_at` 当作入睡时间展示**，也不显示 `undefined` / `null` / `NaN`
         *     （`toShortMinute` 对空值返回 ''，此处直接不渲染）。
         * 字段无值 / 未登记 → ''（**不渲染**，不编造）。
         */
        subValueOf: function (item) {
            if (!item) {
                return ''
            }
            if (item.metric_type === 'sleep') {
                const start = toShortMinute(item.time_start)
                return start ? SLEEP_START_PREFIX + start : ''
            }
            const labels = VALUE_FIELD_LABEL[item.metric_type] || {}
            const raw = item.value_2
            if (raw === null || raw === undefined || raw === '' || !labels.value_2) {
                return ''
            }
            if (item.metric_type === 'bp') {
                return '/' + String(raw)
            }
            return labels.value_2 + ' ' + String(raw)
        },

        /**
         * 点击条目 → SC-09 详情（带 `id` 与 `type`）。
         *
         * ★ 载荷由**模板显式传入**（`@tap="onItemTap(item)"`）—— 这是本工程的既有约定
         *   （参见 `index.vue` 的 `@tap="onGoalEntry(goal)"` / `C-27` / `C-29` 同类写法）。
         *   原因：uni-app H5 会把父级写在**自定义组件**上的 `@tap` 编译为 DOM `onClick`，
         *   而组件内部的 `$emit('tap', 载荷)` 需要父级提供 `onTap` 才能命中 ⇒
         *   若写成裸 `@tap="onItemTap"`，本方法收到的是**原生事件对象**（无 `id`），
         *   会被下面的守卫静默拦下 → 点击"毫无反应"（S3-3 人工验收缺陷的根因）。
         */
        onItemTap: function (record) {
            if (!record || record.id === null || record.id === undefined) {
                return
            }
            const type = record.metric_type ? String(record.metric_type) : this.metricType
            navigateTo(ROUTES.RECORD_DETAIL + '?id=' + record.id + '&type=' + type)
        },

        /** 空态「去记录」→ SC-08（带当前指标） */
        onGoRecord: function () {
            navigateTo(ROUTES.RECORD_ADD + '?type=' + this.metricType)
        },

        /* ───────────── 本地缓存（离线只读） ───────────── */

        /**
         * 写入列表缓存（**按 metric_type 切分**）。
         *
         * 口径（S1-B 第三批 C1）：① 每指标 ≤ 200 条；② 仅近 30 天；③ 取交集。
         * 安全边界：只缓存**界面展示所需的记录字段** —— 不含密码 / Token / `file_token` /
         *   `file_path` / 他人数据 / 删除数据；且 `cache.` 前缀随「登出 / 注销 / 401 / 改密」自动清除。
         */
        saveListCache: function () {
            const type = this.metricType
            if (!type || !this.items.length) {
                return
            }
            const from = shiftDay(1 - RECORD_LIST_MAX_DAYS)
            const kept = []
            for (let i = 0; i < this.items.length; i++) {
                if (kept.length >= RECORD_LIST_MAX_ITEMS) {
                    break
                }
                const day = String(this.items[i].recorded_at || '').slice(0, 10)
                if (day && day >= from) {
                    kept.push(this.items[i])
                }
            }
            if (kept.length) {
                saveCache(recordListKey(type), { items: kept })
            }
        },

        /**
         * 读列表缓存（离线只读，**不写回、不重放**）。
         * 缓存是"服务端某一刻的快照"，**没有分页语义** ⇒ 命中后 `hasMore = false`。
         * @returns {boolean} 是否命中
         */
        readListCache: function () {
            const cached = loadCache(recordListKey(this.metricType))
            const items = cached && cached.data && cached.data.items ? cached.data.items : null
            if (!items || !items.length) {
                return false
            }
            this.items = items
            this.cacheSavedAt = cached.savedAt
            this.nextCursor = ''
            this.hasMore = false
            return true
        },

        /* ───────────── 网络 ───────────── */

        /**
         * 网络变化：离线 → 只读；**恢复 → 刷新当前页（读操作）**，绝不自动重放写操作（S1-D §5）。
         */
        handleNetworkChange: function (res) {
            const online = !!(res && res.isConnected)
            const wasOffline = this.offline
            this.offline = !online
            if (!online) {
                return
            }
            if (wasOffline) {
                this.showRestoredBanner()
                this.load()
            }
        },

        showRestoredBanner: function () {
            const self = this
            this.restoredVisible = true
            if (this.bannerTimer) {
                clearTimeout(this.bannerTimer)
            }
            this.bannerTimer = setTimeout(function () {
                self.restoredVisible = false
                self.bannerTimer = null
            }, NETWORK_BANNER_MS)
        }
    }
}
</script>

<style scoped lang="scss">
.history {
    min-height: 100vh;
    background-color: var(--s-page);
}

.history__body {
    /* A 类系统导航栏占位由平台负责，此处只留内容区节奏 */
    padding-top: var(--page-pad-t);
    padding-bottom: var(--page-pad-b);
}

/* 内容最大宽居中（DESIGN.md §10.4③） */
.history__inner {
    max-width: var(--content-max);
    margin-left: auto;
    margin-right: auto;
    padding-left: var(--gutter);
    padding-right: var(--gutter);
}

.history__block {
    margin-bottom: var(--card-gap);
}

.history__filter {
    margin-bottom: var(--sp-4);
}

.history__metrics {
    margin-bottom: var(--sp-5);
}

/* ── 触底加载更多状态区 ── */
.history__more {
    display: flex;
    flex-direction: row;
    align-items: center;
    justify-content: center;
    padding-top: var(--sp-3);
    padding-bottom: var(--sp-6);
}

.history__more-plain {
    display: flex;
    flex-direction: row;
    align-items: center;
    justify-content: center;
    min-height: var(--tap-min);
}

.history__more-text {
    font-size: var(--fs-caption);
    line-height: $lh-caption;
    color: var(--t-3);
    letter-spacing: 0;
}

/* 离线提示用更弱的层级（表达"该动作已不可用"） */
.history__more-text--muted {
    color: var(--t-4);
}

.history__more-retry {
    display: flex;
    flex-direction: row;
    align-items: center;
    justify-content: center;
    min-height: var(--tap-min);
    padding-left: var(--sp-7);
    padding-right: var(--sp-7);
    border-radius: var(--r-md);
    border: 1rpx solid var(--b-border);
    background-color: var(--s-card);
    transition: transform var(--d-fast) var(--ease-std), opacity var(--d-fast) var(--ease-std);
}

.history__more-retry--press {
    transform: scale(var(--press-scale));
    opacity: var(--press-opacity);
}

.history__more-retry-text {
    font-size: var(--fs-btn-m);
    line-height: $lh-btn-m;
    font-weight: $fw-medium;
    color: var(--c-p-600);
    letter-spacing: 0;
}

/* ── 自定义范围抽屉内容 ── */
.history__range {
    display: flex;
    flex-direction: column;
}

.history__range-item {
    margin-bottom: var(--sp-5);
}

.history__range-hint {
    display: block;
    font-size: var(--fs-caption);
    line-height: $lh-caption;
    color: var(--t-3);
    letter-spacing: 0;
}
</style>
