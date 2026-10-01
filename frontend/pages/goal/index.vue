<template>
    <!--
      SC-12 目标页（pages/goal/index）
      依据：S1-C §二 SC-12（① 顶部栏 / ② 目标卡列表 / ③ 达标率行）｜
            DESIGN.md §8.3（C-25 目标进度卡）/ §10.3（**A 类系统导航栏**）/ §11 / §12 / §13

      顶栏：**A 类系统导航栏**（`DESIGN.md §10.3` 的 B 类自绘顶栏清单**不含** SC-12）——
            标题由 `pages.json` 指定，本页**不得**加 `navigationStyle: custom`。
            原型 ① 的【＋ 新建目标】在系统导航栏放不下 ⇒ **照 SC-09 先例落内容区顶部**。

      数据来源（**刻意不使用 S-01**，避免与首页口径混淆）：
        · G-01 `GET /api/v1/goals`          → 目标本体（类型 / 目标值 / 状态 / 周期）
        · G-07 `GET /api/v1/goals/progress` → 完成度（当前值 / 百分比 / 是否达成 / 还差）+ 达标率

      ★ 两接口主键字段名不一致（**易错点，已实测**）：G-01 用 `id`、G-07 用 `goal_id`
        （两者指向同一目标）⇒ 本页以 `G-07.goal_id === G-01.id` 关联后再合并。

      ★ 排序：服务端固定 `ORDER BY goal_type ASC, id ASC`（字母序 ⇒ sleep→sport→water→weight），
        与原型顺序（体重→饮水→运动→睡眠）不同 ⇒ 客户端按 `GOAL_TYPE_ORDER` 重排。

      状态覆盖（DESIGN.md §13）：
        正常 / 加载（骨架屏）/ 空（「还没有设置目标」）/ 失败（失败组件 + 重试）/
        未登录（守卫 → SC-03）/ 离线（缓存只读 + 「离线数据 · 更新于 <时间>」；
        **未命中缓存 → 离线空态**，绝不冒充「还没有设置目标」）/ 401（统一请求层处理）。
        提交防重 → **N/A**（本页只读，无写操作）；高风险确认 → **N/A**（S1-C SC-12 无）。
    -->
    <view class="goal-page">
        <view class="goal-page__body">
            <view class="goal-page__inner">
                <!-- 离线只读标记 / 网络恢复横幅 -->
                <view v-if="offlineBarText" class="goal-page__block">
                    <AppOfflineBar variant="offline" :text="offlineBarText" />
                </view>
                <view v-if="restoredVisible" class="goal-page__block">
                    <AppOfflineBar variant="restored" text="网络已恢复，正在刷新" />
                </view>

                <!--
                  ① 新建入口
                  ★ 为什么要外层容器接管点击：A 类页的系统导航栏放不了自定义按钮，而本入口需要
                    「离线时置灰**但仍然给提示**」。`AppButton` 的 `disabled` 会拦掉自身 `tap`
                    事件（`handleTap` 直接 return，组件 §八态 disabled 口径），因此把点击交给
                    外层容器，内层按钮只负责视觉。在线 → 进 SC-13；离线 → 仅给中性提示。
                -->
                <view class="goal-page__block" hover-class="none" @tap="onCreate">
                    <AppButton label="新建目标" block :disabled="offline" />
                </view>

                <!-- ② 目标卡列表 / 各态 -->
                <view v-if="state === 'loading'" class="goal-page__block">
                    <AppSkeleton variant="list" />
                </view>

                <view v-else-if="state === 'error'" class="goal-page__block">
                    <AppErrorState variant="full" :text="errorMsg" @retry="reload" />
                </view>

                <view v-else-if="state === 'offline'" class="goal-page__block">
                    <AppEmpty variant="common" text="当前离线，暂无本地缓存数据" />
                </view>

                <view v-else-if="state === 'empty'" class="goal-page__block">
                    <AppEmpty
                        variant="common"
                        text="还没有设置目标"
                        action-text="新建目标"
                        @action="onCreate"
                    />
                </view>

                <template v-else>
                    <view v-for="item in items" :key="item.goal_id" class="goal-page__block">
                        <GoalProgressCard
                            :goal="item"
                            :status="item.status"
                            @tap="onGoalTap(item)"
                        />
                        <text v-if="rateTextOf(item)" class="goal-page__rate">{{ rateTextOf(item) }}</text>
                    </view>
                </template>
            </view>
        </view>

        <!-- 轻提示宿主（离线提示 / 会话失效提示由统一请求层经此渲染） -->
        <AppToast />

        <!-- 开发环境页面预览器（仅 H5 非生产环境渲染；生产构建下为空节点） -->
        <DevPagePreviewer />
    </view>
</template>

<script>
import AppButton from '../../components/AppButton.vue'
import AppEmpty from '../../components/AppEmpty.vue'
import AppSkeleton from '../../components/AppSkeleton.vue'
import AppErrorState from '../../components/AppErrorState.vue'
import AppOfflineBar from '../../components/AppOfflineBar.vue'
import AppToast from '../../components/AppToast.vue'
import GoalProgressCard from '../../components/GoalProgressCard.vue'
// 开发环境专用页面预览器（**仅 H5 + 非生产**生效；不注册进 `pages.json`、不计入 25 页）
import DevPagePreviewer from '../../components/DevPagePreviewer.vue'

import { ROUTES, navigateTo, requireLogin } from '../../utils/route'
import { fetchGoals, fetchGoalsProgress, DEFAULT_RATE_WINDOW, GOAL_TYPE_ORDER } from '../../api/goals'
import { CACHE_KEYS, loadCache, saveCache } from '../../utils/cache'
import { errorText } from '../../utils/request'
import { showToast } from '../../utils/toast'
import { NETWORK_BANNER_MS } from '../../utils/config'

/**
 * 合并 G-01（目标本体）与 G-07（完成度）。
 *
 * 关联键：`G-07.goal_id === G-01.id`（两接口字段名不同，见文件头注）。
 * 排序：按 `GOAL_TYPE_ORDER`（原型顺序）；**未知类型排到最后**（不隐藏数据、不猜测类型）。
 *
 * 保护口径：G-07 缺项一律保持 `null` / 缺省（**不补 0**）——
 *   `weight` 目标在"无体重记录"时 `progress_percent` / `remaining_value` / `remaining_text`
 *   均为 `null`，组件据此显示「—」并隐藏「还差」行。
 */
function mergeGoals(goalRows, progressRows) {
    const byId = {}
    const progresses = progressRows || []
    for (let i = 0; i < progresses.length; i++) {
        const row = progresses[i]
        if (row && row.goal_id !== undefined && row.goal_id !== null) {
            byId[String(row.goal_id)] = row
        }
    }

    const list = []
    const goals = goalRows || []
    for (let i = 0; i < goals.length; i++) {
        const g = goals[i]
        if (!g) {
            continue
        }
        const p = byId[String(g.id)] || {}
        list.push({
            goal_id: g.id,
            goal_type: g.goal_type,
            target_value: g.target_value,
            unit: g.unit,
            attr_1: g.attr_1,
            start_date: g.start_date,
            target_date: g.target_date,
            start_weight_kg: g.start_weight_kg,
            status: g.status,
            status_text: g.status_text,
            current_value: p.current_value,
            progress_percent: p.progress_percent,
            is_reached: p.is_reached === true,
            remaining_value: p.remaining_value,
            remaining_text: p.remaining_text,
            period_label: p.period_label,
            rate: p.rate || null
        })
    }

    list.sort(function (a, b) {
        const ia = GOAL_TYPE_ORDER.indexOf(a.goal_type)
        const ib = GOAL_TYPE_ORDER.indexOf(b.goal_type)
        const va = ia < 0 ? GOAL_TYPE_ORDER.length : ia
        const vb = ib < 0 ? GOAL_TYPE_ORDER.length : ib
        return va - vb
    })
    return list
}

export default {
    components: {
        AppButton: AppButton,
        AppEmpty: AppEmpty,
        AppSkeleton: AppSkeleton,
        AppErrorState: AppErrorState,
        AppOfflineBar: AppOfflineBar,
        AppToast: AppToast,
        GoalProgressCard: GoalProgressCard,
        DevPagePreviewer: DevPagePreviewer
    },
    data: function () {
        return {
            /** 页面态：loading / normal / empty / offline / error */
            state: 'loading',
            /** 合并后的目标列表（G-01 + G-07） */
            items: [],
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
        }
    },
    onLoad: function () {
        // 未登录守卫（S1-C SC-12：需登录）
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
        // 从 SC-13 返回自动刷新（DESIGN.md §7④）；首次进入由 onLoad 负责，避免双发
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
    methods: {
        /* ───────────── 数据加载 ───────────── */

        /**
         * 加载 G-01 + G-07。
         * ★ 两者**都成功**才进入正常态：目标卡（G-01）与完成度（G-07）缺一不可，
         *   若只拿到本体就渲染，会把"完成度未知"画成 0%（**展示不实数据**）。
         * @param {boolean} silent 静默刷新（返回本页 / 网络恢复）：不显示骨架，避免打断阅读
         */
        load: function (silent) {
            const self = this
            this.reqToken += 1
            const token = this.reqToken
            this.errorMsg = ''

            // 先读本地缓存：命中 → 立即只读渲染（离线可看），再向服务端刷新
            if (!silent) {
                const cached = loadCache(CACHE_KEYS.GOAL)
                if (cached && cached.data && cached.data.items) {
                    this.commit(cached.data.items, cached.savedAt, true)
                } else if (!this.items.length) {
                    this.state = 'loading'
                }
            }

            return Promise.all([
                fetchGoals(),
                fetchGoalsProgress(DEFAULT_RATE_WINDOW)
            ]).then(function (res) {
                // 过期响应（页面已重新加载）→ 丢弃，由最新一次请求收尾
                if (token !== self.reqToken) {
                    return
                }
                const goalRows = (res[0] && res[0].data && res[0].data.items) || []
                const progressRows = (res[1] && res[1].data && res[1].data.items) || []
                const merged = mergeGoals(goalRows, progressRows)
                self.offline = false
                const savedAt = self.saveAndStamp(merged)
                self.commit(merged, savedAt, false)
            }, function (err) {
                if (token !== self.reqToken) {
                    return
                }
                if (err && err.isNetwork) {
                    // ★ 401 / 会话失效**不会**走到这里（统一请求层已处理并清栈回 SC-03），
                    //   因此 isNetwork 就是真离线 —— 不能把 401 当成空态（会谎报"没有目标"）。
                    self.offline = true
                    if (self.items.length) {
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
         * @param {Array} list 合并后的列表
         * @param {string} savedAt 缓存写入时刻（空串 = 非缓存来源）
         * @param {boolean} fromCache 本次是否来自本地缓存
         */
        commit: function (list, savedAt, fromCache) {
            this.items = list || []
            this.state = this.items.length ? 'normal' : 'empty'
            this.cacheSavedAt = fromCache ? (savedAt || '') : ''
        },

        /** 写缓存并回读写入时刻（`saveCache` 不返回时间戳；回读一次最准确，开销可忽略） */
        saveAndStamp: function (list) {
            if (!saveCache(CACHE_KEYS.GOAL, { items: list })) {
                return ''
            }
            const back = loadCache(CACHE_KEYS.GOAL)
            return back ? back.savedAt : ''
        },

        /* ───────────── 渲染辅助 ───────────── */

        /**
         * 达标率行文案：「近 N 天达标 M 天」。
         *
         * 口径（全部取自服务端，客户端**不自行计算**）：
         *   · `rate` 为 `null` → 不显示（`weight` 目标恒 `null`：无每日 / 每周周期）；
         *   · `reached_rate_percent` 为 `null` → 不显示（窗口内无记录；服务端不除零、不补零）；
         *   · 天数用回显的 `window_days` **动态拼**（不硬编码「7 天」）。
         * 红线：只陈述计数事实，**不含任何评判词**（DESIGN.md §12）。
         */
        rateTextOf: function (item) {
            const rate = item && item.rate ? item.rate : null
            if (!rate) {
                return ''
            }
            const percent = rate.reached_rate_percent
            if (percent === null || percent === undefined) {
                return ''
            }
            const days = Number(rate.window_days)
            const reachedDays = Number(rate.days_reached)
            if (isNaN(days) || isNaN(reachedDays)) {
                return ''
            }
            return '近 ' + days + ' 天达标 ' + reachedDays + ' 天'
        },

        /* ───────────── 出口 ───────────── */

        /** 「新建目标」：离线时**不进入表单**，仅给中性提示（S1-C SC-12 离线行） */
        onCreate: function () {
            if (this.offline) {
                showToast('info', '当前处于离线状态，新建目标需要联网后操作')
                return
            }
            navigateTo(ROUTES.GOAL_EDIT)
        },

        /** 目标卡 → SC-13（带该目标的类型；无类型则不下发跳转，避免打开非法页） */
        onGoalTap: function (item) {
            if (!item || !item.goal_type) {
                return
            }
            navigateTo(ROUTES.GOAL_EDIT + '?type=' + item.goal_type)
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
.goal-page {
    min-height: 100vh;
    background-color: var(--s-page);
}

/* A 类系统导航栏占位由平台负责，此处只留内容区节奏 */
.goal-page__body {
    padding-top: var(--page-pad-t);
    padding-bottom: var(--page-pad-b);
}

/* 内容最大宽居中（DESIGN.md §10.4③）+ 唯一水平边距来源 --gutter */
.goal-page__inner {
    max-width: var(--content-max);
    margin-left: auto;
    margin-right: auto;
    padding-left: var(--gutter);
    padding-right: var(--gutter);
}

.goal-page__block {
    margin-bottom: var(--card-gap);
}

/* 达标率行：紧贴对应目标卡下方的中性小字（只陈述计数事实） */
.goal-page__rate {
    display: block;
    margin-top: var(--sp-3);
    padding-left: var(--sp-2);
    padding-right: var(--sp-2);
    font-size: var(--fs-caption);
    line-height: $lh-caption;
    color: var(--t-3);
    letter-spacing: 0;
}
</style>
