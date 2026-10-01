<template>
    <!--
      C-31 DraftBanner（G15 兜底提示条 · 离线草稿，DESIGN.md §8.3 已登记）
      规格：说明「有未提交内容，是否继续？」+ [继续填写] [重新开始]；
            **仅回填，绝不自动提交**（DESIGN.md §8.3 C-31 / S1-C §三 第 11 条弹层规格）。

      八态：default（显示中）/ pressed（按钮按下）
            disabled · loading · error · success · empty · offline —— **N/A**
            （本组件是"提示 + 二选一"的静态条；草稿读取由宿主页在 `onLoad` 完成，
              条本身不发请求、不承载校验与提交。）
    -->
    <view v-if="show" class="draft">
        <text class="draft__text">{{ message }}</text>

        <view class="draft__actions">
            <view
                class="draft__btn draft__btn--continue"
                hover-class="draft__btn--press"
                :hover-start-time="0"
                :hover-stay-time="80"
                @tap="handleContinue"
            >
                <text class="draft__btn-text draft__btn-text--continue">{{ continueText }}</text>
            </view>

            <view
                class="draft__btn draft__btn--restart"
                hover-class="draft__btn--press"
                :hover-start-time="0"
                :hover-stay-time="80"
                @tap="handleRestart"
            >
                <text class="draft__btn-text draft__btn-text--restart">{{ restartText }}</text>
            </view>
        </view>
    </view>
</template>

<script>
export default {
    name: 'DraftBanner',
    props: {
        show: { type: Boolean, default: false },
        /** 固定文案（S1-C §三 第 11 条：不得改写） */
        text: { type: String, default: '有未提交内容，是否继续？' },
        continueText: { type: String, default: '继续填写' },
        restartText: { type: String, default: '重新开始' }
    },
    emits: ['continue', 'restart'],
    computed: {
        message: function () {
            return this.text ? String(this.text) : '有未提交内容，是否继续？'
        }
    },
    methods: {
        handleContinue: function () {
            this.$emit('continue')
        },
        handleRestart: function () {
            this.$emit('restart')
        }
    }
}
</script>

<style scoped lang="scss">
.draft {
    padding: var(--sp-4) var(--sp-5);
    border-radius: var(--r-sm);
    background-color: var(--c-info-bg);
}

.draft__text {
    display: block;
    font-size: var(--fs-caption);
    line-height: $lh-caption;
    color: var(--c-info);
    letter-spacing: 0;
}

.draft__actions {
    display: flex;
    flex-direction: row;
    align-items: center;
    margin-top: var(--sp-4);
}

.draft__btn {
    flex: 1;
    display: flex;
    flex-direction: row;
    align-items: center;
    justify-content: center;
    min-height: var(--tap-min);
    border-radius: var(--r-sm);
    transition: transform var(--d-fast) var(--ease-std), opacity var(--d-fast) var(--ease-std);
}

.draft__btn--press {
    transform: scale(var(--press-scale));
    opacity: var(--press-opacity);
}

.draft__btn--continue {
    background-color: var(--s-card);
    border: 1rpx solid var(--b-border);
    margin-right: var(--sp-5);
}

.draft__btn--restart {
    background-color: var(--s-sunken);
}

.draft__btn-text {
    font-size: var(--fs-btn-m);
    line-height: $lh-btn-m;
    font-weight: $fw-medium;
    letter-spacing: 0;
}

.draft__btn-text--continue {
    color: var(--c-p-600);
}

.draft__btn-text--restart {
    color: var(--t-2);
}
</style>
