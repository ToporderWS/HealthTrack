<template>
    <!--
      SC-14 提醒列表页（pages/reminder/index）
      依据：S1-C §二 SC-14（① 顶部栏 / ② 通知权限引导条 / ③ A-11 兜底区块 / ④ 全局总开关 /
            ⑤ 提醒项列表 / ⑥ 底部说明）｜DESIGN.md §8.2（C-19 / C-20）/ §8.3（C-30）/
            §10.3（**A 类系统导航栏**）/ §11 / §12 / §13

      顶栏：**A 类系统导航栏**（`DESIGN.md §10.3` 的 B 类自绘顶栏清单**不含** SC-14）——
            标题由 `pages.json` 指定，本页**不得**加 `navigationStyle: custom`。
            原型 ① 的【＋新建提醒】在系统导航栏放不下 ⇒ **照 SC-09 / SC-12 先例落内容区顶部**。

      数据来源：**纯本地，0 个接口**（S1-C §五 API 矩阵 / S1-D 三重复核「提醒表 0 张 / 无提醒接口」）
        · `utils/reminder.js`  → 提醒配置 / 到点计算 / 兜底确认状态
        · `utils/notify.js`    → 系统通知能力（能否通知 / 去设置）
        本页**不发任何网络请求**，因此**不存在**服务端加载 / 失败 / 离线分支。

      状态覆盖（DESIGN.md §13 底线清单，逐项说明）：
        正常 → 列表 + 兜底区块 + 总开关；
        空 → `AppEmpty`「还没有提醒」+「新建提醒」+ **保留底部系统限制说明**（S1-C SC-14 ⑩）；
        加载 → **N/A**：S1-C SC-14 ⑪ 明确「无网络加载（纯本地数据，同步读取），不设骨架屏」；
        失败 → **N/A（页面级）**：本页无请求；**局部**失败态 = 该条提醒标「未生效」+ 顶部黄条（SC-14 ⑫）；
        未登录 → 路由守卫 → SC-03；
        离线 → **完全可用**（S1-C SC-14 ⑭：查看 / 开关 / 新建 / 编辑 / 删除全部离线可用）⇒ 不置灰、
               不显示离线条，也**不适用**「离线数据 · 更新于 <时间>」标记（本页数据不是缓存，就是本地数据）；
        高风险确认 → **N/A（本页）**：删除入口在 SC-15（见下方「如实登记 ②」）；
        提交防重 → **N/A**：无请求、无幂等键。

      ★ 如实登记（本轮不做、不伪造，逐条给出原因）：
        ① 「未生效」在 **H5 恒为显示**：`notify.canNotify()` 在非 App 运行期恒为 false
           （裁定 A：H5 如实降级；裁定 4：真机系统通道留 S3-9）⇒ H5 验收时**顶部黄条常驻、
              每条开启中的提醒都带「未生效」**。这是两条裁定的必然结果，**不是缺陷**。
              单条关闭的提醒**不显示「未生效」**（裁定 ⑩），只体现开关为关。
        ② **本页无删除入口**：原型 ⑤（提醒项列表）与 ⑧（主要组件）均**未列出删除控件**，
           删除以 SC-15 ① 的【删除】为唯一入口 ⇒ 本页 SC-14 ⑮ 的「删除提醒二次确认」
           由 SC-15 承载（弹窗文案取自 SC-14 ⑮ 原文）。**若需本页也能删，请指定入口形态**（已登记待裁定）。
        ③ 「去记录」后**无法核实 SC-08 是否真的写入成功**（该页属已封板资产、不回传结果）。
           口径：本页在**返回时按"该提醒已被响应"标记确认**（A-11 的语义是「未**确认**」，
           去记录 / 标记已处理是两种确认方式）⇒ 该行从兜底区块移除（符合 SC-14 ⑯ 原文）。
           **不弹"已保存"式的成功提示**（避免把未核实的事说成成功）。已登记待裁定。
    -->
    <view class="rl">
        <view class="rl__body">
            <view class="rl__inner">
                <!-- ② 通知权限引导条（能力不可用 / 权限未开时显示；S1-C SC-14 ② / ⑫②） -->
                <view v-if="permissionVisible" class="rl__block">
                    <NotifyPermissionBar visible @action="onPermissionAction" />
                </view>

                <!-- ① 新建提醒（A 类页导航栏放不下 ⇒ 落内容区顶部） -->
                <view class="rl__block" hover-class="none" @tap="onCreate">
                    <AppButton label="新建提醒" block />
                </view>

                <!-- ③ A-11 兜底区块（未完成 / 错过；最多 5 条） -->
                <AppCard v-if="fallbackRows.length" class="rl__block">
                    <text class="rl__fb-title">{{ fallbackTitle }}</text>
                    <view
                        v-for="(row, i) in fallbackRows"
                        :key="row.key"
                        class="rl__fb-row"
                        :class="{ 'rl__fb-row--first': i === 0 }"
                    >
                        <view class="rl__fb-info">
                            <text class="rl__fb-name">{{ row.name }}</text>
                            <text class="rl__fb-time">{{ row.timeText }}</text>
                        </view>
                        <view
                            class="rl__fb-action"
                            hover-class="rl__fb-action--press"
                            :hover-start-time="0"
                            :hover-stay-time="80"
                            @tap="onFallbackAction(row)"
                        >
                            <text class="rl__fb-action-text">{{ row.actionText }}</text>
                        </view>
                    </view>
                </AppCard>

                <!-- ④ 全局总开关 -->
                <AppCard class="rl__block">
                    <AppListRow title="全部提醒" :last="true">
                        <template #tail>
                            <AppSwitch :model-value="globalEnabled" @change="onGlobalToggle" />
                        </template>
                    </AppListRow>
                </AppCard>

                <!-- ⑤ 提醒项列表 / 空态 -->
                <view v-if="!items.length" class="rl__block">
                    <AppEmpty
                        variant="common"
                        text="还没有提醒"
                        action-text="新建提醒"
                        @action="onCreate"
                    />
                </view>

                <AppCard v-else class="rl__block">
                    <AppListRow
                        v-for="(item, i) in items"
                        :key="item.id"
                        :icon="item.icon"
                        :title="item.name"
                        :subtitle="item.subtitle"
                        :last="i === items.length - 1"
                        arrow
                        @tap="onEditRow(item)"
                    >
                        <template #tail>
                            <!-- 「未生效」状态标记（SC-14 ⑤：未生效时显示状态标记） -->
                            <view v-if="item.ineffective" class="rl__badge">
                                <text class="rl__badge-text">未生效</text>
                            </view>
                            <!--
                              ★ 开关必须阻止事件冒泡到整行：整行的点按是"进入编辑"，
                                开关的点按是"切换开关"，两者不能同时发生。
                                双保险：① 外层容器 `@tap.stop`；② `onEditRow` 内 400ms 时间窗护栏
                                （即便 `.stop` 在某个平台不生效，也不会误跳转）。
                            -->
                            <view class="rl__sw" @tap.stop="onSwitchGuard">
                                <AppSwitch
                                    :model-value="item.enabled"
                                    @change="onItemToggle(item, $event)"
                                />
                            </view>
                        </template>
                    </AppListRow>
                </AppCard>

                <!-- ⑥ 底部说明（**空态下同样保留**，S1-C SC-14 ⑩ 明确要求） -->
                <text class="rl__note">
                    受系统权限与省电策略影响，提醒可能延迟或不触发，本应用会尽量提醒
                </text>
            </view>
        </view>

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
import AppSwitch from '../../components/AppSwitch.vue'
import AppEmpty from '../../components/AppEmpty.vue'
import AppToast from '../../components/AppToast.vue'
import NotifyPermissionBar from '../../components/NotifyPermissionBar.vue'
import DevPagePreviewer from '../../components/DevPagePreviewer.vue'

import { ROUTES, navigateTo, requireLogin } from '../../utils/route'
import { showToast } from '../../utils/toast'
import { canNotify, cancelAllRegistered, openSystemSettings, syncAll } from '../../utils/notify'
import {
    MAX_FALLBACK_ROWS,
    itemDisplayName,
    iconOf,
    subtitleText,
    loadConfig,
    listItems,
    pendingToday,
    missedRecent,
    markHandled,
    pruneConfirm,
    setGlobalEnabled,
    setItemEnabled,
    upcomingTriggers
} from '../../utils/reminder'

/** 开关点按与整行点按的防误触时间窗（毫秒）—— 见模板内注释「双保险」 */
const SWITCH_GUARD_MS = 400

/** 关键动作文案（逐字取自 S1-C SC-14 ③ / ⑯，**不自行发明**） */
const ACTION_RECORD = '去记录'
const ACTION_HANDLED = '标记已处理'
const TOAST_ON = '已开启'
const TOAST_OFF = '已关闭'
const TOAST_OFF_ALL = '已关闭全部提醒（数据记录功能不受影响）'
const TOAST_HANDLED = '已标记处理'
const TOAST_SETTING_UNSUPPORTED = '当前环境暂不支持系统通知设置'

export default {
    components: {
        AppButton: AppButton,
        AppCard: AppCard,
        AppListRow: AppListRow,
        AppSwitch: AppSwitch,
        AppEmpty: AppEmpty,
        AppToast: AppToast,
        NotifyPermissionBar: NotifyPermissionBar,
        DevPagePreviewer: DevPagePreviewer
    },
    data: function () {
        return {
            /** 全局总开关 */
            globalEnabled: true,
            /** 提醒项（渲染用，已拼好 name / subtitle / icon / ineffective） */
            items: [],
            /** A-11 兜底区块行（≤5）与模式：today / missed / 空串 */
            fallbackRows: [],
            fallbackMode: '',
            /** 系统通知能力（H5 恒 false，裁定 A） */
            notifyReady: false,
            /** 本次 onShow 之前是否已加载过（避免与 onLoad 重复计算） */
            entered: false,
            /** 最近一次开关点按时刻（防误触护栏） */
            lastToggleAt: 0,
            /** 「去记录」意图：返回本页后据此标记该提醒已响应 */
            pendingRecord: null
        }
    },
    computed: {
        /** 权限引导条：能力不可用 / 权限未开时显示 */
        permissionVisible: function () {
            return !this.notifyReady
        },
        /** 兜底区块标题（S1-C SC-14 ③ 的两句冻结文案） */
        fallbackTitle: function () {
            if (!this.fallbackRows.length) {
                return ''
            }
            if (this.fallbackMode === 'missed') {
                return '近 3 日错过 ' + this.fallbackRows.length + ' 条'
            }
            return '今天还有 ' + this.fallbackRows.length + ' 条未确认'
        }
    },
    onLoad: function () {
        // 未登录守卫（S1-C SC-14 ⑬：需登录）
        if (!requireLogin()) {
            return
        }
        this.refresh()
    },
    onShow: function () {
        // 裁定 ⑫：A-11 兜底区块在 onShow 刷新（纯本地、零请求，代价可忽略）；
        // 同时覆盖"从 SC-15 返回自动刷新"（DESIGN.md §7④）与"从 SC-08 返回移除该条"（SC-14 ⑯）。
        if (this.entered) {
            this.settlePendingRecord()
            this.refresh()
        }
        this.entered = true
    },
    methods: {
        /* ───────────── 本地数据装载（零请求） ───────────── */

        /**
         * 重算全部本地派生数据（**原子替换**，避免中间态渲染）。
         * 顺序刻意如此：① 能力（决定「未生效」）→ ② 配置（决定列表与开关）→ ③ 兜底区块。
         */
        refresh: function () {
            this.notifyReady = canNotify()
            // 剪枝：确认记录只保留最近若干天（避免本地键无界增长）
            pruneConfirm()

            const cfg = loadConfig()
            const raw = cfg.items || []
            const list = []
            for (let i = 0; i < raw.length; i++) {
                const item = raw[i]
                list.push({
                    id: item.id,
                    type: item.type,
                    enabled: item.enabled !== false,
                    name: itemDisplayName(item),
                    subtitle: subtitleText(item),
                    icon: iconOf(item),
                    /** 「未生效」= 全局开 + 单条开 + 系统通知能力不可用（裁定 ⑩：单条关闭不显示） */
                    ineffective: cfg.enabled !== false && item.enabled !== false && !this.notifyReady,
                    /** 源数据（供动作使用，避免动作里再读一次盘） */
                    raw: item
                })
            }

            const today = pendingToday()
            const missed = missedRecent()
            // S1-C SC-14 ③：**当日为 0 且近 3 日有错过**时，才展示「近 3 日错过 N 条」
            const useMissed = today.length === 0 && missed.length > 0
            const rows = useMissed ? missed : today

            this.globalEnabled = cfg.enabled !== false
            this.items = list
            this.fallbackMode = useMissed ? 'missed' : (rows.length ? 'today' : '')
            this.fallbackRows = this.buildRows(rows, useMissed)
        },

        /** 兜底行 → 渲染行（含时间格式与动作文案） */
        buildRows: function (rows, isMissed) {
            const out = []
            const list = rows || []
            for (let i = 0; i < list.length && i < MAX_FALLBACK_ROWS; i++) {
                const r = list[i]
                out.push({
                    key: r.key,
                    reminderId: r.reminderId,
                    time: r.time,
                    name: r.name,
                    // 当日行只显示时刻；past 3 日行必须带日期才有意义（`MM-DD HH:mm`）
                    timeText: isMissed ? r.key.slice(5, 10) + ' ' + r.time : r.time,
                    recordType: r.recordType,
                    actionText: r.recordType ? ACTION_RECORD : ACTION_HANDLED
                })
            }
            return out
        },

        /* ───────────── 交互 ───────────── */

        /** 「新建提醒」→ SC-15（无参 = 新建模式） */
        onCreate: function () {
            navigateTo(ROUTES.REMINDER_EDIT)
        },

        /**
         * 全局总开关。
         * 裁定 ⑪：**关闭 = 取消已注册通知**（而不是仅"不再注册"）—— 否则通知栏会残留，
         * 与 I-01 同理（S1-C SC-14 I-01 注）。
         */
        onGlobalToggle: function (next) {
            this.lastToggleAt = Date.now()
            const ok = setGlobalEnabled(next)
            if (!ok) {
                // 写入失败：不谎报成功，直接按真实状态重算
                this.refresh()
                showToast('error', '设置未保存，请重试')
                return
            }
            if (next) {
                showToast('success', TOAST_ON)
                // 重新开启 ⇒ 把 24h 窗口内的未来提醒重新排入（档 1 全量重建）
                syncSchedules()
            } else {
                // 关闭前先取消已注册通知，再重算（顺序与 I-01 一致：先系统侧、再本地展示）
                cancelRegisteredQuietly()
                showToast('info', TOAST_OFF_ALL)
            }
            this.refresh()
        },

        /** 单条开关 */
        onItemToggle: function (item, next) {
            this.lastToggleAt = Date.now()
            const ok = setItemEnabled(item.id, next)
            if (!ok) {
                this.refresh()
                showToast('error', '设置未保存，请重试')
                return
            }
            showToast(next ? 'success' : 'info', next ? TOAST_ON : TOAST_OFF)
            // 单条启停 ⇒ 重建全量排程（档 1：不逐条 diff、不做精确撤销）
            syncSchedules()
            this.refresh()
        },

        /** 开关外层容器的 `@tap.stop` 落点（本身无逻辑，只为阻止冒泡） */
        onSwitchGuard: function () {},

        /** 整行点按 → SC-15 编辑模式（带 ?id=） */
        onEditRow: function (item) {
            // 双保险之②：开关刚被点过 ⇒ 本次整行点按视为冒泡，直接忽略
            if (Date.now() - this.lastToggleAt < SWITCH_GUARD_MS) {
                return
            }
            if (!item || !item.id) {
                return
            }
            navigateTo(ROUTES.REMINDER_EDIT + '?id=' + item.id)
        },

        /**
         * 兜底行动作：
         *   可记录类 → SC-08（`?type=` 映射：喝水 / 运动 / 测量-血压·血糖·体重）；
         *   自定义类 → 直接标记已处理。
         */
        onFallbackAction: function (row) {
            if (row.recordType) {
                // 记下意图：返回本页后按"已响应"标记（口径与局限见文件头「如实登记 ③」）
                this.pendingRecord = {
                    reminderId: row.reminderId,
                    time: row.time,
                    key: row.key
                }
                navigateTo(ROUTES.RECORD_ADD + '?type=' + row.recordType)
                return
            }
            markHandled(row.reminderId, row.time)
            showToast('success', TOAST_HANDLED)
            this.refresh()
        },

        /** 从 SC-08 返回：把"去记录"过的该条标记为已响应（**不谎报写入成功**） */
        settlePendingRecord: function () {
            const p = this.pendingRecord
            if (!p) {
                return
            }
            this.pendingRecord = null
            markHandled(p.reminderId, p.time)
        },

        /** 「去设置」：取回真实结果，失败即如实告知（不假装能跳） */
        onPermissionAction: function () {
            const res = openSystemSettings()
            if (res && res.ok) {
                return
            }
            showToast('info', TOAST_SETTING_UNSUPPORTED)
        }
    }
}

/**
 * 排程同步：**对账式全量重建**（清空 → 按 24h 滚动窗口重排）。
 * 档 1 定档：**不做逐条 diff、不做精确撤销承诺**；失败不阻断交互（与 I-01 同一处置口径）。
 */
function syncSchedules() {
    try {
        syncAll(upcomingTriggers())
    } catch (e) {
        // 通知通道异常不应影响页面主流程
    }
}

/** 取消已注册通知（失败不阻断交互 —— 与 I-01 同一处置口径） */
function cancelRegisteredQuietly() {
    try {
        cancelAllRegistered()
    } catch (e) {
        // 通知通道异常不应影响页面主流程
    }
}
</script>

<style scoped lang="scss">
.rl {
    min-height: 100vh;
    background-color: var(--s-page);
}

/* A 类系统导航栏高度由平台负责，此处只留内容区节奏 */
.rl__body {
    padding-top: var(--page-pad-t);
    padding-bottom: var(--page-pad-b);
}

/* 内容最大宽居中（DESIGN.md §10.4③）+ 唯一水平边距来源 --gutter */
.rl__inner {
    max-width: var(--content-max);
    margin-left: auto;
    margin-right: auto;
    padding-left: var(--gutter);
    padding-right: var(--gutter);
}

.rl__block {
    margin-bottom: var(--card-gap);
}

/* ── A-11 兜底区块 ── */
.rl__fb-title {
    display: block;
    margin-bottom: var(--sp-3);
    font-size: var(--fs-body-strong);
    line-height: $lh-body-strong;
    font-weight: $fw-medium;
    color: var(--t-1);
    letter-spacing: 0;
}

.rl__fb-row {
    display: flex;
    flex-direction: row;
    align-items: center;
    min-height: var(--tap-min);
    padding-top: var(--sp-3);
    border-top: 1rpx solid var(--b-line);
}

/* 首行紧贴标题，不再重复画分隔线 */
.rl__fb-row--first {
    border-top: none;
}

.rl__fb-info {
    flex: 1;
    display: flex;
    flex-direction: column;
    justify-content: center;
    min-width: 0;
    padding-right: var(--sp-4);
}

.rl__fb-name {
    font-size: var(--fs-body);
    line-height: $lh-body;
    font-weight: $fw-medium;
    color: var(--t-1);
    letter-spacing: 0;
}

.rl__fb-time {
    margin-top: var(--sp-1);
    font-size: var(--fs-caption);
    line-height: $lh-caption;
    color: var(--t-3);
    letter-spacing: 0;
}

.rl__fb-action {
    display: flex;
    flex-direction: row;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
    min-width: var(--tap-min);
    min-height: var(--tap-min);
    padding-left: var(--sp-4);
    padding-right: var(--sp-4);
    border: 1rpx solid var(--b-border);
    border-radius: var(--r-sm);
    background-color: var(--s-card);
    transition: transform var(--d-fast) var(--ease-std), opacity var(--d-fast) var(--ease-std);
}

.rl__fb-action--press {
    transform: scale(var(--press-scale));
    opacity: var(--press-opacity);
}

.rl__fb-action-text {
    font-size: var(--fs-btn-m);
    line-height: $lh-btn-m;
    font-weight: $fw-medium;
    color: var(--t-link);
    letter-spacing: 0;
}

/* ── 「未生效」状态标记（SC-14 ⑤） ── */
.rl__badge {
    display: flex;
    flex-direction: row;
    align-items: center;
    margin-right: var(--sp-3);
    padding: var(--sp-1) var(--sp-2);
    border-radius: var(--r-xs);
    background-color: var(--c-warning-bg);
}

.rl__badge-text {
    font-size: var(--fs-caption);
    line-height: $lh-caption;
    color: var(--c-warning);
    letter-spacing: 0;
}

/* 开关外层：只用来阻断冒泡，本身不画任何东西 */
.rl__sw {
    display: flex;
    flex-direction: row;
    align-items: center;
}

/* ── ⑥ 底部说明（空态下同样保留） ── */
.rl__note {
    display: block;
    padding: var(--sp-2);
    font-size: var(--fs-caption);
    line-height: $lh-caption;
    color: var(--t-3);
    letter-spacing: 0;
}
</style>
