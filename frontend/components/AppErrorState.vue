<template>
    <!--
      C-16 AppErrorState（G3 失败态）
      规格：几何构成插画位（**不使用插图库**，DESIGN.md §12 红线）+ 中性文案 + 「重试」；inline（局部）/ full（整页）。
      八态：error（即本态）/ pressed（重试键按下）/ default·disabled·loading·success·empty·offline —— **N/A**
            （离线态由 AppOfflineBar / 页面提示承担，本批不实现离线态插画变体）。
    -->
    <view class="err" :class="'err--' + variant">
        <view class="err__art">
            <view class="err__art-box"></view>
            <view class="err__art-bar err__art-bar--1"></view>
            <view class="err__art-bar err__art-bar--2"></view>
        </view>
        <text class="err__text">{{ text }}</text>
        <view
            v-if="showRetry"
            class="err__retry"
            hover-class="err__retry--press"
            :hover-start-time="0"
            :hover-stay-time="80"
            @tap="handleRetry"
        >
            <text class="err__retry-text">{{ retryText }}</text>
        </view>
    </view>
</template>

<script>
export default {
    name: 'AppErrorState',
    props: {
        variant: { type: String, default: 'inline' },
        text: { type: String, default: '内容加载失败，请稍后重试' },
        retryText: { type: String, default: '重试' },
        showRetry: { type: Boolean, default: true }
    },
    emits: ['retry'],
    methods: {
        handleRetry: function () {
            this.$emit('retry')
        }
    }
}
</script>

<style scoped lang="scss">
.err {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    padding: var(--sp-9) var(--card-pad);
}

.err--full {
    min-height: 60vh;
}

/* 几何构成插画位：两层错位矩形 + 一根横线（纯 CSS，无插图库） */
.err__art {
    position: relative;
    width: 120rpx;
    height: 96rpx;
    margin-bottom: var(--sp-5);
}

.err__art-box {
    position: absolute;
    left: 0;
    top: 0;
    width: 96rpx;
    height: 72rpx;
    border-radius: var(--r-sm);
    border: 2rpx solid var(--b-border);
    background-color: var(--s-card-sub);
}

.err__art-bar {
    position: absolute;
    height: 6rpx;
    border-radius: var(--r-xs);
    background-color: var(--b-border);
}

.err__art-bar--1 {
    right: 0;
    bottom: var(--sp-3);
    width: 64rpx;
}

.err__art-bar--2 {
    right: var(--sp-3);
    bottom: 0;
    width: 40rpx;
}

.err__text {
    font-size: var(--fs-body);
    line-height: $lh-body;
    color: var(--t-2);
    text-align: center;
    letter-spacing: 0;
}

.err__retry {
    margin-top: var(--sp-6);
    min-width: 200rpx;
    height: var(--tap-min);
    padding-left: var(--sp-7);
    padding-right: var(--sp-7);
    display: flex;
    align-items: center;
    justify-content: center;
    border-radius: var(--r-md);
    border: 1rpx solid var(--b-border);
    background-color: var(--s-card);
    transition: transform var(--d-fast) var(--ease-std), opacity var(--d-fast) var(--ease-std);
}

.err__retry--press {
    transform: scale(var(--press-scale));
    opacity: var(--press-opacity);
}

.err__retry-text {
    font-size: var(--fs-btn-m);
    line-height: $lh-btn-m;
    font-weight: $fw-medium;
    color: var(--c-p-600);
}
</style>
