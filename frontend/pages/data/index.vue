<template>
    <!--
      SC-20 数据管理页（pages/data/index）
      依据：S1-C §二 SC-20（① 顶部栏 / ② 数据总览 / ③ 功能入口 / ④ 页脚注）｜
            DESIGN.md §8.2（C-02 / C-14 / C-15 / C-16 / C-17 / C-20）/ §10.3 / §11 / §12 / §13

      顶栏：**A 类系统导航栏**（`DESIGN.md §10.3` 的 B 类自绘顶栏 custom 名单逐字为
            SC-01 / 02 / 03 / 04 / 05 / 06 / 11 / SC-18，**不含 SC-20**）——
            标题「数据管理」由 `pages.json` 指定，本页**不得**加 `navigationStyle: "custom"`
            （本批唯一加 custom 的新页仍是 SC-18）。

      结构（与 S1-C SC-20 逐项对应）：
        [① 顶部栏]   系统导航栏「数据管理」（注册随子项 3.4 落地）
        [② 数据总览]  F-070 —— 逐指标一行（指标名 + 条数 + 最早 / 最晚记录时间）
                     ＋ 合计行「共 N 条记录 · 时间范围 <起> ~ <止>」
        [③ 功能入口]  数据导出 → SC-21 ／ 数据删除 → SC-22（**子项 3.4 接线后启用**，见下）
        [④ 页脚注]    D-3 备份策略标记 —— **不渲染任何界面元素**
                     （预检报告 §6.3 S-5：`S1-C-UIUX信息架构与页面清单 §6` 原文注明
                       「SC-20 备注（**文档层，非界面**）：D-3 备份策略待 S1-D 最终冻结；
                         V1.0 明确不启用」）

      数据来源：`D-01 GET /me/data/summary`（`api/data.js`）。

      ★ 合计行的「时间范围」由**前端聚合**（预检报告 §6.1 G-8）：
        `D-01` 只**逐指标**返回 `first_recorded_at` / `last_recorded_at`，**不返回总量级时间范围**
        ⇒ 本页从 `by_metric` 逐项取 min / max 得到。字段为**定宽** `YYYY-MM-DD HH:mm:ss`
        ⇒ **字符串比较即时间先后比较**（无需解析日期，也不做任何时区换算）。

      状态覆盖（DESIGN.md §13 底线清单，逐项说明）：
        正常   ✅ 各指标行 + 合计行；
        空     ✅ 逐字「还没有任何数据」+「去记录」→ SC-07（S1-C ⑩）；
                 导出 / 删除入口**保留**（S1-C ⑩ 要求"点击后提示暂无可处理的数据"——
                 该提示随子项 3.4 接线一并落地，见「如实登记」②）；
        加载   ✅ 总览**骨架屏**（S1-C ⑪；不整页白屏）；
        失败   ✅ G3 失败组件 + 重试（S1-C ⑫）；
        未登录 ✅ 路由守卫 → SC-03（S1-C ⑬）；
        离线   ✅ 缓存只读 + 离线标记**必须标注更新时间**（S1-C ⑭：条数可能陈旧）；
                 未命中缓存 → 离线空态（**不得**把"无本地缓存"显示成「还没有任何数据」）；
        401    → 由统一请求层处理（单次 Refresh → 重放；失败清栈回 SC-03）；
        提交防重 / 高风险确认 → **N/A**（本页只读、无写操作：S1-C ⑮「无（在子页面执行）」）。

      ★ 范围守卫（S1-C SC-20 范围守卫，逐字落实）：
        **不出现「数据导入」「备份 / 恢复」入口**（F-074 / F-075 属 P1 / V1.1）。

      ★ 如实登记（本轮不做 / 延后，逐条给出原因，**不伪造**）
        ① **接线状态（S3-8 子项 3.4 已落地）**：`pages.json` 注册（M1）与 `route.js` 常量（M2）
           已于子项 3.4 完成（`pages.json` 19 → 22 页）⇒ 本页**已可 URL 直达**；
           与之配套的 H5 端到端验证在 3.4 之后进行（与预检报告 §7「接线必须最后做，
           否则三页不可达」一致）。
        ② **两个功能入口（S3-8 子项 3.4 已接线）**：按原计划把 `entryItems.enabled` 改为
           **在线即可点**、模板补 `@tap="onEntry"`、方法内补两条 `navigateTo` 分支、
           「空态」拦截（⑩ 逐字「暂无可处理的数据」）与「离线置灰」（⑭）⇒
           与 S1-C SC-20 ③ / ⑩ / ⑭ 完全对齐；**本页原有结构零改动**
           （总览 / 卡片 / 离线条 / 请求时序 / 缓存口径均未触碰）。
        ③ 缓存键用**页内常量** `cache.data_summary`，未登记进 `utils/cache.js#CACHE_KEYS`：
           该文件属 S3-5 已封板资产、本批未获授权修改（预检报告 §6.1 G-6 / §6.3 S-1）⇒
           沿用 SC-16（`cache.profile`）**同一先例**，行为完全一致，仅登记位置不同。
        ④ 本页**不渲染**任何「设置」「意见反馈」「数据导入 / 备份恢复」入口（P1 类）。
    -->
    <view class="data-page">
        <view class="data-page__body">
            <view class="data-page__inner">
                <!-- 离线只读标记 / 网络恢复横幅（S1-C SC-20 ⑭） -->
                <view v-if="offlineBarText" class="data-page__block">
                    <AppOfflineBar variant="offline" :text="offlineBarText" />
                </view>
                <view v-if="restoredVisible" class="data-page__block">
                    <AppOfflineBar variant="restored" text="网络已恢复，正在刷新" />
                </view>

                <!-- ② 数据总览（F-070） -->
                <AppCard title="数据总览" class="data-page__block">
                    <view v-if="state === 'loading'">
                        <AppSkeleton variant="list" />
                    </view>

                    <AppErrorState
                        v-else-if="state === 'error'"
                        variant="inline"
                        :text="errorMsg"
                        retry-text="重试"
                        @retry="reload"
                    />

                    <AppEmpty
                        v-else-if="state === 'offline'"
                        variant="common"
                        text="当前离线，暂无本地缓存数据"
                    />

                    <AppEmpty
                        v-else-if="state === 'empty'"
                        variant="common"
                        text="还没有任何数据"
                        action-text="去记录"
                        @action="onGoRecord"
                    />

                    <template v-else>
                        <!--
                          逐指标一行：指标名（title）＋ 最早 / 最晚记录时间（subtitle）＋ 条数（value）。
                          ★ 为什么时间范围走 `subtitle` 而**不**走 `value`（勿回退）：
                            C-20 右侧 `tail` 区是 `flex-shrink: 0`（**不可收缩**）⇒ 把长文本交给
                            `value` 会在窄屏把左侧字段名压到 0 宽后**溢出绘制**、与值视觉重叠
                            （2026-09-17 SC-18 人工验收缺陷的根因，见预检报告 §6.1 与
                             `BASELINE §7.23`）。`subtitle` 位于 `.lrow__body`
                            （`flex: 1 + min-width: 0`，**天然可收缩**），
                            而 `value` 只承载短文本（「N 条」）⇒ 两侧宽度分配恒安全。
                        -->
                        <AppListRow
                            v-for="(row, i) in metricRows"
                            :key="row.metricType"
                            :icon="row.icon"
                            :title="row.title"
                            :subtitle="row.subtitle"
                            :value="row.countText"
                            :last="i === metricRows.length - 1"
                        />

                        <!-- 合计行（S1-C SC-20 ② 逐字：「共 N 条记录 · 时间范围 <起> ~ <止>」） -->
                        <text class="data-page__total">{{ totalText }}</text>
                    </template>
                </AppCard>

                <!--
                  ③ 功能入口（S1-C SC-20 ③）：数据导出 → SC-21、数据删除 → SC-22。
                  状态口径（勿回退）：**离线 ⇒ 置灰**（⑭：两者均为写操作，必须在线）；
                  **在线空态 ⇒ 入口保留**（⑩：点击后提示「暂无可处理的数据」），
                  由 `onEntry` 拦截跳转 —— 两种态都**不出现"点了没反应"**。
                -->
                <AppCard class="data-page__block">
                    <AppListRow
                        v-for="(item, i) in entryItems"
                        :key="item.key"
                        :title="item.label"
                        :arrow="item.enabled"
                        :disabled="!item.enabled"
                        :last="i === entryItems.length - 1"
                        @tap="onEntry(item)"
                    />
                </AppCard>
            </view>
        </view>

        <!-- 轻提示宿主（离线 / 会话失效提示由统一请求层经此渲染） -->
        <AppToast />

        <!-- 开发环境页面预览器（仅 H5 非生产环境渲染；生产构建下为空节点） -->
        <DevPagePreviewer />
    </view>
</template>

<script>
import AppCard from '../../components/AppCard.vue'
import AppListRow from '../../components/AppListRow.vue'
import AppEmpty from '../../components/AppEmpty.vue'
import AppSkeleton from '../../components/AppSkeleton.vue'
import AppErrorState from '../../components/AppErrorState.vue'
import AppOfflineBar from '../../components/AppOfflineBar.vue'
import AppToast from '../../components/AppToast.vue'
// 开发环境专用页面预览器（**仅 H5 + 非生产**生效；不注册进 `pages.json`、不计入 25 页）
import DevPagePreviewer from '../../components/DevPagePreviewer.vue'

import { ROUTES, navigateTo, requireLogin } from '../../utils/route'
import { fetchDataSummary } from '../../api/data'
import { loadCache, saveCache } from '../../utils/cache'
import { METRIC_TYPES, metricLabel, toDay } from '../../utils/metrics'
import { errorText } from '../../utils/request'
import { showToast } from '../../utils/toast'
import { NETWORK_BANNER_MS } from '../../utils/config'

/**
 * 数据总览的本地缓存键（离线只读来源）。
 *
 * ★ 为什么用**页内常量**而不是 `utils/cache.js#CACHE_KEYS`：
 *   `CACHE_KEYS` 属 S3-5 已封板资产（其头注要求「新增业务缓存时必须先在此登记」），
 *   而本批**未获授权**修改该文件（预检报告 §6.1 G-6 / §6.3 S-1）⇒
 *   沿用 SC-16（`cache.profile`）**同一先例**：页内声明同前缀常量 + 完整注释。
 *   行为与登记进 `CACHE_KEYS` **完全一致** —— `loadCache` / `saveCache` 按 key 字符串工作，
 *   且 `cache.` 前缀已在 `utils/storage.js` 的 `AUTH_SCOPED_PREFIXES` 中登记 ⇒
 *   「登出 / 注销 / 401 / 改密」四触发会随前缀扫描一并清除（无需额外登记）。
 *   待需求方授权一次性治理 G-6 + G-8 时，把它迁入 `CACHE_KEYS` 即可（本页只需改这一行）。
 */
const DATA_SUMMARY_CACHE_KEY = 'cache.data_summary'

/**
 * ③ 功能入口在**空态**下的点击提示（S1-C SC-20 ⑩ 逐字）。
 * ⑩ 要求「导出 / 删除入口**保留**但点击后提示『暂无可处理的数据』」⇒ 空态下入口**不置灰**，
 * 只在 `onEntry` 内**拦截跳转**（保留完整信息架构，见 DESIGN.md §12 不夸大不隐瞒）。
 */
const NO_DATA_OP_TEXT = '暂无可处理的数据'

/** 取字符串（空值 / 非字符串 → ''） */
function textOf(value) {
    if (value === null || value === undefined) {
        return ''
    }
    return String(value)
}

/**
 * 条数文案：「N 条」。
 * 非法 / 负数 → 返回空串（**不补 0**：把"未知"画成 0 属展示不实数据）。
 */
function countTextOf(count) {
    const n = Number(count)
    if (isNaN(n) || n < 0) {
        return ''
    }
    return String(n) + ' 条'
}

/**
 * 时间范围文案（`YYYY-MM-DD HH:mm:ss` → `YYYY-MM-DD`）。
 *
 * 口径：
 *   · 只做**同一冻结格式的截断**（`utils/metrics.js#toDay`），无时区换算、无相对时间推算；
 *   · 最早与最晚落在**同一天**时只显示一天（避免出现「2026-09-18 ~ 2026-09-18」这种无信息量的重复）；
 *   · 任一为空 → 只显示存在的一侧；两侧皆空 → 空串（调用方不渲染该行）。
 */
function rangeTextOf(first, last) {
    const a = toDay(first)
    const b = toDay(last)
    if (a && b) {
        return a === b ? a : a + ' ~ ' + b
    }
    return a || b
}

export default {
    components: {
        AppCard: AppCard,
        AppListRow: AppListRow,
        AppEmpty: AppEmpty,
        AppSkeleton: AppSkeleton,
        AppErrorState: AppErrorState,
        AppOfflineBar: AppOfflineBar,
        AppToast: AppToast,
        DevPagePreviewer: DevPagePreviewer
    },
    data: function () {
        return {
            /** 页面态：loading / normal / empty / offline / error */
            state: 'loading',
            /** `D-01` 的 `data` 原文（**不加工**，展示层各自派生） */
            summary: null,
            /** 失败文案（取自统一请求层，不自行编造） */
            errorMsg: '',

            /* ── 离线 / 网络 ── */
            offline: false,
            /** 当前展示来自本地缓存的写入时刻（用于「离线数据 · 更新于 <时间>」） */
            cacheSavedAt: '',
            restoredVisible: false,

            /** 本次 onShow 之前是否已加载过（避免与 onLoad 双发） */
            entered: false,
            /** 请求序号（并发保护：过期响应直接丢弃） */
            reqToken: 0,
            bannerTimer: null,
            networkHandler: null
        }
    },
    computed: {
        /** 离线条文案（离线且命中缓存 → 带更新时间；未命中 → 说明当前无本地缓存） */
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
         * 逐指标行（顺序 = 接口返回顺序 = 后端 `METRIC_TYPES` 固定顺序，**客户端不再排序**）。
         *
         * 字段：
         *   metricType —— 指标 type（用于 `:key` 与图标分派）；
         *   icon       —— 图标标识（**仅当是已知 8 类之一**才下发，否则不渲染图标位，
         *                 避免出现无样式的空图标盒）；
         *   title      —— 指标中文名（`utils/metrics.js` 冻结字典；未知类型原样回显，不编造）；
         *   subtitle   —— 该指标最早 ~ 最晚记录时间；无时间则不渲染该行副文案；
         *   countText  —— 「N 条」。
         */
        metricRows: function () {
            const list = this.summary && this.summary.by_metric ? this.summary.by_metric : []
            const rows = []
            for (let i = 0; i < list.length; i++) {
                const item = list[i]
                if (!item) {
                    continue
                }
                const type = textOf(item.metric_type)
                if (!type) {
                    continue
                }
                rows.push({
                    metricType: type,
                    icon: METRIC_TYPES.indexOf(type) >= 0 ? type : '',
                    title: metricLabel(type),
                    subtitle: rangeTextOf(item.first_recorded_at, item.last_recorded_at),
                    countText: countTextOf(item.count)
                })
            }
            return rows
        },
        /**
         * 总量级时间范围 —— 由 `by_metric` 逐项聚合 min / max（预检报告 §6.1 G-8）。
         *
         * ★ 可直接用字符串比较的原因：`YYYY-MM-DD HH:mm:ss` 为**定宽**格式 ⇒
         *   字典序 = 时间先后序（不解析日期、不做时区换算）。
         */
        totalRangeText: function () {
            const list = this.summary && this.summary.by_metric ? this.summary.by_metric : []
            let first = ''
            let last = ''
            for (let i = 0; i < list.length; i++) {
                const item = list[i]
                if (!item) {
                    continue
                }
                const f = textOf(item.first_recorded_at)
                const l = textOf(item.last_recorded_at)
                if (f && (!first || f < first)) {
                    first = f
                }
                if (l && (!last || l > last)) {
                    last = l
                }
            }
            return rangeTextOf(first, last)
        },
        /**
         * 合计行文案（S1-C SC-20 ② 逐字形态：「共 N 条记录 · 时间范围 <起> ~ <止>」）。
         * 条数取服务端 `total_records`（**不自行累加 `by_metric`**，避免与后端口径分叉）；
         * 时间范围缺失时退化为「共 N 条记录」（**不补假区间**）。
         */
        totalText: function () {
            const n = Number(this.summary && this.summary.total_records)
            if (isNaN(n) || n <= 0) {
                return ''
            }
            const range = this.totalRangeText
            if (!range) {
                return '共 ' + n + ' 条记录'
            }
            return '共 ' + n + ' 条记录 · 时间范围 ' + range
        },
        /**
         * ③ 功能入口（顺序与 S1-C SC-20 ③ 一致：数据导出 → SC-21、数据删除 → SC-22）。
         *
         * ★ `enabled` 口径（S1-C SC-20 ⑭ / ⑩，S3-8 子项 3.4 接线）：
         *   · **离线 ⇒ 置灰**（⑭：导出 / 删除均为写操作，必须在线）；置灰走 C-20 既有机制
         *     （`tapEnabled = !disabled && arrow` ⇒ `arrow = false` 时组件**不派发 `tap`**）
         *     ⇒ 不产生死链接、不出现"点了没反应"。
         *   · **在线但空态 ⇒ 入口保留**（⑩ 要求入口保留、点击后提示）⇒ 此处 `enabled` 仍为
         *     `true`，空态拦截在 `onEntry` 内完成（**不放宽为"置灰"，那会变成⑩ 不允许的隐藏**）。
         */
        entryItems: function () {
            const enabled = !this.offline
            return [
                { key: 'export', label: '数据导出', enabled: enabled },
                { key: 'delete', label: '数据删除', enabled: enabled }
            ]
        }
    },
    onLoad: function () {
        // 未登录守卫（S1-C SC-20 ⑬：需登录）
        if (!requireLogin()) {
            return
        }

        // 首次加载：优先本地缓存即时渲染（离线只读的基础），再向服务端刷新
        this.load(false)

        // 网络恢复 → 自动刷新本页（只读页，**不自动重放**任何写操作）
        const self = this
        this.networkHandler = function (res) {
            self.handleNetworkChange(res)
        }
        uni.onNetworkStatusChange(this.networkHandler)
    },
    onShow: function () {
        // 从子页面（SC-21 / SC-22）返回时自动刷新总览（S1-C SC-20 ⑯）；
        // 首次进入由 onLoad 负责，避免双发
        if (this.entered) {
            this.load(true)
        }
        this.entered = true
    },
    onUnload: function () {
        this.clearBanner()
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
         * 加载 `D-01`。
         * @param {boolean} silent 静默刷新（返回本页 / 网络恢复）：不显示骨架，避免打断阅读
         */
        load: function (silent) {
            const self = this
            this.reqToken += 1
            const token = this.reqToken
            this.errorMsg = ''

            // 先读本地缓存：命中 → 立即只读渲染（离线可看），再向服务端刷新
            if (!silent) {
                const cached = loadCache(DATA_SUMMARY_CACHE_KEY)
                if (cached && cached.data) {
                    this.commit(cached.data, cached.savedAt, true)
                } else if (!this.summary) {
                    this.state = 'loading'
                }
            }

            return fetchDataSummary().then(function (res) {
                // 过期响应（页面已重新加载）→ 丢弃，由最新一次请求收尾
                if (token !== self.reqToken) {
                    return
                }
                const data = res && res.data ? res.data : null
                self.offline = false
                const savedAt = self.saveAndStamp(data)
                self.commit(data, savedAt, false)
            }, function (err) {
                if (token !== self.reqToken) {
                    return
                }
                if (err && err.isNetwork) {
                    // ★ 401 / 会话失效**不会**走到这里（统一请求层已处理并清栈回 SC-03），
                    //   因此 isNetwork 就是真离线 —— 不能把 401 当成空态
                    //   （否则会谎报「还没有任何数据」）。
                    self.offline = true
                    if (self.summary) {
                        // 命中缓存 → 保持只读展示（离线条已说明数据来源与时间）
                        return
                    }
                    self.state = 'offline'
                    return
                }
                self.errorMsg = errorText(err)
                self.state = 'error'
            })
        },

        /** 手动重试（失败组件的重试入口）：按"首次加载"处理，避免继续停留在失败态 */
        reload: function () {
            this.offline = false
            this.load(false)
        },

        /**
         * 落地一次渲染（**原子替换**）。
         * @param {object} data `D-01` 的 `data`
         * @param {string} savedAt 缓存写入时刻（空串 = 非缓存来源）
         * @param {boolean} fromCache 本次是否来自本地缓存
         */
        commit: function (data, savedAt, fromCache) {
            this.summary = data || null
            const n = Number(data && data.total_records)
            // 判定依据 = 服务端 `total_records`（> 0 才算有数据；`by_metric = []` 与 0 同义）
            this.state = !isNaN(n) && n > 0 ? 'normal' : 'empty'
            this.cacheSavedAt = fromCache ? (savedAt || '') : ''
        },

        /** 写缓存并回读写入时刻（`saveCache` 不返回时间戳；回读一次最准确，开销可忽略） */
        saveAndStamp: function (data) {
            if (!data || !saveCache(DATA_SUMMARY_CACHE_KEY, data)) {
                return ''
            }
            const back = loadCache(DATA_SUMMARY_CACHE_KEY)
            return back ? back.savedAt : ''
        },

        /* ───────────── 出口 ───────────── */

        /**
         * 空状态的「去记录」→ SC-07 记录中心（S1-C SC-20 ⑩ 逐字）。
         * 本页只读，离线时也允许前往（SC-07 自身承担离线只读口径）。
         */
        onGoRecord: function () {
            navigateTo(ROUTES.RECORD)
        },

        /**
         * ③ 功能入口跳转（S1-C SC-20 ③ / ⑩ / ⑭）。
         *
         * 拦截顺序（先判态、再判目标）：
         *   1. 置灰项本就不会走到这里（C-20 的 `tapEnabled` 机制），仍保留一道防御性 return；
         *   2. **空态 ⇒ 只提示、不跳转**（⑩ 逐字「暂无可处理的数据」）—— 保留入口可见性，
         *      同时避免进入"无数据可处理"的子页面；
         *   3. 正常 → 按 `key` 进入 SC-21 / SC-22（路径取 `ROUTES` 常量，**不硬编码字符串**）。
         * 离线拦截已由 `entryItems` 置灰完成（⑭），此处**不重复判 `offline`**（单一判据来源）。
         */
        onEntry: function (item) {
            if (!item || !item.enabled) {
                return
            }
            if (this.state === 'empty') {
                showToast('info', NO_DATA_OP_TEXT)
                return
            }
            if (item.key === 'export') {
                navigateTo(ROUTES.DATA_EXPORT)
                return
            }
            if (item.key === 'delete') {
                navigateTo(ROUTES.DATA_DELETE)
            }
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
.data-page {
    min-height: 100vh;
    background-color: var(--s-page);
}

/* A 类系统导航栏的占位由平台负责，此处只留内容区节奏 */
.data-page__body {
    padding-top: var(--page-pad-t);
    padding-bottom: var(--page-pad-b);
}

/* 内容最大宽居中（DESIGN.md §10.4③）+ 唯一水平边距来源 --gutter */
.data-page__inner {
    max-width: var(--content-max);
    margin-left: auto;
    margin-right: auto;
    padding-left: var(--gutter);
    padding-right: var(--gutter);
}

/* 区块节奏：卡片之间统一走 --card-gap（同一屏内多条信息，比 --section-gap 更紧凑） */
.data-page__block {
    margin-bottom: var(--card-gap);
}

/* 合计行：位于逐指标行之后，用 1rpx 分隔线与上方的行分隔开（行最后一条已无下边框）。
   文案只陈述条数与时间范围，**不含任何评价词**（DESIGN.md §12）。 */
.data-page__total {
    display: block;
    margin-top: var(--sp-5);
    padding-top: var(--sp-5);
    border-top: 1rpx solid var(--b-line);
    font-size: var(--fs-caption);
    line-height: $lh-caption;
    color: var(--t-2);
    letter-spacing: 0;
}
</style>
