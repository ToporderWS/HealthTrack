<template>
    <!--
      C-05 AppSelect（G13 表单项 · 底部抽屉单选）
      数据源约定：`R-08` 字典（性别 / 血型 / 测量时机 / 运动类型 / 强度）—— 由使用方以 options 传入。
      八态：default / pressed（选中项按下）/ disabled / error / empty（无选项 → 显示提示行）
            / loading(N/A) / success(N/A) / offline（由页面在提交前拦截）
      说明：抽屉为组件内置（与 C-12 AppModal 视觉一致但**不改变其契约**，避免为选择器额外扩 mode）。
    -->
    <view class="app-select">
        <view v-if="label" class="app-select__label-row">
            <text class="app-select__label">{{ label }}</text>
            <text v-if="required" class="app-select__required">*</text>
        </view>

        <view
            class="app-select__box"
            :class="{ 'app-select__box--error': !!error, 'app-select__box--disabled': disabled }"
            :hover-class="disabled ? 'none' : 'app-select__box--press'"
            :hover-start-time="0"
            :hover-stay-time="80"
            @tap="open"
        >
            <text class="app-select__value" :class="{ 'app-select__value--placeholder': !selectedLabel }">
                {{ selectedLabel ? selectedLabel : placeholder }}
            </text>
            <view class="app-select__caret"></view>
        </view>

        <text v-if="error" class="app-select__error">{{ error }}</text>
        <text v-else-if="hint" class="app-select__hint">{{ hint }}</text>

        <!-- 底部抽屉 -->
        <view v-if="visible" class="drawer">
            <view class="drawer__mask" @tap="handleMask"></view>
            <view class="drawer__panel">
                <view class="drawer__head">
                    <text class="drawer__title">{{ title || label || '请选择' }}</text>
                </view>

                <view v-if="!options || options.length === 0" class="drawer__empty">
                    <text class="drawer__empty-text">暂无可选项</text>
                </view>

                <scroll-view v-else class="drawer__list" scroll-y>
                    <view
                        v-for="(item, index) in options"
                        :key="item.value !== undefined ? item.value : index"
                        class="drawer__row"
                        :class="{ 'drawer__row--active': isSelected(item) }"
                        hover-class="drawer__row--press"
                        :hover-start-time="0"
                        :hover-stay-time="80"
                        @tap="pick(item)"
                    >
                        <text class="drawer__row-text" :class="{ 'drawer__row-text--active': isSelected(item) }">
                            {{ item.label }}
                        </text>
                        <view v-if="isSelected(item)" class="drawer__check"></view>
                    </view>
                </scroll-view>

                <view class="drawer__foot">
                    <view class="drawer__cancel" hover-class="drawer__cancel--press" @tap="close">
                        <text class="drawer__cancel-text">{{ cancelText }}</text>
                    </view>
                </view>
                <view class="drawer__safe"></view>
            </view>
        </view>
    </view>
</template>

<script>
export default {
    name: 'AppSelect',
    props: {
        modelValue: { type: [String, Number], default: '' },
        label: { type: String, default: '' },
        title: { type: String, default: '' },
        placeholder: { type: String, default: '请选择' },
        options: { type: Array, default: function () { return [] } },
        cancelText: { type: String, default: '取消' },
        error: { type: String, default: '' },
        hint: { type: String, default: '' },
        disabled: { type: Boolean, default: false },
        required: { type: Boolean, default: false }
    },
    emits: ['update:modelValue', 'change'],
    data: function () {
        return {
            visible: false
        }
    },
    computed: {
        selectedLabel: function () {
            const list = this.options || []
            for (let i = 0; i < list.length; i++) {
                if (String(list[i].value) === String(this.modelValue)) {
                    return list[i].label
                }
            }
            return ''
        }
    },
    methods: {
        open: function () {
            if (this.disabled) {
                return
            }
            this.visible = true
        },
        close: function () {
            this.visible = false
        },
        handleMask: function () {
            this.close()
        },
        isSelected: function (item) {
            return String(item.value) === String(this.modelValue)
        },
        pick: function (item) {
            this.$emit('update:modelValue', item.value)
            this.$emit('change', item.value)
            this.close()
        }
    }
}
</script>

<style scoped lang="scss">
.app-select {
    width: 100%;
}

.app-select__label-row {
    display: flex;
    flex-direction: row;
    align-items: center;
    margin-bottom: var(--sp-3);
}

.app-select__label {
    font-size: var(--fs-sub);
    line-height: $lh-sub;
    color: var(--t-2);
    letter-spacing: 0;
}

.app-select__required {
    font-size: var(--fs-sub);
    line-height: $lh-sub;
    color: var(--c-danger);
    margin-left: var(--sp-1);
}

.app-select__box {
    display: flex;
    flex-direction: row;
    align-items: center;
    justify-content: space-between;
    min-height: var(--tap-min);
    padding-left: var(--sp-5);
    padding-right: var(--sp-5);
    border-radius: var(--r-sm);
    background-color: var(--s-card);
    border: 1rpx solid var(--b-border);
    transition: transform var(--d-fast) var(--ease-std), opacity var(--d-fast) var(--ease-std);
}

.app-select__box--press {
    transform: scale(var(--press-scale));
    opacity: var(--press-opacity);
}

.app-select__box--error {
    border: 1rpx solid var(--c-danger);
}

.app-select__box--disabled {
    background-color: var(--s-sunken);
    border: 1rpx solid var(--s-sunken);
}

.app-select__value {
    flex: 1;
    font-size: var(--fs-body);
    line-height: $lh-body;
    color: var(--t-1);
    letter-spacing: 0;
}

.app-select__value--placeholder {
    color: var(--t-4);
}

/* 下拉指示（图标边长按 §10.4 例外取 px） */
.app-select__caret {
    width: 9px;
    height: 9px;
    border-right: 2px solid var(--t-3);
    border-bottom: 2px solid var(--t-3);
    transform: rotate(45deg);
    margin-left: var(--sp-3);
}

.app-select__error {
    display: block;
    margin-top: var(--sp-2);
    font-size: var(--fs-caption);
    line-height: $lh-caption;
    color: var(--t-danger);
    letter-spacing: 0;
}

.app-select__hint {
    display: block;
    margin-top: var(--sp-2);
    font-size: var(--fs-caption);
    line-height: $lh-caption;
    color: var(--t-3);
    letter-spacing: 0;
}

/* ── 底部抽屉 ── */
.drawer {
    position: fixed;
    left: 0;
    right: 0;
    top: 0;
    bottom: 0;
    z-index: 80;
}

.drawer__mask {
    position: absolute;
    left: 0;
    right: 0;
    top: 0;
    bottom: 0;
    background-color: var(--s-overlay);
}

.drawer__panel {
    position: absolute;
    left: 0;
    right: 0;
    bottom: 0;
    background-color: var(--s-card);
    border-radius: var(--r-xl) var(--r-xl) 0 0;
    padding: var(--sp-6) var(--card-pad) 0 var(--card-pad);
    animation: drawer-up var(--d-slow) var(--ease-out);
}

.drawer__head {
    display: flex;
    flex-direction: row;
    align-items: center;
    justify-content: center;
    padding-bottom: var(--sp-4);
}

.drawer__title {
    font-size: var(--fs-h3);
    line-height: $lh-h3;
    font-weight: $fw-medium;
    color: var(--t-1);
    letter-spacing: 0;
}

.drawer__list {
    max-height: 600rpx;
}

.drawer__row {
    display: flex;
    flex-direction: row;
    align-items: center;
    justify-content: space-between;
    min-height: var(--row-h);
    padding: var(--row-pad-y) 0;
    border-bottom: 1rpx solid var(--b-line);
    transition: background-color var(--d-row) var(--ease-std);
}

.drawer__row--press {
    background-color: var(--c-n-100);
}

.drawer__row-text {
    font-size: var(--fs-body);
    line-height: $lh-body;
    color: var(--t-1);
    letter-spacing: 0;
}

.drawer__row-text--active {
    color: var(--c-p-600);
    font-weight: $fw-medium;
}

/* 选中勾：两段边框旋转成 ✓ */
.drawer__check {
    width: 7px;
    height: 12px;
    border-right: 2px solid var(--c-p-600);
    border-bottom: 2px solid var(--c-p-600);
    transform: rotate(45deg);
}

.drawer__empty {
    padding: var(--sp-9) 0;
    display: flex;
    justify-content: center;
}

.drawer__empty-text {
    font-size: var(--fs-sub);
    line-height: $lh-sub;
    color: var(--t-3);
}

.drawer__foot {
    padding: var(--sp-4) 0 var(--sp-5) 0;
}

.drawer__cancel {
    height: var(--tap-min);
    display: flex;
    align-items: center;
    justify-content: center;
    border-radius: var(--r-md);
    background-color: var(--s-sunken);
}

.drawer__cancel--press {
    opacity: var(--press-opacity);
}

.drawer__cancel-text {
    font-size: var(--fs-btn-m);
    line-height: $lh-btn-m;
    font-weight: $fw-medium;
    color: var(--t-2);
}

.drawer__safe {
    height: var(--safe-b);
}

@keyframes drawer-up {
    from {
        transform: translateY(100%);
    }
    to {
        transform: translateY(0);
    }
}
</style>
