<template>
    <!--
      C-01 AppButton（G12 提交按钮 · 防重复提交）
      八态：default / pressed / disabled / loading / error(N/A) / success(N/A) / empty(N/A) / offline(N/A)
        - error / success：按钮自身不承载结果态，统一由 AppToast / AppValidateBar / AppErrorState 表达；
        - empty：无内容态概念；
        - offline：离线由页面在提交前拦截并提示（DESIGN.md §13），按钮保持 default + disabled 由页面控制。
      规格：type = primary / secondary / text / danger；size = l(96rpx) / m(80rpx) / s(64rpx)；block；内置 loading + 自动禁用。
    -->
    <view
        class="app-btn"
        :class="btnClass"
        :hover-class="isDisabled ? 'none' : 'app-btn--press'"
        :hover-start-time="0"
        :hover-stay-time="80"
        @tap="handleTap"
    >
        <view v-if="loading" class="app-btn__spinner"></view>
        <text class="app-btn__label">{{ label }}</text>
    </view>
</template>

<script>
export default {
    name: 'AppButton',
    props: {
        label: { type: String, default: '' },
        type: { type: String, default: 'primary' },
        size: { type: String, default: 'l' },
        block: { type: Boolean, default: false },
        loading: { type: Boolean, default: false },
        disabled: { type: Boolean, default: false }
    },
    emits: ['tap'],
    computed: {
        isDisabled: function () {
            return this.disabled || this.loading
        },
        btnClass: function () {
            return [
                'app-btn--' + this.type,
                'app-btn--' + this.size,
                { 'app-btn--block': this.block, 'app-btn--disabled': this.isDisabled }
            ]
        }
    },
    methods: {
        handleTap: function () {
            if (this.isDisabled) {
                return
            }
            this.$emit('tap')
        }
    }
}
</script>

<style scoped lang="scss">
.app-btn {
    display: flex;
    flex-direction: row;
    align-items: center;
    justify-content: center;
    border-radius: var(--r-md);
    padding-left: var(--sp-8);
    padding-right: var(--sp-8);
    transition: transform var(--d-fast) var(--ease-std), opacity var(--d-fast) var(--ease-std),
        background-color var(--d-fast) var(--ease-std);
}

.app-btn--block {
    width: 100%;
}

/* 三档高度：l = 96rpx / m = 80rpx / s = 64rpx（DESIGN.md §8.1 C-01） */
.app-btn--l {
    height: 96rpx;
}

.app-btn--m {
    height: 80rpx;
}

.app-btn--s {
    height: 64rpx;
}

/* 按下反馈：统一使用 DESIGN.md §7.3 固定比例令牌 */
.app-btn--press {
    transform: scale(var(--press-scale));
    opacity: var(--press-opacity);
}

/* 类型 */
.app-btn--primary {
    background-color: var(--c-p-600);
}

.app-btn--secondary {
    background-color: var(--s-card);
    border: 1rpx solid var(--b-border);
}

.app-btn--text {
    background-color: transparent;
}

.app-btn--danger {
    background-color: var(--c-danger);
}

/* 禁用：用「凹陷底 + 次要文字」表达，不用透明度（DESIGN.md §2.1） */
.app-btn--disabled {
    background-color: var(--s-sunken);
    border: 1rpx solid var(--s-sunken);
}

/* 文字 */
.app-btn__label {
    font-size: var(--fs-btn-l);
    line-height: $lh-btn-l;
    font-weight: $fw-semibold;
    letter-spacing: 0;
}

.app-btn--m .app-btn__label,
.app-btn--s .app-btn__label {
    font-size: var(--fs-btn-m);
    line-height: $lh-btn-m;
    font-weight: $fw-medium;
}

.app-btn--primary .app-btn__label,
.app-btn--danger .app-btn__label {
    color: var(--t-inverse);
}

.app-btn--secondary .app-btn__label {
    color: var(--t-1);
}

.app-btn--text .app-btn__label {
    color: var(--t-link);
}

.app-btn--disabled .app-btn__label {
    color: var(--t-4);
}

/* 内置 loading：跟随 currentColor（任何底色上均可见）；旋转周期复用 §7 的 --d-breathe */
.app-btn__spinner {
    width: 30rpx;
    height: 30rpx;
    margin-right: var(--sp-3);
    border: 2rpx solid currentColor;
    border-top-color: transparent;
    border-radius: var(--r-full);
    animation: app-btn-spin var(--d-breathe) linear infinite;
}

.app-btn--primary .app-btn__spinner,
.app-btn--danger .app-btn__spinner {
    color: var(--t-inverse);
}

.app-btn--secondary .app-btn__spinner {
    color: var(--t-2);
}

.app-btn--text .app-btn__spinner {
    color: var(--t-link);
}

@keyframes app-btn-spin {
    from {
        transform: rotate(0deg);
    }
    to {
        transform: rotate(360deg);
    }
}
</style>
