<template>
    <!--
      SC-11 趋势页（pages/trend/index）  tabBar ③
      依据：S1-C §二 SC-11（① 顶部栏 / ② 指标切换 / ③ 时间窗口 / ④ 图表区 / ⑤ 统计摘要卡 /
            ⑥ 查看明细）｜ DESIGN.md §9（图表规范）/ §10.2（图表尺寸）/ §10.3（B 类自绘顶栏）/
            §11（页面清单）/ §12（文案）/ §13（状态底线）

      数据来源：**S-02** `GET /api/v1/stats/trend` + **S-03** `GET /api/v1/stats/summary`
              （两者窗口规则一致，必须传同一个 `window`）；图表**本地渲染**（S1-C ⑰）。

      ★ 指标 / 窗口切换一律**原地刷新**（S1-C ⑨：不跳页）。
      ★ 「查看明细」→ SC-10，带**当前指标**筛选（S1-C ⑥「带当前筛选」）；
        SC-10 的入参只有 `?type=`（其时间范围有自己的 7/30/90/自定义分段），故不传窗口。
      ★ 数据点**不建立** → SC-09 的跳转：S1-C ⑦ 的条件是"若该点对应单条记录"，
        而 S-02 的 `points[]` 是**日聚合**（体重取当日最后一次、血压/心率/血糖/心情取当日均值、
        睡眠/饮水/运动取当日累计），**不唯一对应单条记录** ⇒ 按该条件本页不建跳转，
        点选只显示气泡 + 指示线（DESIGN.md §9「点选时用气泡」）。

      ★ 快照式状态机（关键实现口径）：
        页面持有 `snap` = **已成功加载并正在展示**的一个原子快照（含它自己的指标 / 窗口 / 数据 / 状态）。
        用户切换指标或窗口时，`snap` **保持不变**直到新数据返回 —— 这正是 DESIGN.md §7④ /
        S1-C SC-11 ⑪ 要求的「切换时保留旧图 + 淡加载，避免闪白」；
        而图上画的仍然是"旧指标自己的映射"，不会把旧数据贴上"新指标"的标签（避免展示错误数据）。
        请求返回后 `snap` **整体替换**；失败时替换为失败态（**不清空指标切换器**，可换指标重试，S1-C ⑫）。
        并发保护：每次请求带自增 token，过期响应直接丢弃。

      状态覆盖（DESIGN.md §13）：
        正常 / 加载（骨架屏，> 8s 追加「仍在加载，请稍候」）/ 空（「该时间段还没有记录」）/
        记录数 < 2（「至少需要 2 条记录才能画出趋势」）/ 失败（失败组件 + 重试）/
        未登录（守卫 → SC-03）/ 离线（缓存只读 + 「离线数据 · 更新于 <时间>」；未命中 → 该区域离线空态）/
        401（由统一请求层处理：单次 Refresh → 重放；失败清栈回 SC-03 并清 9 项缓存）。
        提交防重 → **N/A**（本页只读，无写操作）；高风险确认 → **N/A**（S1-C ⑮ 无）。

      ★ 如实登记：图表库为 DESIGN.md §9 冻结的 uCharts 组件（`qiun-data-charts`，S3-4 批次安装）。
    -->
    <view class="trend">
        <AppNavBar title="趋势" />

        <view class="trend__body">
            <!-- ① 顶部栏下的状态条区（离线只读标记 / 网络恢复横幅） -->
            <view class="trend__inner">
                <view v-if="offlineBarText" class="trend__notice">
                    <AppOfflineBar variant="offline" :text="offlineBarText" />
                </view>
                <view v-if="restoredVisible" class="trend__notice">
                    <AppOfflineBar variant="restored" text="网络已恢复，正在刷新" />
                </view>

                <!-- ② 指标切换：横向滚动标签，8 类（顺序 = 后端 METRIC_TYPES） -->
                <view class="trend__block">
                    <AppChipTabs
                        :model-value="metricType"
                        :options="metricOptions"
                        @change="onMetricChange"
                    />
                </view>

                <!-- ③ 时间窗口：分段控件 7 / 30 / 90 -->
                <view class="trend__block">
                    <AppSegmented
                        :model-value="windowDays"
                        :options="windowOptions"
                        @change="onWindowChange"
                    />
                </view>

                <!-- ④ 图表区的小标题 -->
                <text class="trend__section">趋势图</text>
            </view>

            <!--
              ④ 图表区
              ★ 本区块**刻意放在带 gutter 的 `.trend__inner` 之外**：
                DESIGN.md §9 / §10.2 规定「宽 = var(--chart-w)」，而
                `--chart-w = calc(100% - 2 * var(--gutter))` 的 100% 指**页面内容宽**。
                若嵌在已含 gutter 内边距的容器里会二次扣减、比其它卡片窄两档 gutter。
                故此处用同宽的居中容器承载，图表自身再用 `var(--chart-w)` 居中 —— 左右边缘与上方卡片严格对齐。
            -->
            <view class="trend__chartwrap">
                <TrendChartContainer
                    :metric-type="snap.metric"
                    :state="snap.trendState"
                    :chart-payload="snap.trend"
                    :switching="switching"
                    :slow-loading="slowLoading"
                    :error-text="trendErrorText"
                    @retry="reload"
                />
            </view>

            <view class="trend__inner">
                <!-- ⑤ 统计摘要卡（F-035） -->
                <StatsSummaryCard
                    class="trend__summary"
                    :metric-type="snap.metric"
                    :unit-from-api="snap.unit"
                    :summary="snap.summary"
                    :state="snap.summaryState"
                    :error-text="summaryErrorText"
                    @retry="reload"
                />

                <!-- ⑥ 查看明细 → SC-10（带当前指标） -->
                <view
                    class="trend__entry"
                    hover-class="trend__entry--press"
                    :hover-start-time="0"
                    :hover-stay-time="80"
                    @tap="onDetailEntry"
                >
                    <text class="trend__entry-text">查看明细</text>
                    <view class="trend__chevron"></view>
                </view>
            </view>
        </view>

        <!-- ⑦ 底部 tabBar（当前项 = 趋势，组件内部不会对当前项派发事件） -->
        <AppTabBar :items="tabItems" current="trend" @select="onTabSelect" />

        <!-- 轻提示宿主（会话失效提示由统一请求层经此渲染） -->
        <AppToast />

        <!-- 开发环境页面预览器（仅 H5 非生产环境渲染；生产构建下为空节点） -->
        <DevPagePreviewer />
    </view>
</template>

<script>
import AppNavBar from '../../components/AppNavBar.vue'
import AppChipTabs from '../../components/AppChipTabs.vue'
import AppSegmented from '../../components/AppSegmented.vue'
import AppOfflineBar from '../../components/AppOfflineBar.vue'
import AppTabBar from '../../components/AppTabBar.vue'
import AppToast from '../../components/AppToast.vue'
import TrendChartContainer from '../../components/TrendChartContainer.vue'
import StatsSummaryCard from '../../components/StatsSummaryCard.vue'
// 开发环境专用页面预览器（**仅 H5 + 非生产**生效；不注册进 `pages.json`、不计入 25 页）
import DevPagePreviewer from '../../components/DevPagePreviewer.vue'

import { ROUTES, navigateTo, reLaunch, requireLogin } from '../../utils/route'
import { METRIC_TYPES, metricLabel } from '../../utils/metrics'
import { fetchTrend, fetchSummary, DEFAULT_TREND_WINDOW, normalizeWindow } from '../../api/stats'
import { loadCache, saveCache, trendKey, trimTrendPayload } from '../../utils/cache'
import { errorText } from '../../utils/request'
import { NETWORK_BANNER_MS, SLOW_LOADING_MS } from '../../utils/config'

/** 默认指标（SC-11 无必填入参；与后端 `METRIC_TYPES` 首项一致） */
const DEFAULT_METRIC = METRIC_TYPES[0]

/** 时间窗口选项（S1-C SC-11 ③「7 天 / 30 天 / 90 天」；顺序即展示顺序） */
const WINDOW_OPTIONS = [
    { value: 7, label: '7 天' },
    { value: 30, label: '30 天' },
    { value: 90, label: '90 天' }
]

/**
 * 由 S-02 载荷判定图表区状态（口径全部来自服务端字段，客户端不自行推断）：
 *   - `points` 为空 → `empty`（该时间段还没有记录）；
 *   - `insufficient_data === true`（服务端判定 `points < 2`）→ `insufficient`；
 *   - 否则 → `normal`。
 */
function trendStateOf(payload) {
    const points = (payload && payload.points) || []
    if (!points.length) {
        return 'empty'
    }
    return payload.insufficient_data === true ? 'insufficient' : 'normal'
}

/** 8 类指标的 chip 选项（顺序 = 后端 `METRIC_TYPES`，确定性渲染） */
function buildMetricOptions() {
    return METRIC_TYPES.map(function (type) {
        return { value: type, label: metricLabel(type) }
    })
}

export default {
    components: {
        AppNavBar: AppNavBar,
        AppChipTabs: AppChipTabs,
        AppSegmented: AppSegmented,
        AppOfflineBar: AppOfflineBar,
        AppTabBar: AppTabBar,
        AppToast: AppToast,
        TrendChartContainer: TrendChartContainer,
        StatsSummaryCard: StatsSummaryCard,
        DevPagePreviewer: DevPagePreviewer
    },
    data: function () {
        return {
            /* ── 当前选择（用户点击后立即生效，用于高亮 chip / 分段） ── */
            metricType: DEFAULT_METRIC,
            windowDays: DEFAULT_TREND_WINDOW,

            /**
             * 已加载快照（**原子替换**）。切换中保持不变 ⇒ 旧图不闪白。
             * `key = <metric>@<window>`；`metric` 是"图上画的那份数据自己的指标"，
             * 因此不会出现"旧数据 + 新指标标签"的错配。
             */
            snap: {
                key: '',
                metric: DEFAULT_METRIC,
                window: DEFAULT_TREND_WINDOW,
                trend: null,
                trendState: 'loading',
                summary: null,
                summaryState: 'loading',
                unit: '',
                savedAt: ''
            },

            /** 切换中（目标键还没有快照，当前仍在展示旧快照）→ 淡加载指示 */
            switching: false,
            /** > 8s 追加「仍在加载，请稍候」（DESIGN.md §7④） */
            slowLoading: false,
            /** 失败文案（图表区 / 摘要区各自独立） */
            trendErrorText: '',
            summaryErrorText: '',

            /* ── 离线 / 网络 ── */
            offline: false,
            /** 当前展示的快照来自本地缓存的写入时刻（用于「离线数据 · 更新于 <时间>」） */
            cacheSavedAt: '',
            restoredVisible: false,

            /** 本次 onShow 之前是否已加载过（避免与 onLoad 双发） */
            entered: false,
            /** 请求序号（并发保护：过期响应直接丢弃） */
            reqToken: 0,
            /** 内部定时器句柄 */
            slowTimer: null,
            bannerTimer: null,
            /** 网络监听回调句柄 */
            networkHandler: null,

            metricOptions: buildMetricOptions(),
            windowOptions: WINDOW_OPTIONS,
            tabItems: [
                { key: 'home', label: '首页', enabled: true },
                { key: 'record', label: '记录中心', enabled: true },
                { key: 'trend', label: '趋势', enabled: true },
                { key: 'mine', label: '我的', enabled: true }
            ]
        }
    },
    computed: {
        /** 当前选择对应的快照键 */
        currentKey: function () {
            return this.metricType + '@' + this.windowDays
        },
        /** 离线条文案（离线且命中缓存 → 带更新时间；未命中 → 说明当前无本地缓存） */
        offlineBarText: function () {
            if (!this.offline) {
                return ''
            }
            if (this.cacheSavedAt) {
                return '离线数据 · 更新于 ' + this.cacheSavedAt
            }
            return '当前离线，暂无本地缓存数据'
        }
    },
    onLoad: function (options) {
        // 未登录守卫（S1-C SC-11 ⑬：需登录）
        if (!requireLogin()) {
            return
        }

        // 可选入参 `?type=`（8 类之一）；非法 / 缺失 → 默认指标（不因参数错误而白屏）
        const wanted = options && options.type ? String(options.type) : ''
        if (METRIC_TYPES.indexOf(wanted) >= 0) {
            this.metricType = wanted
        }

        // 首次加载：优先本地缓存即时渲染（离线只读的基础），再向服务端刷新
        this.load(false)

        // 网络恢复 → 自动刷新本页（只刷当前页、**不自动重放**任何写操作）
        const self = this
        this.networkHandler = function (res) {
            self.handleNetworkChange(res)
        }
        uni.onNetworkStatusChange(this.networkHandler)
    },
    onShow: function () {
        // 返回本页自动刷新（DESIGN.md §7④）；首次进入由 onLoad 负责，避免双发
        if (this.entered) {
            this.load(true)
        }
        this.entered = true
    },
    onUnload: function () {
        this.clearTimers()
        if (this.networkHandler) {
            uni.offNetworkStatusChange(this.networkHandler)
            this.networkHandler = null
        }
    },
    onHide: function () {
        // 空实现：本页无后台任务、无计时型业务
    },
    methods: {
        /* ───────────── 数据加载 ───────────── */

        /**
         * 加载当前选择对应的 S-02 + S-03。
         * @param {boolean} silent 静默刷新（返回本页 / 网络恢复时）：不显示骨架，避免打断阅读
         */
        load: function (silent) {
            const self = this
            const metric = this.metricType
            const days = this.windowDays
            const key = metric + '@' + days
            const tkey = trendKey(metric, days)

            this.reqToken += 1
            const token = this.reqToken
            this.trendErrorText = ''
            this.summaryErrorText = ''

            // 目标键尚无数据、且当前正展示另一份快照 → 切"保留旧图 + 淡加载"
            this.switching = this.snap.key !== '' && this.snap.key !== key
            this.startSlowTimer()

            // 先读本地缓存：命中 → 立即原地切换（离线只读 / 切换免闪白），再向服务端刷新
            if (!silent) {
                const cached = loadCache(tkey)
                if (cached && cached.data) {
                    const blob = cached.data
                    this.commit(key, metric, days, blob.trend || null, trendStateOf(blob.trend || null),
                        blob.summary || null, 'normal', cached.savedAt, true)
                } else if (this.snap.key !== key) {
                    // 无缓存且不是同一个键 → 骨架屏（首屏 / 首次切到该键）
                    this.commit(key, metric, days, null, 'loading', null, 'loading', '', false)
                }
            }

            // 两个接口各自独立成败：**局部失败只失败局部**（图表区 / 摘要区互不拖累）
            const result = {
                trend: null,
                trendState: 'loading',
                summary: null,
                summaryState: 'loading'
            }
            let wasOffline = false

            const trendTask = fetchTrend(metric, days).then(function (res) {
                const data = res && res.data ? res.data : {}
                result.trend = data
                result.trendState = trendStateOf(data)
            }, function (err) {
                if (err && err.isNetwork) {
                    wasOffline = true
                    result.trend = null
                    result.trendState = 'empty'
                    return
                }
                result.trendState = 'error'
                self.trendErrorText = errorText(err)
            })

            const summaryTask = fetchSummary(metric, days).then(function (res) {
                const data = res && res.data ? res.data : {}
                result.summary = data
                result.summaryState = 'normal'
            }, function (err) {
                if (err && err.isNetwork) {
                    wasOffline = true
                    result.summary = null
                    // 数值全部回落为「—」中性占位（不伪造 0，也不做任何评价）
                    result.summaryState = 'normal'
                    return
                }
                result.summaryState = 'error'
                self.summaryErrorText = errorText(err)
            })

            return Promise.all([trendTask, summaryTask]).then(function () {
                // 过期响应（用户已再次切换）→ 丢弃，由最新一次请求负责收尾
                if (token !== self.reqToken) {
                    return
                }
                self.clearSlowTimer()

                // 离线：未命中缓存的区域显示离线空态；命中缓存的保持只读展示
                if (wasOffline) {
                    self.offline = true
                    if (self.snap.key === key && self.snap.trend) {
                        self.switching = false
                        return
                    }
                    self.commit(key, metric, days, null, 'empty', null, 'normal', '', false)
                    return
                }

                self.offline = false

                // 写入本地缓存（TTL 24h，按「指标 + 窗口」切分；离线只读的数据来源）
                const blob = {
                    trend: trimTrendPayload(result.trend),
                    summary: result.summary
                }
                const savedAt = self.saveAndStamp(tkey, blob)
                self.commit(key, metric, days, result.trend, result.trendState,
                    result.summary, result.summaryState, savedAt, false)
            })
        },

        /** 手动重试（失败组件的重试入口）：按"首次加载"处理，避免继续停留在失败态 */
        reload: function () {
            this.offline = false
            this.load(false)
        },

        /**
         * 原子替换快照。
         * @param {string} key 快照键 `<metric>@<window>`
         * @param {string} metric 该快照自己的指标（图表系列名 / 取值字段 / 摘要口径都以它为准）
         * @param {number} days 该快照自己的窗口
         * @param {object|null} trend S-02 的 `data`（整体交给 C-23，它自己按 `points`/`window`/`chart` 取值）
         * @param {string} trendState 图表区状态
         * @param {object|null} summaryPayload S-03 的 `data`（**外层**：含 `unit` 与内层 `summary`）
         * @param {string} summaryState 摘要区状态
         * @param {string} savedAt 缓存写入时刻（空串 = 非缓存来源）
         * @param {boolean} fromCache 本次快照是否来自本地缓存
         */
        commit: function (key, metric, days, trend, trendState, summaryPayload, summaryState, savedAt, fromCache) {
            /*
             * ★ 层次口径（易错点，已由 H5 集成冒烟实证）：
             *   S-03 响应为 `data = { metric_type, unit, window, summary: {...} }`；
             *   C-24 的契约（DESIGN.md §8.3 / 组件 props 注释）**只吃内层 `data.summary`**，
             *   而 `unit` 在外层。故此处必须**分别取用**：
             *     单位 → `summaryPayload.unit`；数值 → `summaryPayload.summary`。
             *   若把外层整体传下去，C-24 读不到 `average / max / min ...` ⇒ 六行全显示 `—`
             *   （表现为"摘要卡一片空白"，图表却正常）。
             */
            const unitFromSummary = summaryPayload && summaryPayload.unit ? summaryPayload.unit : ''
            const unitFromTrend = trend && trend.unit ? trend.unit : ''
            this.snap = {
                key: key,
                metric: metric,
                window: days,
                trend: trend,
                trendState: trendState,
                summary: summaryPayload && summaryPayload.summary ? summaryPayload.summary : null,
                summaryState: summaryState,
                unit: unitFromSummary || unitFromTrend,
                savedAt: savedAt || ''
            }
            this.cacheSavedAt = fromCache ? (savedAt || '') : ''
            this.switching = false
        },

        /** 写缓存并回读写入时刻（`saveCache` 不返回时间戳；回读一次最准确，且开销可忽略） */
        saveAndStamp: function (tkey, blob) {
            if (!saveCache(tkey, blob)) {
                return ''
            }
            const back = loadCache(tkey)
            return back ? back.savedAt : ''
        },

        /* ───────────── 切换（原地刷新，不跳页） ───────────── */

        /** 指标切换：只接受 8 类之一；与当前一致则不发请求 */
        onMetricChange: function (value) {
            const type = String(value)
            if (METRIC_TYPES.indexOf(type) < 0 || type === this.metricType) {
                return
            }
            this.metricType = type
            this.load(false)
        },

        /** 窗口切换：归一化到 7 / 30 / 90；与当前一致则不发请求（C-08 重复点会派发 change） */
        onWindowChange: function (value) {
            const days = normalizeWindow(value)
            if (days === this.windowDays) {
                return
            }
            this.windowDays = days
            this.load(false)
        },

        /* ───────────── 网络状态 ───────────── */

        handleNetworkChange: function (res) {
            const online = !!(res && res.isConnected)
            if (!online) {
                this.offline = true
                return
            }
            this.offline = false
            this.showRestoredBanner()
            this.load(true)
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
            this.slowLoading = false
        },

        clearTimers: function () {
            this.clearSlowTimer()
            if (this.bannerTimer) {
                clearTimeout(this.bannerTimer)
                this.bannerTimer = null
            }
        },

        /* ───────────── 出口 ───────────── */

        /** 「查看明细」→ SC-10，带当前指标筛选（S1-C SC-11 ⑥） */
        onDetailEntry: function () {
            navigateTo(ROUTES.RECORD_HISTORY + '?type=' + this.metricType)
        },

        /**
         * tabBar 切换：首页 / 记录中心 / 我的 为已实现项；「趋势」即当前页
         * （C-11 内部不会对当前项派发事件，故无 trend 分支）。
         * 「我的」（SC-18，S3-7 落地，tabBar ④）自本批起 `enabled: true` —— 四项之间
         * 互相切换**一律用清栈 `reLaunch`**（tabBar 是平级切换，不允许层层压栈返回）。
         * 依据：S1-C SC-11 ⑦与 `DESIGN.md §11` tabBar（4 项）。
         */
        onTabSelect: function (item) {
            if (!item || !item.key) {
                return
            }
            if (item.key === 'home') {
                reLaunch(ROUTES.HOME)
                return
            }
            if (item.key === 'record') {
                reLaunch(ROUTES.RECORD)
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
.trend {
    min-height: 100vh;
    background-color: var(--s-page);
}

.trend__body {
    padding-top: var(--nav-total-h);
    /* 底部固定区 = tabBar 总高 + 区块间距 */
    padding-bottom: calc(var(--tabbar-total-h) + var(--section-gap));
}

/* 内容最大宽居中（DESIGN.md §10.4③）+ 唯一水平边距来源 --gutter */
.trend__inner {
    max-width: var(--content-max);
    margin-left: auto;
    margin-right: auto;
    padding-left: var(--gutter);
    padding-right: var(--gutter);
}

/* 图表区块：与 .trend__inner 同宽同居中，但**不含水平内边距**（原因见模板注释） */
.trend__chartwrap {
    max-width: var(--content-max);
    margin-left: auto;
    margin-right: auto;
}

.trend__notice {
    margin-top: var(--sp-5);
}

.trend__block {
    margin-top: var(--section-gap);
}

.trend__section {
    display: block;
    margin-top: var(--section-gap);
    margin-bottom: var(--sp-5);
    font-size: var(--fs-h2);
    line-height: $lh-h2;
    font-weight: $fw-semibold;
    color: var(--t-1);
    letter-spacing: 0;
}

.trend__summary {
    display: block;
    margin-top: var(--section-gap);
}

/* ── ⑥ 查看明细入口（与 SC-06「查看趋势」入口同一视觉语言） ── */
.trend__entry {
    display: flex;
    flex-direction: row;
    align-items: center;
    justify-content: space-between;
    min-height: var(--row-h);
    margin-top: var(--section-gap);
    padding-left: var(--card-pad);
    padding-right: var(--card-pad);
    border-radius: var(--r-md);
    background-color: var(--s-card);
    border: 1rpx solid var(--b-line);
    box-shadow: var(--el-0);
    transition: transform var(--d-fast) var(--ease-std), opacity var(--d-fast) var(--ease-std);
}

.trend__entry--press {
    transform: scale(var(--press-scale));
    opacity: var(--press-opacity);
}

.trend__entry-text {
    font-size: var(--fs-h3);
    line-height: $lh-h3;
    font-weight: $fw-medium;
    color: var(--t-1);
    letter-spacing: 0;
}

/* 右向箭头：纯 CSS 几何（旋转 45° 的两段边框），不用图标库；图标边长用 px 属 §10.4② 例外 */
.trend__chevron {
    width: 9px;
    height: 9px;
    margin-left: var(--sp-3);
    border-top: 2px solid var(--t-3);
    border-right: 2px solid var(--t-3);
    transform: rotate(45deg);
}
</style>
