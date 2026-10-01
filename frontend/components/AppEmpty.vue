<template>
    <!--
      C-14 AppEmpty（G1 空状态 / 首次使用）
      规格：几何构成插画位（**不使用插图库**，DESIGN.md §12 红线）+ 一行说明 + 主行动按钮；
            variant = common（该处无数据）/ first-use（首次使用，多一句"为什么需要用" + 引导按钮，见 §13）。

      八态：empty（即本态）/ pressed（行动键按下）
            default · disabled · loading · error · success · offline —— **N/A**
            （失败态由 C-16 AppErrorState 承担；离线态由 C-17 AppOfflineBar + 页面提示承担，
              不制造重复语义的插画变体。）

      插画位与按钮**全部使用设计令牌**；插画为纯 CSS 几何，不含任何图片素材。
    -->
    <view class="empty" :class="'empty--' + variant">
        <view class="empty__art">
            <view class="empty__ring"></view>
            <view class="empty__bar empty__bar--1"></view>
            <view class="empty__bar empty__bar--2"></view>
        </view>

        <text class="empty__text">{{ text }}</text>

        <!-- 首次使用：多一句"为什么需要用"（DESIGN.md §13） -->
        <text v-if="variant === 'first-use' && hint" class="empty__hint">{{ hint }}</text>

        <view
            v-if="showAction && actionText"
            class="empty__action"
            hover-class="empty__action--press"
            :hover-start-time="0"
            :hover-stay-time="80"
            @tap="handleAction"
        >
            <text class="empty__action-text">{{ actionText }}</text>
        </view>
    </view>
</template>

<script>
export default {
    name: 'AppEmpty',
    props: {
        /** common = 该处暂无数据；first-use = 首次使用（附"为什么需要用"） */
        variant: { type: String, default: 'common' },
        /** 主说明（**必须**取自 DESIGN.md §12 的空状态文案口径） */
        text: { type: String, default: '' },
        /** 首次使用的补充说明（仅 variant = first-use 时展示） */
        hint: { type: String, default: '' },
        /** 主行动按钮文案（为空则不渲染按钮，避免出现无去处的空按钮） */
        actionText: { type: String, default: '' },
        showAction: { type: Boolean, default: true }
    },
    emits: ['action'],
    methods: {
        handleAction: function () {
            this.$emit('action')
        }
    }
}
</script>

<style scoped lang="scss">
.empty {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    padding: var(--sp-9) var(--card-pad);
}

.empty--first-use {
    padding-top: var(--sp-10);
    padding-bottom: var(--sp-10);
}

/* 几何构成插画位：空圆环 + 两根不同长度的横线（纯 CSS，无插图库） */
.empty__art {
    position: relative;
    width: 120rpx;
    height: 96rpx;
    margin-bottom: var(--sp-6);
}

.empty__ring {
    position: absolute;
    left: 0;
    top: 0;
    width: 72rpx;
    height: 72rpx;
    border-radius: var(--r-full);
    border: 2rpx solid var(--b-border);
    background-color: var(--s-card-sub);
}

.empty__bar {
    position: absolute;
    right: 0;
    height: 6rpx;
    border-radius: var(--r-xs);
    background-color: var(--b-border);
}

.empty__bar--1 {
    bottom: var(--sp-4);
    width: 56rpx;
}

.empty__bar--2 {
    bottom: 0;
    right: var(--sp-4);
    width: 32rpx;
}

.empty__text {
    font-size: var(--fs-body);
    line-height: $lh-body;
    color: var(--t-2);
    text-align: center;
    letter-spacing: 0;
}

.empty__hint {
    margin-top: var(--sp-3);
    font-size: var(--fs-sub);
    line-height: $lh-sub;
    color: var(--t-3);
    text-align: center;
    letter-spacing: 0;
}

/* 主行动键：热区 ≥ --tap-min，主色底 */
.empty__action {
    margin-top: var(--sp-7);
    min-width: 240rpx;
    height: var(--tap-min);
    padding-left: var(--sp-8);
    padding-right: var(--sp-8);
    display: flex;
    align-items: center;
    justify-content: center;
    border-radius: var(--r-md);
    background-color: var(--c-p-600);
    transition: transform var(--d-fast) var(--ease-std), opacity var(--d-fast) var(--ease-std);
}

.empty__action--press {
    transform: scale(var(--press-scale));
    opacity: var(--press-opacity);
}

.empty__action-text {
    font-size: var(--fs-btn-m);
    line-height: $lh-btn-m;
    font-weight: $fw-medium;
    color: var(--t-inverse);
    letter-spacing: 0;
}
</style>
