<template>
    <!--
      SC-06 首页（pages/index/index）  tabBar ①
      依据：S1-C §二 SC-06 ｜ DESIGN.md §11 / §12 / §13 / §10.3（B 类：自绘顶栏）

      结构（与 S1-C 逐项对应）：
        [① 顶部栏]            自绘顶栏（品牌）+ 欢迎 / 身份区（含「今天 · <日期>」）
        [② 今日概览卡]  F-010 已记录 N 项 + 今日已记指标 + 目标进度环 ×N + 未确认提醒行（条件）
        [③ 快捷录入区]  F-011 4 卡：体重 / 血压 / 饮水 / 运动（C-28）
        [④ 今日目标进度] F-013 环形 + 进度条 + 「当前值 / 目标值」+「还差 X」（C-25）
        [⑤ 最近记录]     F-012 最近 10 条时间线（C-27）
        [⑥ 查看趋势入口]
        [⑦ 底部]         tabBar（C-11，本批仅"首页"可点，见组件内说明）

      数据来源：**唯一接口 S-01 `GET /api/v1/home/overview`**（一次聚合，不分页、最近 10 条）。
        `reminder_fallback` 是服务端的占位声明，**客户端忽略**（提醒计数为纯本地计算）。

      状态覆盖（DESIGN.md §13 底线清单）：
        正常 / 加载（骨架屏，> 8s 追加「仍在加载，请稍候」）/ 失败（**局部失败只失败局部** + 重试入口，
        5xx → 「服务器繁忙，请稍后重试」）/ 未登录（守卫 → SC-03）/ 离线（命中缓存 → 只读展示 +
        「离线数据 · 更新于 <时间>」；未命中 → 空状态 + 离线标记；网络恢复 → **自动刷新本页**）、
        提交防重 → **N/A**（本页无写操作，写操作在 SC-08）、高风险确认 → **N/A**（无可危操作）、
        401 → 由统一请求层处理（单次 Refresh → 重放；失败清栈回 SC-03）。

      ★ 如实登记（本轮不做、不伪造）：
        1. [⑥ 查看趋势] → SC-11（S3-4）、[③ 快捷卡] → SC-08（S3-2 后续步骤）、[④ 环/卡] → SC-12（S3-5）、
           [⑤ 记录行] → SC-09（S3-3）、[未确认提醒行] → SC-14（S3-6）**均尚未实现**。
           按既有约定（`utils/route.js`：未实现路径**不写入** `ROUTES`，避免死链接），
           这些入口**保留完整视觉但不建立跳转**；待对应批次落地后在此处接上 `ROUTES` 即可。
        2. [未确认提醒行] 计数恒为 0（本地提醒模块属 S3-6）→ 该行不渲染。
        3. ⑯「返回后高亮刚记的那一项」需要来源页回传标记，SC-08 落地后一并接入；
           本批只做「返回本页自动刷新」（DESIGN.md §7④）。
        4. `--content-max` 内容最大宽居中按 §10.4③ 在本页落地。
    -->
    <view class="home">
        <AppNavBar title="康迹" />

        <view class="home__body">
            <view class="home__inner">
                <!-- 离线只读标记（离线且命中缓存 / 无缓存时展示） -->
                <view v-if="offlineBarText" class="home__notice">
                    <AppOfflineBar variant="offline" :text="offlineBarText" />
                </view>

                <!-- 网络恢复横幅（3s 后自行撤下，DESIGN.md §8.2 C-17） -->
                <view v-if="restoredVisible" class="home__notice">
                    <AppOfflineBar variant="restored" text="网络已恢复，正在刷新" />
                </view>

                <!-- ① 欢迎 / 身份区（含「今天 · <日期>」） -->
                <view class="home__hello">
                    <text class="home__greet">{{ greetText }}</text>
                    <text class="home__date">今天 · {{ dateText }}</text>
                </view>

                <!-- ② 今日概览卡 -->
                <AppCard title="今日概览" class="home__block">
                    <view v-if="loading">
                        <AppSkeleton variant="card" />
                        <text v-if="slowLoading" class="home__slow">仍在加载，请稍候</text>
                    </view>

                    <view v-else-if="loadError">
                        <AppErrorState
                            variant="inline"
                            :text="errorText"
                            retry-text="重试"
                            @retry="reload"
                        />
                    </view>

                    <template v-else>
                        <view class="home__overview">
                            <view class="home__count">
                                <text class="home__count-num">{{ todayCount }}</text>
                                <text class="home__count-label">已记录项</text>
                            </view>

                            <view
                                v-if="reminderCount > 0"
                                class="home__reminder"
                                hover-class="home__reminder--press"
                                :hover-start-time="0"
                                :hover-stay-time="80"
                                @tap="onReminderEntry"
                            >
                                <text class="home__reminder-text">{{ reminderText }}</text>
                                <view class="home__chevron"></view>
                            </view>
                        </view>

                        <view v-if="todayMetrics.length" class="home__chips">
                            <view
                                v-for="type in todayMetrics"
                                :key="type"
                                class="home__chip"
                            >
                                <text class="home__chip-text">{{ metricName(type) }}</text>
                            </view>
                        </view>
                        <text v-else class="home__muted">{{ offlineNoCache ? '当前离线，暂无本地缓存数据' : '今天还没有记录' }}</text>

                        <view v-if="goals.length" class="home__rings">
                            <view
                                v-for="goal in goals"
                                :key="goal.goal_id"
                                class="home__ring-item"
                                hover-class="home__ring-item--press"
                                :hover-start-time="0"
                                :hover-stay-time="80"
                                @tap="onGoalEntry(goal)"
                            >
                                <ProgressRing :percent="ringPercent(goal)" size="s">
                                    <text class="home__ring-percent">{{ ringPercentText(goal) }}</text>
                                </ProgressRing>
                                <text class="home__ring-label">{{ goalName(goal) }}</text>
                            </view>
                        </view>
                        <text v-else class="home__muted">还没有设置目标</text>
                    </template>
                </AppCard>

                <!-- ③ 快捷录入区 -->
                <view class="home__block">
                    <text class="home__section">快速记录</text>
                    <QuickRecordGrid :highlight="showEmptyGuide" @select="onRecordEntry" />
                </view>

                <!-- ④ 今日目标进度 -->
                <view class="home__block">
                    <text class="home__section">今日目标进度</text>

                    <view v-if="loading">
                        <AppSkeleton variant="card" />
                    </view>
                    <view v-else-if="loadError">
                        <AppErrorState
                            variant="inline"
                            :text="errorText"
                            retry-text="重试"
                            @retry="reload"
                        />
                    </view>
                    <text v-else-if="!goals.length" class="home__muted">还没有设置目标</text>
                    <template v-else>
                        <GoalProgressCard
                            v-for="goal in goals"
                            :key="goal.goal_id"
                            :goal="goal"
                            class="home__goal"
                            @tap="onGoalEntry(goal)"
                        />
                    </template>
                </view>

                <!-- ⑤ 最近记录（F-012 最近 10 条） -->
                <AppCard title="最近记录" class="home__block">
                    <view v-if="loading">
                        <AppSkeleton variant="list" />
                    </view>

                    <view v-else-if="loadError">
                        <AppErrorState
                            variant="inline"
                            :text="errorText"
                            retry-text="重试"
                            @retry="reload"
                        />
                    </view>

                    <AppEmpty
                        v-else-if="showEmptyGuide"
                        variant="first-use"
                        text="还没有记录，今天从一次记录开始"
                        hint="记满 2 条后，趋势页就能画出你的变化曲线"
                        action-text="去记录"
                        @action="onRecordEntry"
                    />

                    <view v-else class="home__list">
                        <RecordItem
                            v-for="(record, index) in recentRecords"
                            :key="record.id"
                            :record="record"
                            variant="timeline"
                            :last="index === recentRecords.length - 1"
                            @tap="onRecordEntry(record)"
                        />
                    </view>
                </AppCard>

                <!-- ⑥ 查看趋势入口 -->
                <view
                    class="home__entry"
                    hover-class="home__entry--press"
                    :hover-start-time="0"
                    :hover-stay-time="80"
                    @tap="onTrendEntry"
                >
                    <text class="home__entry-text">查看趋势</text>
                    <view class="home__chevron"></view>
                </view>
            </view>
        </view>

        <!-- ⑦ 底部 tabBar -->
        <AppTabBar :items="tabItems" current="home" @select="onTabSelect" />

        <!-- 轻提示宿主（401 会话失效提示由统一请求层经此渲染） -->
        <AppToast />

        <!-- 开发环境页面预览器（仅 H5 非生产环境渲染；生产构建下为空节点，不影响正式功能） -->
        <DevPagePreviewer />
    </view>
</template>

<script>
import AppNavBar from '../../components/AppNavBar.vue'
import AppCard from '../../components/AppCard.vue'
import AppSkeleton from '../../components/AppSkeleton.vue'
import AppErrorState from '../../components/AppErrorState.vue'
import AppEmpty from '../../components/AppEmpty.vue'
import AppOfflineBar from '../../components/AppOfflineBar.vue'
import AppTabBar from '../../components/AppTabBar.vue'
import AppToast from '../../components/AppToast.vue'
import ProgressRing from '../../components/ProgressRing.vue'
import GoalProgressCard from '../../components/GoalProgressCard.vue'
import RecordItem from '../../components/RecordItem.vue'
import QuickRecordGrid from '../../components/QuickRecordGrid.vue'
// 开发环境专用页面预览器（**仅 H5 + 非生产**生效；不注册进 `pages.json`、不计入 25 页）
import DevPagePreviewer from '../../components/DevPagePreviewer.vue'

import { ROUTES, navigateTo, reLaunch, requireLogin } from '../../utils/route'
import { useUserStore } from '../../store/user'
import { fetchHomeOverview } from '../../api/home'
import { CACHE_KEYS, loadCache, saveCache } from '../../utils/cache'
import { metricLabel, goalLabel } from '../../utils/metrics'
import { todayString } from '../../utils/validate'
import { errorText } from '../../utils/request'
import { NETWORK_BANNER_MS, SLOW_LOADING_MS } from '../../utils/config'
import { pendingToday, missedRecent } from '../../utils/reminder'

export default {
    components: {
        AppNavBar: AppNavBar,
        AppCard: AppCard,
        AppSkeleton: AppSkeleton,
        AppErrorState: AppErrorState,
        AppEmpty: AppEmpty,
        AppOfflineBar: AppOfflineBar,
        AppTabBar: AppTabBar,
        AppToast: AppToast,
        ProgressRing: ProgressRing,
        GoalProgressCard: GoalProgressCard,
        RecordItem: RecordItem,
        QuickRecordGrid: QuickRecordGrid,
        DevPagePreviewer: DevPagePreviewer
    },
    data: function () {
        return {
            /** 首屏加载中（有缓存时直接为 false —— 不用骨架屏遮挡已有内容） */
            loading: true,
            /** > 8s 追加「仍在加载，请稍候」（DESIGN.md §7④） */
            slowLoading: false,
            /** 请求失败（且无内容可展示）→ 局部失败：只失败概览与最近记录两个区块 */
            loadError: false,
            errorText: '加载失败，点击重试',
            /** 离线只读（网络不可用） */
            offline: false,
            /** 离线且**无本地缓存** → 空状态 + 离线标记 */
            offlineNoCache: false,
            /** 缓存写入时刻（用于「离线数据 · 更新于 <时间>」） */
            cacheSavedAt: '',
            /** S-01 的 data */
            overview: null,
            /** 网络恢复横幅是否可见（3s） */
            restoredVisible: false,
            /** 本次 onShow 之前是否已加载过（用于「返回本页自动刷新」） */
            entered: false,
            /** 内部定时器句柄 */
            slowTimer: null,
            bannerTimer: null,
            /**
             * 「未确认提醒 N 条」计数（S3-6 起接真实本地数据）。
             * 刻意用 data 而非 computed：`pendingToday()` 读的是 `uni.getStorageSync`
             *   （同步但**非响应式**），若写成 computed，Vue2 会把首次结果**永久缓存** ——
             *   用户去 SC-14 增删提醒后返回首页，数字不会变。故改为 data + onShow 手动重算。
             */
            reminderCount: 0,
            /** true ⇒ 文案走「近 3 日错过」（当日为 0 且近 3 日有错过时的兜底口径） */
            reminderMissedMode: false,
            tabItems: [
                { key: 'home', label: '首页', enabled: true },
                { key: 'record', label: '记录中心', enabled: true },
                { key: 'trend', label: '趋势', enabled: true },
                { key: 'mine', label: '我的', enabled: true }
            ]
        }
    },
    computed: {
        todayCount: function () {
            const today = this.overview && this.overview.today
            return today && today.record_count !== undefined ? today.record_count : 0
        },
        todayMetrics: function () {
            const today = this.overview && this.overview.today
            return today && today.metric_types_recorded ? today.metric_types_recorded : []
        },
        goals: function () {
            return this.overview && this.overview.goals ? this.overview.goals : []
        },
        recentRecords: function () {
            return this.overview && this.overview.recent_records ? this.overview.recent_records : []
        },
        /** 「今天」以**服务端日期**为准（口径统一）；离线无数据时回退本机日期 */
        dateText: function () {
            if (this.overview && this.overview.date) {
                return String(this.overview.date)
            }
            return todayString()
        },
        /** 欢迎语：只使用本地已缓存的登录用户名；无则退回中性问候（不编造昵称） */
        greetText: function () {
            const name = useUserStore().username
            return name ? '你好，' + name : '你好'
        },
        /** 首次使用引导：今日 0 条且无任何历史记录（SC-06 ⑩） */
        showEmptyGuide: function () {
            return !this.loading && !this.loadError && this.todayCount === 0 &&
                this.recentRecords.length === 0
        },
        offlineBarText: function () {
            if (!this.offline) {
                return ''
            }
            if (this.cacheSavedAt) {
                return '离线数据 · 更新于 ' + this.cacheSavedAt
            }
            return '当前离线，暂无本地缓存数据'
        },
        /**
         * 「未确认提醒 N 条」文案 —— **纯本地**（S1-C SC-06 ⑰：提醒模块**无服务端接口**）。
         * 兜底口径（S1-C A-11）：优先"当日未确认"；当日为 0 且近 3 日有错过
         *   → 「近 3 日错过 N 条」。数据源见 refreshReminder()（onShow 重算）。
         */
        reminderText: function () {
            if (this.reminderMissedMode) {
                return '近 3 日错过 ' + this.reminderCount + ' 条'
            }
            return '未确认提醒 ' + this.reminderCount + ' 条'
        }
    },
    onLoad: function () {
        // 未登录守卫（SC-06 ⑬：访客 → SC-03）；守卫内部已清栈跳转
        if (!requireLogin()) {
            return
        }

        // 先读本地缓存：命中 → 立即渲染（离线只读的基础），再向服务端刷新
        const cached = loadCache(CACHE_KEYS.HOME_OVERVIEW)
        if (cached) {
            this.overview = cached.data
            this.cacheSavedAt = cached.savedAt
            this.loading = false
        } else {
            this.startSlowTimer()
        }

        // 网络恢复 → 自动刷新本页
        // （S1-C SC-06 ⑭③ / S1-D §5：只刷当前页、**不自动重放**写操作）
        const self = this
        this.networkHandler = function (res) {
            self.handleNetworkChange(res)
        }
        uni.onNetworkStatusChange(this.networkHandler)

        this.fetchOverview()
    },
    onShow: function () {
        // 返回本页自动刷新（DESIGN.md §7④）；首次进入由 onLoad 负责，避免重复请求
        if (this.entered) {
            this.fetchOverview(true)
        }
        this.entered = true
        // 提醒计数为纯本地数据、无响应式来源 ⇒ 每次显示都重算（S3-6：A-11 区块 onShow 刷新）
        this.refreshReminder()
    },
    onUnload: function () {
        this.clearTimers()
        // 注销网络监听（避免页面销毁后仍持有回调）
        if (this.networkHandler) {
            uni.offNetworkStatusChange(this.networkHandler)
            this.networkHandler = null
        }
    },
    onHide: function () {
        // 空实现：本页无后台任务、无计时型业务
    },
    methods: {
        /* ───────────── 提醒计数（纯本地） ───────────── */

        /**
         * 重算「未确认提醒」计数（S3-6）。
         * 口径（S1-C A-11）：当日未确认优先；当日为 0 且近 3 日有错过 ⇒ 走错过分支。
         * 两者都取**实际展示条数**（reminder.js 内已封顶 5 条）——
         * 与 SC-14 兜底区块同一数字口径，避免首页与提醒页显示不一致。
         */
        refreshReminder: function () {
            const pending = pendingToday()
            if (pending.length > 0) {
                this.reminderMissedMode = false
                this.reminderCount = pending.length
                return
            }
            const missed = missedRecent()
            this.reminderMissedMode = missed.length > 0
            this.reminderCount = missed.length
        },
        /** 点进提醒列表页（SC-14） */
        onReminderEntry: function () {
            navigateTo(ROUTES.REMINDER)
        },

        /* ───────────── 数据加载 ───────────── */

        reload: function () {
            this.loadError = false
            if (!this.overview) {
                this.loading = true
                this.startSlowTimer()
            }
            this.fetchOverview()
        },

        /**
         * 拉取 S-01 首页概览。
         * @param {boolean} silent 静默刷新（保留已有内容，不显示骨架屏）
         */
        fetchOverview: function (silent) {
            const self = this
            return fetchHomeOverview().then(function (res) {
                const data = res && res.data ? res.data : {}
                self.overview = data
                self.loading = false
                self.loadError = false
                self.slowLoading = false
                self.offline = false
                self.offlineNoCache = false
                self.cacheSavedAt = ''
                self.clearSlowTimer()
                // 写缓存供离线只读（TTL 24h；四触发时随 kj:cache.* 清除）
                saveCache(CACHE_KEYS.HOME_OVERVIEW, data)
            }, function (err) {
                self.loading = false
                self.slowLoading = false
                self.clearSlowTimer()

                if (err && err.isNetwork) {
                    // 离线：命中缓存 → 保持只读展示；未命中 → 空状态（均由离线条标记）
                    self.offline = true
                    self.offlineNoCache = !self.overview
                    return
                }
                // 业务 / 服务端失败：**局部失败只失败局部**（概览区与最近记录区各自可重试）
                if (!self.overview) {
                    self.loadError = true
                    self.errorText = errorText(err)
                }
            })
        },

        /* ───────────── 网络状态 ───────────── */

        handleNetworkChange: function (res) {
            const online = !!(res && res.isConnected)
            if (!online) {
                this.offline = true
                return
            }
            // 恢复：撤下离线标记 → 展示 3s 恢复横幅 → 自动刷新本页
            this.offline = false
            this.showRestoredBanner()
            this.fetchOverview(true)
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
        },

        /* ───────────── 定时器 ───────────── */

        startSlowTimer: function () {
            const self = this
            this.clearSlowTimer()
            this.slowTimer = setTimeout(function () {
                self.slowLoading = true
                self.slowTimer = null
            }, SLOW_LOADING_MS)
        },

        clearSlowTimer: function () {
            if (this.slowTimer) {
                clearTimeout(this.slowTimer)
                this.slowTimer = null
            }
        },

        clearTimers: function () {
            this.clearSlowTimer()
            if (this.bannerTimer) {
                clearTimeout(this.bannerTimer)
                this.bannerTimer = null
            }
        },

        /* ───────────── 展示口径 ───────────── */

        metricName: function (type) {
            return metricLabel(type)
        },

        goalName: function (goal) {
            return goalLabel(goal && goal.goal_type)
        },

        ringPercent: function (goal) {
            const n = Number(goal && goal.progress_percent)
            if (isNaN(n) || n < 0) {
                return 0
            }
            return n > 100 ? 100 : n
        },

        ringPercentText: function (goal) {
            const n = Number(goal && goal.progress_percent)
            return String(isNaN(n) ? 0 : Math.round(n)) + '%'
        },

        /* ───────────── 入口 ───────────── */

        /**
         * 记录入口统一分发（S3-2 第二批接线 SC-07 / SC-08；**S3-3 补第 ② 支 → SC-09 详情**）。
         *
         * 三种来源 → 三种落点（**不做兜底猜测，未实现的目标一律不建立跳转**）：
         *   ① 快捷录入卡（C-10 `QuickRecordGrid`）→ `item = { type, label, unit }`
         *      → SC-08 `pages/record/add?type=<type>`（直接进对应指标录入页）；
         *   ② 最近记录行（C-27 `RecordItem`）→ `item = 记录对象`（含 `id` / `metric_type`）
         *      → **SC-09 `pages/record/detail?id=<id>&type=<metric_type>`**（S3-3 落地接通）；
         *   ③ 空态主行动按钮（C-14 `AppEmpty`「去记录」）→ **无载荷**
         *      → SC-07 记录中心（与 S1-C：SC-20「还没有任何数据」+「去记录」→ SC-07 同口径，
         *        让用户先从 8 类指标中挑一项）。
         *
         * ★ 载荷传递约定（本工程铁律，S3-3 人工验收缺陷后固化）：
         *   对**带载荷**抛 `tap` 的自定义组件（如 `RecordItem` 的 `$emit('tap', record)`、
         *   `GoalProgressCard` 的 `$emit('tap', goal)`），父级**必须把载荷写进模板表达式**：
         *   `@tap="onRecordEntry(record)"`，**不得**写成裸 `@tap="onRecordEntry"`。
         *   原因：uni-app H5 会把写在组件上的 `@tap` 编译成 **DOM `onClick`**，组件内部
         *   `$emit('tap', 载荷)` 需要父级提供 `onTap` 才能命中 ⇒ 裸写法下本方法收到的是
         *   **原生事件对象**（无 `type` / 无 `metric_type`）⇒ 会错误落到第 ③ 支。
         *   同类既有正确写法：`@tap="onGoalEntry(goal)"`（C-26）、`@tap="handleTap(item)"`（C-10/C-24）。
         */
        onRecordEntry: function (item) {
            if (item && item.type) {
                navigateTo(ROUTES.RECORD_ADD + '?type=' + item.type)
                return
            }
            if (item && item.metric_type) {
                // ② 最近记录行 → SC-09 详情（S3-3 接线）
                // `id` 缺失时保持"不跳转"（宁可不跳，也不进一个查不到记录的详情页）
                if (item.id === null || item.id === undefined) {
                    return
                }
                navigateTo(ROUTES.RECORD_DETAIL + '?id=' + item.id + '&type=' + item.metric_type)
                return
            }
            reLaunch(ROUTES.RECORD)
        },

        /**
         * 目标进度环 / 目标卡 → SC-12 目标页（S3-5 落地）。
         * 目标页 `pages/goal/index` 已注册进 `pages.json`（**A 类：系统导航栏，不加
         * `navigationStyle: custom`**），路由 `ROUTES.GOAL` 已登记，故此处接通为**跳转**。
         *
         * 本入口**不带载荷参数**：SC-12 是"全部目标"聚合页（4 类目标一起展示），
         * 与被点击的那张卡属于哪一类无关 ⇒ 不进 `onGoalEntry(goal)` 的载荷分支。
         * 载荷仍按 `@tap="onGoalEntry(goal)"` 写法传入（见 `onRecordEntry` 上方的载荷传递约定），
         * 此处只是**刻意不消费**它。
         */
        onGoalEntry: function () {
            navigateTo(ROUTES.GOAL)
        },

        /**
         * 「查看趋势」→ SC-11 趋势页（S3-4 落地：uCharts 已在本批次以 uni_modules 形式安装）。
         * 目标页 `pages/trend/index` 已注册进 `pages.json`（`navigationStyle: custom`），
         * 路由 `ROUTES.TREND` 已登记，故此处接通为**跳转**。
         * 本入口**不带筛选参数**：趋势页默认指标 = 后端 `METRIC_TYPES` 首项（与 S1-C SC-11 一致）。
         */
        onTrendEntry: function () {
            navigateTo(ROUTES.TREND)
        },

        /**
         * tabBar 切换：「首页」即当前页，C-11 **不对当前项派发事件**（故无 home 分支）；
         * 「记录中心」（SC-07）、「趋势」（SC-11，S3-4 落地）、「我的」（SC-18，S3-7 落地，tabBar ④）
         * 均为启用项 —— 四项之间互相切换**一律用清栈 `reLaunch`**（tabBar 是平级切换，
         * 不允许层层压栈返回；与 S3-2/S3-4 既有口径一致）。
         * 依据：S1-C SC-06 ⑦「首页 / 记录中心 / 趋势 / 我的」与 `DESIGN.md §11` tabBar（4 项）。
         */
        onTabSelect: function (item) {
            if (!item || !item.key) {
                return
            }
            if (item.key === 'record') {
                reLaunch(ROUTES.RECORD)
                return
            }
            if (item.key === 'trend') {
                reLaunch(ROUTES.TREND)
                return
            }
            if (item.key === 'mine') {
                reLaunch(ROUTES.MINE)
            }
        }
    }
}
</script>

<style scoped lang="scss">
.home {
    min-height: 100vh;
    background-color: var(--s-page);
}

.home__body {
    padding-top: var(--nav-total-h);
    /* 底部固定区 = tabBar 总高 + 区块间距 */
    padding-bottom: calc(var(--tabbar-total-h) + var(--section-gap));
}

/* 内容最大宽居中（DESIGN.md §10.4③） */
.home__inner {
    max-width: var(--content-max);
    margin-left: auto;
    margin-right: auto;
    padding-left: var(--gutter);
    padding-right: var(--gutter);
}

.home__notice {
    margin-top: var(--sp-5);
}

/* ── ① 欢迎 / 身份区 ── */
.home__hello {
    display: flex;
    flex-direction: column;
    padding-top: var(--sp-8);
    padding-bottom: var(--sp-5);
}

.home__greet {
    font-size: var(--fs-h1);
    line-height: $lh-h1;
    font-weight: $fw-semibold;
    color: var(--t-1);
    letter-spacing: 0;
}

.home__date {
    margin-top: var(--sp-2);
    font-size: var(--fs-sub);
    line-height: $lh-sub;
    color: var(--t-3);
    letter-spacing: 0;
}

/* ── 区块节奏 ── */
.home__block {
    margin-bottom: var(--section-gap);
}

.home__section {
    display: block;
    margin-bottom: var(--sp-5);
    font-size: var(--fs-h2);
    line-height: $lh-h2;
    font-weight: $fw-semibold;
    color: var(--t-1);
    letter-spacing: 0;
}

.home__goal {
    margin-bottom: var(--card-gap);
}

/* ── ② 概览 ── */
.home__overview {
    display: flex;
    flex-direction: row;
    align-items: center;
    justify-content: space-between;
}

.home__count {
    display: flex;
    flex-direction: row;
    align-items: baseline;
}

.home__count-num {
    font-size: var(--fs-metric-xl);
    line-height: $lh-metric-xl;
    font-weight: $fw-semibold;
    color: var(--t-1);
    letter-spacing: 0;
}

.home__count-label {
    margin-left: var(--sp-3);
    font-size: var(--fs-sub);
    line-height: $lh-sub;
    color: var(--t-3);
    letter-spacing: 0;
}

.home__reminder {
    display: flex;
    flex-direction: row;
    align-items: center;
    min-height: var(--tap-min);
    padding-left: var(--sp-4);
    transition: transform var(--d-fast) var(--ease-std), opacity var(--d-fast) var(--ease-std);
}

/* 按下反馈（DESIGN.md §7①：scale + opacity，时长 --d-fast；与 .home__ring-item--press 同口径） */
.home__reminder--press {
    transform: scale(var(--press-scale));
    opacity: var(--press-opacity);
}

.home__reminder-text {
    font-size: var(--fs-btn-m);
    line-height: $lh-btn-m;
    font-weight: $fw-medium;
    color: var(--t-link);
    letter-spacing: 0;
}

/* 右向箭头：纯 CSS 几何（旋转 45° 的两段边框），不用图标库 */
.home__chevron {
    width: 9px;
    height: 9px;
    margin-left: var(--sp-3);
    border-top: 2px solid var(--t-3);
    border-right: 2px solid var(--t-3);
    transform: rotate(45deg);
}

.home__chips {
    display: flex;
    flex-direction: row;
    flex-wrap: wrap;
    margin-top: var(--sp-5);
}

.home__chip {
    margin-right: var(--sp-2);
    margin-bottom: var(--sp-2);
    padding: var(--sp-1) var(--sp-3);
    border-radius: var(--r-xs);
    background-color: var(--s-card-sub);
}

.home__chip-text {
    font-size: var(--fs-caption);
    line-height: $lh-caption;
    color: var(--t-2);
    letter-spacing: 0;
}

.home__rings {
    display: flex;
    flex-direction: row;
    flex-wrap: wrap;
    margin-top: var(--sp-6);
}

.home__ring-item {
    display: flex;
    flex-direction: column;
    align-items: center;
    width: 128rpx;
    margin-right: var(--sp-5);
    margin-bottom: var(--sp-3);
    transition: transform var(--d-fast) var(--ease-std), opacity var(--d-fast) var(--ease-std);
}

.home__ring-item--press {
    transform: scale(var(--press-scale));
    opacity: var(--press-opacity);
}

.home__ring-percent {
    font-size: var(--fs-micro);
    line-height: $lh-micro;
    font-weight: $fw-semibold;
    color: var(--t-1);
    letter-spacing: 0;
}

.home__ring-label {
    margin-top: var(--sp-2);
    font-size: var(--fs-caption);
    line-height: $lh-caption;
    color: var(--t-3);
    text-align: center;
    letter-spacing: 0;
}

.home__muted {
    display: block;
    margin-top: var(--sp-5);
    font-size: var(--fs-sub);
    line-height: $lh-sub;
    color: var(--t-3);
    letter-spacing: 0;
}

.home__slow {
    display: block;
    margin-top: var(--sp-4);
    font-size: var(--fs-caption);
    line-height: $lh-caption;
    color: var(--t-3);
    text-align: center;
    letter-spacing: 0;
}

.home__list {
    display: flex;
    flex-direction: column;
}

/* ── ⑥ 查看趋势入口 ── */
.home__entry {
    display: flex;
    flex-direction: row;
    align-items: center;
    justify-content: space-between;
    min-height: var(--row-h);
    padding-left: var(--card-pad);
    padding-right: var(--card-pad);
    border-radius: var(--r-md);
    background-color: var(--s-card);
    border: 1rpx solid var(--b-line);
    box-shadow: var(--el-0);
    transition: transform var(--d-fast) var(--ease-std), opacity var(--d-fast) var(--ease-std);
}

.home__entry--press {
    transform: scale(var(--press-scale));
    opacity: var(--press-opacity);
}

.home__entry-text {
    font-size: var(--fs-h3);
    line-height: $lh-h3;
    font-weight: $fw-medium;
    color: var(--t-1);
    letter-spacing: 0;
}
</style>
