<template>
    <!--
      C-11 AppTabBar（G11 底部一级导航 · 4 项）
      规格：4 项 = 首页 / 记录中心 / 趋势 / 我的；总高 = `var(--tabbar-total-h)`（见 DESIGN.md §10.2）；
            **不得新增第 5 项**（DESIGN.md §11）。

      八态：default（可点）/ pressed（按下反馈）/ disabled（本批：目标页未实现 → **置灰不可点**）
            loading · error · success · empty · offline —— **N/A**（导航组件不承载数据态）

      图标：**纯 CSS 几何构成**，不使用图片素材、不使用 emoji（DESIGN.md §12）。
            ⚠️ 最终"图标方案"（自绘 vs `uni_modules/uni-icons`）与 native tabBar 的 8 张素材
            在需求方拍板前**不引入任何素材文件**；本组件因此不依赖 `static/`。

      ★ 本批（S3-2 第 1 步）落地口径：
        `pages/record/index`(SC-07) / `pages/trend/index`(SC-11) / `pages/mine/index`(SC-18)
        **尚未实现**，按需求方裁定「组件化 tabBar，仅首页可点」处理 ——
        未实现项以 `enabled: false` 传入，**渲染为置灰态且不派发 select 事件**，
        从而**不产生指向不存在页面的死链接**（与 `utils/route.js` 的既有约定一致）。
    -->
    <view class="tabbar">
        <view class="tabbar__inner">
            <view
                v-for="item in items"
                :key="item.key"
                class="tabbar__item"
                :class="itemClass(item)"
                :hover-class="canTap(item) ? 'tabbar__item--press' : 'none'"
                :hover-start-time="0"
                :hover-stay-time="80"
                @tap="handleTap(item)"
            >
                <view class="tabbar__icon" :class="'tabbar__icon--' + item.key">
                    <view class="tabbar__shape tabbar__shape--a"></view>
                    <view class="tabbar__shape tabbar__shape--b"></view>
                </view>
                <text class="tabbar__label">{{ item.label }}</text>
            </view>
        </view>
    </view>
</template>

<script>
export default {
    name: 'AppTabBar',
    props: {
        /**
         * 4 项配置：`[{ key, label, enabled }]`
         * key ∈ home / record / trend / mine（与 SC-06 顶部栏之外的 4 个一级页一一对应）
         */
        items: { type: Array, default: function () { return [] } },
        /** 当前所在项 key */
        current: { type: String, default: '' }
    },
    emits: ['select'],
    methods: {
        canTap: function (item) {
            return !!(item && item.enabled) && item.key !== this.current
        },
        itemClass: function (item) {
            return {
                'tabbar__item--active': item.key === this.current,
                'tabbar__item--disabled': !item.enabled
            }
        },
        handleTap: function (item) {
            // 未实现项（enabled = false）与当前项：不派发事件（无死链接、无空跳转）
            if (!this.canTap(item)) {
                return
            }
            this.$emit('select', item)
        }
    }
}
</script>

<style scoped lang="scss">
.tabbar {
    position: fixed;
    left: 0;
    right: 0;
    bottom: 0;
    z-index: 20;
    background-color: var(--s-card);
    border-top: 1rpx solid var(--b-line);
    padding-bottom: var(--safe-b);
}

.tabbar__inner {
    display: flex;
    flex-direction: row;
    align-items: center;
    height: var(--tabbar-h);
}

.tabbar__item {
    flex: 1;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    height: 100%;
    transition: transform var(--d-fast) var(--ease-std), opacity var(--d-fast) var(--ease-std);
}

.tabbar__item--press {
    transform: scale(var(--press-scale));
    opacity: var(--press-opacity);
}

/* ── 图标容器（图标边长按 DESIGN.md §10.4② 例外以 px 栅格对齐；
      图形只用 flex + 尺寸 + 令牌间距构成，**不使用绝对定位偏移**，避免引入非标间距值） ── */
.tabbar__icon {
    display: flex;
    flex-direction: row;
    align-items: center;
    justify-content: center;
    width: 20px;
    height: 20px;
}

.tabbar__shape {
    flex-shrink: 0;
    background-color: var(--t-3);
    border-radius: var(--r-xs);
}

/* 选中：品牌色（"已选中"属 §2.2 允许用途；不表示健康好坏） */
.tabbar__item--active .tabbar__shape {
    background-color: var(--c-p-600);
}

.tabbar__item--active .tabbar__label {
    color: var(--c-p-600);
}

/* 未实现项：置灰（禁用态用"次要文字色"表达，不用透明度） */
.tabbar__item--disabled .tabbar__shape {
    background-color: var(--t-4);
}

.tabbar__item--disabled .tabbar__label {
    color: var(--t-4);
}

/* ── 首页：方框轮廓（"首页容器"的抽象几何；轮廓用边框，不用图片素材） ── */
.tabbar__icon--home .tabbar__shape--a {
    width: 18px;
    height: 16px;
    background-color: transparent;
    border: 2px solid var(--t-3);
    border-radius: var(--r-xs);
}

.tabbar__icon--home .tabbar__shape--b {
    display: none;
}

.tabbar__item--active .tabbar__icon--home .tabbar__shape--a {
    border-color: var(--c-p-600);
    background-color: transparent;
}

.tabbar__item--disabled .tabbar__icon--home .tabbar__shape--a {
    border-color: var(--t-4);
    background-color: transparent;
}

/* ── 记录中心：两条横线（列表） ── */
.tabbar__icon--record {
    flex-direction: column;
    align-items: flex-start;
    justify-content: center;
}

.tabbar__icon--record .tabbar__shape--a {
    width: 18px;
    height: 4px;
}

.tabbar__icon--record .tabbar__shape--b {
    width: 11px;
    height: 4px;
    margin-top: var(--sp-1);
}

/* ── 趋势：两条竖线（底对齐、不同高度 → "柱状"） ── */
.tabbar__icon--trend {
    align-items: flex-end;
}

.tabbar__icon--trend .tabbar__shape--a {
    width: 4px;
    height: 9px;
}

.tabbar__icon--trend .tabbar__shape--b {
    width: 4px;
    height: 17px;
    margin-left: var(--sp-1);
}

/* ── 我的：圆点 + 肩线（纵排） ── */
.tabbar__icon--mine {
    flex-direction: column;
    justify-content: center;
}

.tabbar__icon--mine .tabbar__shape--a {
    width: 10px;
    height: 10px;
    border-radius: var(--r-full);
}

.tabbar__icon--mine .tabbar__shape--b {
    width: 18px;
    height: 7px;
    border-radius: var(--r-full);
    margin-top: var(--sp-1);
}

.tabbar__label {
    margin-top: var(--sp-1);
    font-size: var(--fs-caption);
    line-height: $lh-caption;
    font-weight: $fw-regular;
    color: var(--t-3);
    letter-spacing: 0;
}
</style>
