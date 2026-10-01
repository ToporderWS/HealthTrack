<template>
    <!--
      C-10 AppNavBar（自绘顶栏）
      八态：default / pressed（返回键按下）/ disabled(N/A) / loading(N/A) / error(N/A) / success(N/A) / empty(N/A) / offline(N/A)
      总高 = var(--nav-total-h) = 状态栏 + var(--navbar-h)（DESIGN.md §10.2 / §10.3，仅 B 类页面使用）。
    -->
    <view class="navbar" :class="{ 'navbar--shadow': shadow }">
        <view class="navbar__status"></view>
        <view class="navbar__bar">
            <view class="navbar__side navbar__side--left">
                <view
                    v-if="showBack"
                    class="navbar__back"
                    hover-class="navbar__back--press"
                    :hover-start-time="0"
                    :hover-stay-time="80"
                    @tap="handleBack"
                >
                    <!-- 返回箭头：纯 CSS 几何（旋转 45° 的两段边框），不引入图标库 -->
                    <view class="navbar__chevron"></view>
                </view>
                <slot name="left"></slot>
            </view>
            <text class="navbar__title">{{ title }}</text>
            <view class="navbar__side navbar__side--right">
                <slot name="right"></slot>
            </view>
        </view>
    </view>
</template>

<script>
export default {
    name: 'AppNavBar',
    props: {
        title: { type: String, default: '' },
        showBack: { type: Boolean, default: false },
        shadow: { type: Boolean, default: false }
    },
    emits: ['back'],
    methods: {
        handleBack: function () {
            this.$emit('back')
        }
    }
}
</script>

<style scoped lang="scss">
.navbar {
    position: fixed;
    top: 0;
    left: 0;
    right: 0;
    z-index: 20;
    background-color: var(--s-card);
}

.navbar--shadow {
    box-shadow: var(--el-2);
}

/* 状态栏占位（--status-bar-height 为平台提供变量，直接引用） */
.navbar__status {
    height: var(--status-bar-height);
    width: 100%;
}

.navbar__bar {
    display: flex;
    flex-direction: row;
    align-items: center;
    height: var(--navbar-h);
    padding-left: var(--sp-3);
    padding-right: var(--sp-3);
}

.navbar__side {
    display: flex;
    flex-direction: row;
    align-items: center;
    min-width: var(--tap-min);
}

.navbar__side--right {
    justify-content: flex-end;
}

.navbar__title {
    flex: 1;
    text-align: center;
    font-size: var(--fs-h2);
    line-height: $lh-h2;
    font-weight: $fw-semibold;
    color: var(--t-1);
    letter-spacing: 0;
    overflow: hidden;
    white-space: nowrap;
    text-overflow: ellipsis;
}

/* 返回键热区 ≥ var(--tap-min) */
.navbar__back {
    width: var(--tap-min);
    height: var(--tap-min);
    display: flex;
    align-items: center;
    justify-content: flex-start;
    transition: transform var(--d-fast) var(--ease-std), opacity var(--d-fast) var(--ease-std);
}

.navbar__back--press {
    transform: scale(var(--press-scale));
    opacity: var(--press-opacity);
}

/* 箭头（图标边长按 DESIGN.md §10.4 例外以 px 栅格对齐） */
.navbar__chevron {
    width: 9px;
    height: 9px;
    border-left: 2px solid var(--t-1);
    border-bottom: 2px solid var(--t-1);
    transform: rotate(45deg);
    margin-left: var(--sp-3);
}
</style>
