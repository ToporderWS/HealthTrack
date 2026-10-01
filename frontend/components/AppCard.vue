<template>
    <!--
      C-02 AppCard
      variant = plain（--el-0 + 1rpx --b-line，★ 默认）/ raised（--el-1）/ brand-soft（--s-brand-soft）
      八态：本组件为**容器**，不承载交互态 —— pressed / disabled / loading / error / success / empty / offline 均 N/A。
      （可点卡片的按下态由使用方在外层处理，不改变本组件契约。）
    -->
    <view class="app-card" :class="cardClass">
        <view v-if="title || hasHead" class="app-card__head">
            <text v-if="title" class="app-card__title">{{ title }}</text>
            <slot name="title"></slot>
            <view class="app-card__extra">
                <slot name="extra"></slot>
            </view>
        </view>
        <slot></slot>
    </view>
</template>

<script>
export default {
    name: 'AppCard',
    props: {
        title: { type: String, default: '' },
        variant: { type: String, default: 'plain' }
    },
    computed: {
        hasHead: function () {
            return !!(this.$slots.title || this.$slots.extra)
        },
        cardClass: function () {
            return 'app-card--' + this.variant
        }
    }
}
</script>

<style scoped lang="scss">
.app-card {
    border-radius: var(--r-md);
    padding: var(--card-pad);
    box-sizing: border-box;
}

/* plain：平面卡（★ 默认）—— 靠 1rpx 边框 + 底色差建立层级，不加阴影 */
.app-card--plain {
    background-color: var(--s-card);
    border: 1rpx solid var(--b-line);
    box-shadow: var(--el-0);
}

/* raised：仅用于需要表达"浮起"的内容卡 */
.app-card--raised {
    background-color: var(--s-card);
    border: 1rpx solid var(--b-line);
    box-shadow: var(--el-1);
}

.app-card--brand-soft {
    background-color: var(--s-brand-soft);
    border: 1rpx solid var(--s-brand-soft);
}

.app-card__head {
    display: flex;
    flex-direction: row;
    align-items: center;
    justify-content: space-between;
    margin-bottom: var(--sp-5);
}

.app-card__title {
    font-size: var(--fs-h2);
    line-height: $lh-h2;
    font-weight: $fw-semibold;
    color: var(--t-1);
    letter-spacing: 0;
}

.app-card__extra {
    display: flex;
    flex-direction: row;
    align-items: center;
}
</style>
