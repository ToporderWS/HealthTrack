<template>
    <!--
      DevPagePreviewer —— **开发环境专用**页面预览器（不属于 DESIGN.md §11 的 25 页冻结清单）

      目的：S3 各批次开发 / 人工验收期间，能一处列出 25 个冻结页面、直达已实现页，
            避免"逐个手敲 URL、或点进空白页"。

      ★ 硬约束（逐条对应）：
        ① **仅在开发环境且 H5 生效**：整个模板被 `H5` 平台条件编译包裹；
           `enabled` 再按 `process.env.NODE_ENV !== 'production'` 判定。
           非 H5 平台编译后本组件为空节点；生产构建下 `enabled = false` → 不渲染任何内容。
        （注：本条注释正文**刻意不写**条件编译标记的字面量 —— HTML 注释中一旦出现注释结束符，
           注释会提前闭合，其后的说明文字会被当成真实文本渲染到页面上。）
        ② **不新增正式业务页面**：本身**不注册进 `pages.json`**（当前注册页 **25** 个，与 S4-1 落地一致），
           因此不计入 25 页、不改变正式路由流程、不影响启动 / 登录 / 引导 / TabBar。
        ③ **已实现页面可点进预览**；**未实现页面灰显且点击只提示**，绝不跳进空白 / 错误页。
           未登录态页面（SC-03 登录页 / SC-04 注册页）在**已登录**时显示「需未登录」：
           点击弹说明弹窗并给出「退出登录并预览」，**不直接跳**（那两页自身的冻结守卫
           会在 onLoad 里立刻把人送回首页，看起来像"入口配错了"）。
        ④ 本组件**不发起任何网络请求**、**不写任何业务数据**。
           唯一例外：点在**用户显式确认**后执行「退出登录并预览」时，会调用**既有登出动作**
           清登录态 + 登录态缓存（`useUserStore().clearSessionAndCache()`），以便进入未登录态页面；
           它**不绕过、不修改**任何产品页面的登录守卫，也不做任何"临时跳转"。

      ★ "已实现"的判定：与 `pages.json` 的注册结果一致（**当前 = SC-01 ~ SC-25**，25/25）。
        新增批次落地后，请同步本表 `ready` 标记（唯一维护点）。
        （S3-6 顺带修正：本行此前停在「SC-01 ~ SC-11」，未随 S3-5 的 SC-12/13 同步更新；
          当时按 `pages.json` 实际注册结果（15 页）校正为 SC-01 ~ SC-15。）
        （S3-7：随 SC-16/17/18/19 注册落地，按 `pages.json` 实际注册结果（19 页）
          更新为 SC-01 ~ SC-19。）
        （S3-8：随 SC-20/21/22 注册落地，按 `pages.json` 实际注册结果（22 页）
          更新为 SC-01 ~ SC-22；剩余未实现 = SC-23 ~ SC-25。）
        （**S4-1：随 SC-23/24/25 注册落地，按 `pages.json` 实际注册结果（25 页）
          更新为 SC-01 ~ SC-25；剩余未实现 = 无。**）

      ★ 视觉：纯 CSS 几何图标（无 emoji、无图标库）；颜色 / 间距 / 字号全部走设计令牌。
    -->
    <!-- #ifdef H5 -->
    <view v-if="enabled" class="devpv">
        <!-- 悬浮入口（右下角，TabBar 之上） -->
        <view
            class="devpv__fab"
            hover-class="devpv__fab--press"
            :hover-start-time="0"
            :hover-stay-time="80"
            @tap="openPanel"
        >
            <view class="devpv__fab-icon">
                <view class="devpv__fab-bar"></view>
                <view class="devpv__fab-bar"></view>
                <view class="devpv__fab-bar"></view>
            </view>
        </view>

        <!-- 全屏面板 -->
        <template v-if="open">
            <view class="devpv__panel">
                <view class="devpv__head">
                    <text class="devpv__title">页面预览器</text>
                    <text class="devpv__sub">开发环境 · 仅 H5 · 不计入 25 页</text>
                    <text class="devpv__count">已实现 {{ readyCount }} / {{ pages.length }}</text>
                </view>

                <scroll-view class="devpv__list" scroll-y>
                    <view
                        v-for="page in pages"
                        :key="page.id"
                        class="devpv__row"
                        hover-class="devpv__row--press"
                        :hover-start-time="0"
                        :hover-stay-time="80"
                        @tap="pick(page)"
                    >
                        <text class="devpv__id">{{ page.id }}</text>
                        <view class="devpv__info">
                            <text class="devpv__name" :class="{ 'devpv__name--off': !page.ready }">{{ page.name }}</text>
                            <text class="devpv__path">{{ page.path }}</text>
                            <text v-if="page.note" class="devpv__note">{{ page.note }}</text>
                        </view>
                        <text
                            class="devpv__state"
                            :class="{ 'devpv__state--off': !page.ready, 'devpv__state--hold': isHeld(page) }"
                        >{{ stateText(page) }}</text>
                    </view>
                </scroll-view>

                <view
                    class="devpv__foot"
                    hover-class="devpv__foot--press"
                    :hover-start-time="0"
                    :hover-stay-time="80"
                    @tap="closePanel"
                >
                    <text class="devpv__foot-text">关闭</text>
                </view>
            </view>
        </template>

        <!--
          未登录态页面（SC-03 登录页 / SC-04 注册页）守卫说明。
          ★ 已登录时**不直接跳转**：那两页自身的冻结守卫会立刻把用户送回首页 ——
            看起来就像"点了入口没进对页面"。此处给出真实原因 + 一个明确的、可逆的退出入口。
          ★ 本弹窗**只服务预览器**，不改变任何产品页面的行为。
        -->
        <view class="devpv__guard">
            <AppModal
                :show="guardVisible"
                mode="confirm"
                title="该页面需要未登录状态"
                :content="guardText"
                confirm-text="退出登录并预览"
                cancel-text="取消"
                @confirm="onGuardConfirm"
                @cancel="onGuardCancel"
            />
        </view>
    </view>
    <!-- #endif -->
</template>

<script>
import AppModal from './AppModal.vue'
import { showToast } from '../utils/toast'
import { hasSession, clearSessionAndCache } from '../utils/auth'
import { useUserStore } from '../store/user'

/**
 * 25 页冻结清单（逐字取自 `DESIGN.md` §11）。
 *   - `ready`：该页是否已在 `pages.json` 注册（= 已实现，可进入预览）；
 *   - `url`  ：预览跳转地址（带参页面使用**示例参数**，见 `note`）。
 */
const PAGES = [
    {
        id: 'SC-01', name: '启动页', path: 'pages/launch/index', ready: true, url: '/pages/launch/index',
        note: '启动即按登录态自动分流（已登录 → 首页），停留时间很短'
    },
    { id: 'SC-02', name: '首次引导页', path: 'pages/onboarding/index', ready: true, url: '/pages/onboarding/index' },
    {
        id: 'SC-03', name: '登录页', path: 'pages/auth/login', ready: true, url: '/pages/auth/login',
        signedOutOnly: true, note: '未登录态页面：已登录时会离开本页'
    },
    {
        id: 'SC-04', name: '注册页', path: 'pages/auth/register', ready: true, url: '/pages/auth/register',
        signedOutOnly: true, note: '未登录态页面：已登录时会离开本页'
    },
    {
        id: 'SC-05', name: '建档引导页', path: 'pages/onboarding/profile-setup',
        ready: true, url: '/pages/onboarding/profile-setup'
    },
    { id: 'SC-06', name: '首页', path: 'pages/index/index', ready: true, url: '/pages/index/index' },
    { id: 'SC-07', name: '记录中心', path: 'pages/record/index', ready: true, url: '/pages/record/index' },
    {
        id: 'SC-08', name: '通用录入页', path: 'pages/record/add?type=',
        ready: true, url: '/pages/record/add?type=weight', note: '示例参数 type=weight'
    },
    {
        id: 'SC-09', name: '记录详情页', path: 'pages/record/detail?id=&type=',
        ready: true, url: '/pages/record/detail?id=1&type=weight',
        note: '示例参数 id=1（无此记录时页面显示「记录不存在」）'
    },
    {
        id: 'SC-10', name: '记录历史列表', path: 'pages/record/history?type=',
        ready: true, url: '/pages/record/history?type=weight', note: '示例参数 type=weight'
    },
    {
        id: 'SC-11', name: '趋势页', path: 'pages/trend/index?type=',
        ready: true, url: '/pages/trend/index?type=weight', note: '示例参数 type=weight（可选，8 类之一）'
    },
    { id: 'SC-12', name: '目标页', path: 'pages/goal/index', ready: true, url: '/pages/goal/index' },
    {
        id: 'SC-13', name: '目标编辑页', path: 'pages/goal/edit?type=', ready: true,
        url: '/pages/goal/edit?type=weight', note: '示例参数 type=weight（可选：weight/water/sport/sleep）'
    },
    { id: 'SC-14', name: '提醒列表页', path: 'pages/reminder/index', ready: true, url: '/pages/reminder/index' },
    {
        id: 'SC-15', name: '提醒编辑页', path: 'pages/reminder/edit?id=', ready: true,
        url: '/pages/reminder/edit', note: '不带 id 进入新建模式；带 ?id= 时须为已存在的提醒'
    },
    { id: 'SC-16', name: '健康档案页', path: 'pages/profile/index', ready: true, url: '/pages/profile/index' },
    { id: 'SC-17', name: '档案编辑页', path: 'pages/profile/edit', ready: true, url: '/pages/profile/edit' },
    { id: 'SC-18', name: '我的页', path: 'pages/mine/index', ready: true, url: '/pages/mine/index' },
    { id: 'SC-19', name: '修改密码页', path: 'pages/mine/password', ready: true, url: '/pages/mine/password' },
    { id: 'SC-20', name: '数据管理页', path: 'pages/data/index', ready: true, url: '/pages/data/index' },
    { id: 'SC-21', name: '数据导出页', path: 'pages/data/export', ready: true, url: '/pages/data/export' },
    { id: 'SC-22', name: '数据删除页', path: 'pages/data/delete', ready: true, url: '/pages/data/delete' },
    { id: 'SC-23', name: '隐私政策页', path: 'pages/mine/privacy', ready: true, url: '/pages/mine/privacy' },
    { id: 'SC-24', name: '用户协议页', path: 'pages/mine/terms', ready: true, url: '/pages/mine/terms' },
    { id: 'SC-25', name: '关于页', path: 'pages/mine/about', ready: true, url: '/pages/mine/about' }
]

/** 行状态文案：已实现 / 未实现（与点击提示 `NOT_READY_TEXT` 区分开，行内必须短） */
const READY_TEXT = '已实现'
const NOT_READY_STATE_TEXT = '未实现'

/** 「未实现」页面的点击提示（中性技术文案，不含"敬请期待"式占位话术） */
const NOT_READY_TEXT = '该页面尚未实现'

/**
 * 未登录态页面（`signedOutOnly`）在**已登录**时的行状态文案。
 * 不是"未实现"，而是"当前登录态下进不去"—— 用不同措辞免得与 `NOT_READY_TEXT` 混淆。
 */
const SIGNED_OUT_ONLY_TEXT = '需未登录'

/** 未登录态页面守卫说明（写清真实原因，避免被当成"入口配错"） */
const GUARD_TEXT = '登录页与注册页属未登录态页面：已登录时进入，会被页面自身的守卫'
    + '重定向回首页。预览前需先退出登录；退出后可随时重新登录（注册页底部有「去登录」）。'

export default {
    name: 'DevPagePreviewer',
    components: {
        AppModal: AppModal
    },
    data: function () {
        return {
            open: false,
            pages: PAGES,
            /** 未登录态页面的守卫弹窗 */
            guardVisible: false,
            guardPage: null,
            /** 打开面板时的登录态快照（用于行状态文案；每次打开面板刷新，避免陈旧） */
            signedIn: false
        }
    },
    computed: {
        /**
         * 是否启用（**仅开发环境的 H5**）。
         * 取值失败时保守返回 false（宁可预览器不出现，也不让它在生产环境冒出来）。
         */
        enabled: function () {
            try {
                if (typeof process === 'undefined' || !process.env) {
                    return false
                }
                return process.env.NODE_ENV !== 'production'
            } catch (e) {
                return false
            }
        },
        readyCount: function () {
            let count = 0
            for (let i = 0; i < this.pages.length; i++) {
                if (this.pages[i].ready) {
                    count++
                }
            }
            return count
        },
        /** 守卫弹窗正文（固定文案，单一来源） */
        guardText: function () {
            return GUARD_TEXT
        }
    },
    methods: {
        openPanel: function () {
            // 每次打开面板都刷新登录态快照（退出登录后重开面板，行状态文案要跟着变）
            this.signedIn = hasSession()
            this.open = true
        },
        closePanel: function () {
            this.open = false
        },
        /** 该行是否为「未登录态页面且当前登录态下确实进不去」 */
        isHeld: function (page) {
            return !!(page && page.signedOutOnly && this.signedIn)
        },
        /** 行状态文案：未实现 / 需未登录 / 已实现 */
        stateText: function (page) {
            if (!page) {
                return ''
            }
            if (!page.ready) {
                return NOT_READY_STATE_TEXT
            }
            return this.isHeld(page) ? SIGNED_OUT_ONLY_TEXT : READY_TEXT
        },
        /**
         * 点击一行：
         *   ① 未实现 → 只提示（**绝不跳进空白 / 错误页**）；
         *   ② 未登录态页面 + 当前已登录 → 弹守卫说明（**不直接跳**：那两页自身的冻结守卫
         *      会立刻把人送回首页，看起来像"点错入口"）；确认后先退出登录再进页；
         *   ③ 其余 → 直接预览。
         */
        pick: function (page) {
            if (!page) {
                return
            }
            if (!page.ready) {
                showToast('info', page.id + ' ' + NOT_READY_TEXT)
                return
            }
            if (page.signedOutOnly && hasSession()) {
                this.guardPage = page
                this.guardVisible = true
                return
            }
            this.go(page)
        },
        /** 真正跳转（关面板 → navigateTo；失败只提示，不做任何"绕道跳转"） */
        go: function (page) {
            this.open = false
            uni.navigateTo({
                url: page.url,
                fail: function () {
                    showToast('error', '打开失败：' + page.url)
                }
            })
        },
        onGuardCancel: function () {
            this.guardVisible = false
            this.guardPage = null
        },
        /**
         * 「退出登录并预览」：走**既有登出动作**（清 Token + 清登录态缓存），再进入该页。
         * ★ 本预览器**不绕过、也不修改**任何产品页面的登录守卫；只是把"需要未登录态"这件事
         *   如实告知，并提供一个可逆的出口（预览完可直接重新登录）。
         */
        onGuardConfirm: function () {
            const page = this.guardPage
            this.guardVisible = false
            this.guardPage = null
            try {
                useUserStore().clearSessionAndCache()
            } catch (e) {
                // store 不可用时退化为直接清本地登录态（保证守卫能放行）
                clearSessionAndCache()
            }
            this.signedIn = false
            if (page) {
                this.go(page)
            }
        }
    }
}
</script>

<style scoped lang="scss">
.devpv__fab {
    position: fixed;
    right: var(--sp-5);
    bottom: calc(var(--tabbar-total-h) + var(--sp-5));
    width: 88rpx;
    height: 88rpx;
    border-radius: var(--r-full);
    background-color: var(--c-p-600);
    display: flex;
    flex-direction: row;
    align-items: center;
    justify-content: center;
    box-shadow: var(--el-1);
    z-index: 900;
    transition: transform var(--d-fast) var(--ease-std), opacity var(--d-fast) var(--ease-std);
}

.devpv__fab--press {
    transform: scale(var(--press-scale));
    opacity: var(--press-opacity);
}

/* 图标：三条横线（纯几何，无 emoji / 无图标库） */
.devpv__fab-icon {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
}

.devpv__fab-bar {
    width: 32rpx;
    height: 4rpx;
    margin-top: var(--sp-1);
    border-radius: var(--r-xs);
    background-color: var(--t-inverse);
}

.devpv__fab-bar:first-child {
    margin-top: 0;
}

/* 面板：全屏（25 项需要足够空间） */
.devpv__panel {
    position: fixed;
    left: 0;
    right: 0;
    top: 0;
    bottom: 0;
    z-index: 960;
    display: flex;
    flex-direction: column;
    background-color: var(--s-page);
}

/*
 * 守卫弹窗层：封板组件 C-12 `AppModal` 的根节点 `.modal` 是 `z-index: 100`，
 * 而本面板是 `z-index: 960` ⇒ 若把弹窗与面板同级摆放，弹窗会被面板**盖住**：
 * DOM 里存在、却完全不可见、点不到，点击还会穿透到面板背后的行上（实测踩过）。
 * 这里用一层定位容器把弹窗整体抬到面板之上。
 * ★ 只作用于本开发工具；**未修改**封板组件 C-12。
 */
.devpv__guard {
    position: relative;
    z-index: 1000;
}

.devpv__head {
    display: flex;
    flex-direction: column;
    padding-top: var(--sp-7);
    padding-left: var(--card-pad);
    padding-right: var(--card-pad);
    padding-bottom: var(--sp-4);
}

.devpv__title {
    font-size: var(--fs-h2);
    line-height: $lh-h2;
    font-weight: $fw-semibold;
    color: var(--t-1);
    letter-spacing: 0;
}

.devpv__sub {
    margin-top: var(--sp-1);
    font-size: var(--fs-caption);
    line-height: $lh-caption;
    color: var(--t-3);
    letter-spacing: 0;
}

.devpv__count {
    margin-top: var(--sp-1);
    font-size: var(--fs-caption);
    line-height: $lh-caption;
    color: var(--t-3);
    letter-spacing: 0;
}

.devpv__list {
    flex: 1;
    padding-left: var(--card-pad);
    padding-right: var(--card-pad);
}

.devpv__row {
    display: flex;
    flex-direction: row;
    align-items: center;
    min-height: var(--row-h);
    padding-top: var(--row-pad-y);
    padding-bottom: var(--row-pad-y);
    border-bottom: 1rpx solid var(--b-line);
}

.devpv__row--press {
    background-color: var(--s-sunken);
}

.devpv__id {
    width: 96rpx;
    flex-shrink: 0;
    font-size: var(--fs-caption);
    line-height: $lh-caption;
    color: var(--t-3);
    letter-spacing: 0;
}

.devpv__info {
    flex: 1;
    display: flex;
    flex-direction: column;
}

.devpv__name {
    font-size: var(--fs-sub);
    line-height: $lh-sub;
    font-weight: $fw-medium;
    color: var(--t-1);
    letter-spacing: 0;
}

.devpv__name--off {
    color: var(--t-4);
}

.devpv__path {
    margin-top: var(--sp-1);
    font-size: var(--fs-caption);
    line-height: $lh-caption;
    color: var(--t-3);
    letter-spacing: 0;
}

.devpv__note {
    margin-top: var(--sp-1);
    font-size: var(--fs-caption);
    line-height: $lh-caption;
    color: var(--t-4);
    letter-spacing: 0;
}

.devpv__state {
    flex-shrink: 0;
    margin-left: var(--sp-4);
    font-size: var(--fs-caption);
    line-height: $lh-caption;
    color: var(--c-p-600);
    letter-spacing: 0;
}

.devpv__state--off {
    color: var(--t-4);
}

/* 「需未登录」：不是"未实现"，用提示色区分（表示"当前登录态下进不去"） */
.devpv__state--hold {
    color: var(--c-warning);
}

.devpv__foot {
    display: flex;
    flex-direction: row;
    align-items: center;
    justify-content: center;
    min-height: var(--tap-min);
    padding-bottom: var(--safe-b);
    border-top: 1rpx solid var(--b-line);
    background-color: var(--s-card);
}

.devpv__foot--press {
    opacity: var(--press-opacity);
}

.devpv__foot-text {
    font-size: var(--fs-btn-m);
    line-height: $lh-btn-m;
    font-weight: $fw-medium;
    color: var(--c-p-600);
    letter-spacing: 0;
}
</style>
