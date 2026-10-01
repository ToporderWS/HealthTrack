<template>
    <!--
      SC-07 记录中心（pages/record/index）  tabBar ②
      依据：S1-C §二 SC-07 ｜ DESIGN.md §8.3 C-21 / §11 / §12 / §13
      顶栏：**A 类系统导航栏**（DESIGN.md §10.3：B 类自绘顶栏仅 SC-01~06/11/18，**不含 SC-07**），
            标题由 `pages.json` 的 `navigationBarTitleText` 提供 ⇒ 本页不使用 C-10 AppNavBar。

      结构（与 S1-C 逐项对应）：
        [① 顶部栏]  系统导航栏「记录中心」+ 页内说明句「选择要记录的指标」
        [② 指标网格] 2 列 × 4 行 = 8 张卡片（体重 / 血压 / 心率 / 血糖 / 睡眠 / 饮水 / 运动 / 心情）
        [⑦ 底部]    tabBar（C-11，4 项不得增删）

      ★ 数据来源与"零请求"登记（S1-C SC-07 ⑰）：
        「仅复用 `S-01` 已有数据，**不新增接口调用**」⇒ 本页**不发任何网络请求**；
        每卡「最近值」读 SC-06 已写入的本地缓存 `kj:cache.home_overview`（S-01 结果，TTL 24h）。
        取不到（无缓存 / 该指标无记录 / 值缺失）→ **静默显示「—」**（C-21），不弹错、不阻塞录入。
        ★ 口径限制：`recent_records[]` **只含 `value_1`**（无 `value_2`）⇒ 血压卡只呈现收缩压，
          与已封板 SC-06「最近记录」卡同口径；成对的「120/80」属 SC-09/SC-10（S3-3），本页不编造。

      状态覆盖（DESIGN.md §13 底线清单，逐项映射）：
        正常 ✅ 8 卡恒常显示（S1-C ⑨）｜空态 **N/A**（S1-C ⑩：卡片为固定功能入口，无空状态）
        加载 **N/A**（S1-C ⑪：页面本身无强制请求，卡片框架立即可用）
        失败 **N/A**（S1-C ⑫：无请求 ⇒ 无失败态；最近值取不到即「—」）
        未登录 ✅ 守卫 → SC-03（S1-C ⑬）｜离线 ✅ 卡片入口**完全可用**（入口不依赖网络）+ 离线条
        401 **N/A**（本页零请求，401 由统一请求层在其他页面处理）
        提交防重 **N/A**（本页无写操作，写操作在 SC-08）｜高风险确认 **N/A**（无危险操作）

      ★ 如实登记（S3-3 起已接通）：
        「历史」入口指向 SC-10（S3-3 已落地）⇒ 传 `history-enabled=true` 并接 `@history`，
        跳 `pages/record/history?type=<指标类型>`。
        C-21 组件本身**零改动** —— 它本就以 `history-enabled` 为开关；
        S3-2 期间传 `false` 只是"未实现页面不建立跳转"的临时处理（无死链、无假页面）。
    -->
    <view class="record">
        <view class="record__body">
            <view class="record__inner">
                <!-- 离线只读标记（最近值来自本地缓存 → 标注即可；入口仍完全可用） -->
                <view v-if="offlineBarText" class="record__notice">
                    <AppOfflineBar variant="offline" :text="offlineBarText" />
                </view>

                <!-- 网络恢复横幅（3s 后自行撤下，DESIGN.md §8.2 C-17） -->
                <view v-if="restoredVisible" class="record__notice">
                    <AppOfflineBar variant="restored" text="网络已恢复" />
                </view>

                <!-- ① 说明句 -->
                <text class="record__desc">选择要记录的指标</text>

                <!-- ② 8 类指标网格（2 列） -->
                <view class="record__grid">
                    <HealthMetricCard
                        v-for="item in metrics"
                        :key="item.type"
                        :metric-type="item.type"
                        :label="item.label"
                        :unit="item.unit"
                        :recent="item.recent"
                        :recent-time="item.recentTime"
                        :history-enabled="true"
                        @record="onAddRecord"
                        @history="onHistory"
                    />
                </view>
            </view>
        </view>

        <!-- ⑦ 底部 tabBar -->
        <AppTabBar :items="tabItems" current="record" @select="onTabSelect" />

        <!-- 轻提示宿主（会话失效提示由统一请求层经此渲染） -->
        <AppToast />
    </view>
</template>

<script>
import AppTabBar from '../../components/AppTabBar.vue'
import AppToast from '../../components/AppToast.vue'
import AppOfflineBar from '../../components/AppOfflineBar.vue'
import HealthMetricCard from '../../components/HealthMetricCard.vue'

import { ROUTES, navigateTo, reLaunch, requireLogin } from '../../utils/route'
import { METRIC_TYPES, metricLabel, metricUnit, toShortMinute } from '../../utils/metrics'
import { CACHE_KEYS, loadCache } from '../../utils/cache'
import { NETWORK_BANNER_MS } from '../../utils/config'

export default {
    components: {
        AppTabBar: AppTabBar,
        AppToast: AppToast,
        AppOfflineBar: AppOfflineBar,
        HealthMetricCard: HealthMetricCard
    },
    data: function () {
        return {
            /** 离线（网络不可用）；**卡片入口完全可用**，仅用于标注最近值来源 */
            offline: false,
            /** 缓存写入时刻（用于「离线数据 · 更新于 <时间>」） */
            cacheSavedAt: '',
            /** 是否命中本地缓存（决定离线条文案） */
            cacheHit: false,
            /** 网络恢复横幅是否可见（3s） */
            restoredVisible: false,
            /** S-01 缓存的 `recent_records[]`（仅用于每卡「最近值」） */
            recentRecords: [],
            /** 网络监听回调句柄 */
            networkHandler: null,
            bannerTimer: null,
            tabItems: [
                { key: 'home', label: '首页', enabled: true },
                { key: 'record', label: '记录中心', enabled: true },
                { key: 'trend', label: '趋势', enabled: true },
                { key: 'mine', label: '我的', enabled: true }
            ]
        }
    },
    computed: {
        /** 8 类指标卡片数据（顺序 = 后端 `METRIC_TYPES`，确定性渲染） */
        metrics: function () {
            const records = this.recentRecords
            return METRIC_TYPES.map(function (type) {
                let recent = ''
                let recentTime = ''
                for (let i = 0; i < records.length; i++) {
                    const item = records[i]
                    if (item && item.metric_type === type) {
                        recent = buildRecentValue(item, type)
                        recentTime = buildRecentTime(item)
                        break
                    }
                }
                return {
                    type: type,
                    label: metricLabel(type),
                    unit: metricUnit(type, ''),
                    recent: recent,
                    recentTime: recentTime
                }
            })
        },
        offlineBarText: function () {
            if (!this.offline) {
                return ''
            }
            if (this.cacheHit && this.cacheSavedAt) {
                return '离线数据 · 更新于 ' + this.cacheSavedAt
            }
            return '当前离线'
        }
    },
    onLoad: function () {
        // 未登录守卫（S1-C SC-07 ⑬：需登录）
        if (!requireLogin()) {
            return
        }

        this.readCache()

        // 网络状态（恢复 → 3s 横幅；本页无请求可刷，不自动重放任何写操作）
        const self = this
        this.networkHandler = function (res) {
            self.handleNetworkChange(res)
        }
        uni.onNetworkStatusChange(this.networkHandler)
    },
    onShow: function () {
        // 重新读缓存：从 SC-08 保存成功返回、或首页刚刷新过缓存时，「最近值」随之更新（零请求）
        this.readCache()
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
        /** 读本地缓存（S-01 结果）—— 本页唯一的"数据来源"，不发请求 */
        readCache: function () {
            const cached = loadCache(CACHE_KEYS.HOME_OVERVIEW)
            if (!cached || !cached.data) {
                this.cacheHit = false
                this.cacheSavedAt = ''
                this.recentRecords = []
                return
            }
            this.cacheHit = true
            this.cacheSavedAt = cached.savedAt
            const list = cached.data.recent_records
            this.recentRecords = list && list.length ? list : []
        },

        handleNetworkChange: function (res) {
            const online = !!(res && res.isConnected)
            if (!online) {
                this.offline = true
                return
            }
            this.offline = false
            this.showRestoredBanner()
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

        /* ───────────── 入口 ───────────── */

        /** 【记一笔】→ SC-08 通用录入页（带 `type=`） */
        onAddRecord: function (metricType) {
            if (!metricType) {
                return
            }
            navigateTo(ROUTES.RECORD_ADD + '?type=' + metricType)
        },

        /** 【历史】→ SC-10 记录历史列表（带 `type=`；S3-3 接通） */
        onHistory: function (metricType) {
            if (!metricType) {
                return
            }
            navigateTo(ROUTES.RECORD_HISTORY + '?type=' + metricType)
        },

        /**
         * tabBar 切换：本页即「记录中心」，C-11 **不对当前项派发事件**（故先拦 record）；
         * 「首页」（SC-06）、「趋势」（SC-11，S3-4 落地）、「我的」（SC-18，S3-7 落地，tabBar ④）
         * 均为启用项 —— 四项之间互相切换**一律用清栈 `reLaunch`**（tabBar 是平级切换，
         * 不允许层层压栈返回；与 S3-2/S3-4 既有口径一致）。
         * 依据：S1-C SC-07 ⑦「首页 / 记录中心 / 趋势 / 我的」与 `DESIGN.md §11` tabBar（4 项）。
         */
        onTabSelect: function (item) {
            if (!item || item.key === 'record') {
                return
            }
            if (item.key === 'home') {
                reLaunch(ROUTES.HOME)
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

/**
 * 「最近值」文案（**只有值与单位，不含时间**；时间走 `buildRecentTime` 第二行）。
 *
 * ★ 口径限制（如实登记，**不发明字段**）：
 *   S-01 冻结契约 `recent_records[]` 的字段为
 *   `id / metric_type / value_1 / unit / recorded_at / time_start / note / tags`
 *   —— **只回 `value_1`，没有 `value_2`**（后端 `stats_service.py` 第 371~383 行）。
 *   因此血压卡的最近值**只呈现收缩压**（`value_1`），与已封板的 SC-06「最近记录」卡
 *   完全同口径；完整的「120/80」成对展示属 **SC-09 详情 / SC-10 历史**（走 `R-02` / `R-03`，
 *   那两条接口的 `_view()` 才含 `value_2`）。
 *   本页**不得**为了凑「成对」而自行编造舒张压或另发请求（S1-C ⑰：仅复用 S-01 已有数据）。
 *
 * 值缺失（`value_1` 为 null / 空）→ 返回空串，由 C-21 统一显示「—」（**不显示 0**）。
 */
function buildRecentValue(record, type) {
    const value = record.value_1
    if (value === null || value === undefined || value === '') {
        return ''
    }
    const unit = metricUnit(type, record.unit)
    return unit ? String(value) + ' ' + unit : String(value)
}

/** 「最近值」时间（`MM-DD HH:mm`，同一冻结格式的截断；缺失 → 空串，整行不渲染） */
function buildRecentTime(record) {
    return toShortMinute(record.recorded_at)
}
</script>

<style scoped lang="scss">
.record {
    min-height: 100vh;
    background-color: var(--s-page);
}

.record__body {
    /* A 类系统导航栏占位由平台负责，此处只留内容区顶部节奏 */
    padding-top: var(--page-pad-t);
    /* 底部固定区 = tabBar 总高 + 区块间距 */
    padding-bottom: calc(var(--tabbar-total-h) + var(--section-gap));
}

/* 内容最大宽居中（DESIGN.md §10.4③） */
.record__inner {
    max-width: var(--content-max);
    margin-left: auto;
    margin-right: auto;
    padding-left: var(--gutter);
    padding-right: var(--gutter);
}

.record__notice {
    margin-bottom: var(--sp-5);
}

.record__desc {
    display: block;
    margin-bottom: var(--sp-5);
    font-size: var(--fs-sub);
    line-height: $lh-sub;
    color: var(--t-3);
    letter-spacing: 0;
}

.record__grid {
    display: flex;
    flex-direction: row;
    flex-wrap: wrap;
    justify-content: space-between;
}
</style>
