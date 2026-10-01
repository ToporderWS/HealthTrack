<template>
    <!--
      C-04 AppTextarea（G13 表单项 —— 多行文本）
      规格（DESIGN.md §8.2）：**多行 + 字数计数（`已填 N / 上限 M`）**。
      设计依据：S1-C SC-17 ⑦「健康背景三字段（多行文本，各带字数上限）」；
               S1-B §14.2「≤2000 字（纯文本，不富文本）」为本组件的默认上限。

      八态（DESIGN.md §8 规则，逐项说明；不适用的**在组件内注明理由**，不硬凑 UI）：
        default  → 可输入；
        pressed  → **N/A**：输入框自身无按压语义（按压反馈由页面容器承担）；
        disabled → 只读展示（背景下沉、文字降级为 --t-4）；
        error    → 校验失败（边框转 --c-danger + 下方错误文案）；
        loading  → **N/A**：多行文本装载没有"进行中"语义（提交中的 loading 由提交按钮承载）；
        success  → **N/A**：成功由 Toast / 页面切换表达，输入框不自我宣称成功；
        empty    → **N/A**：空输入即 default（计数显示「已填 0 / 上限 M」）；
        offline  → **由页面在提交前拦截**，本组件保持可输入（与 C-03 AppInput 同一处置口径）。
    -->
    <view class="app-textarea" :class="{ 'app-textarea--disabled': disabled }">
        <view v-if="label" class="app-textarea__label-row">
            <text class="app-textarea__label">{{ label }}</text>
            <text v-if="required" class="app-textarea__required">*</text>
        </view>

        <view
            class="app-textarea__box"
            :class="{ 'app-textarea__box--error': !!error, 'app-textarea__box--focus': focused }"
        >
            <textarea
                class="app-textarea__field"
                :value="displayValue"
                :disabled="disabled"
                :maxlength="maxlength"
                :placeholder="placeholder"
                :cursor-spacing="cursorSpacing"
                :adjust-position="true"
                placeholder-style="color: var(--t-4)"
                @input="handleInput"
                @focus="handleFocus"
                @blur="handleBlur"
            />
        </view>

        <view class="app-textarea__foot">
            <text v-if="error" class="app-textarea__error">{{ error }}</text>
            <text v-else-if="hint" class="app-textarea__hint">{{ hint }}</text>
            <!-- 占位：无错误也无提示时仍占一行，避免计数在有无错误之间跳动 -->
            <text v-else class="app-textarea__hint"></text>
            <text class="app-textarea__count">{{ countText }}</text>
        </view>
    </view>
</template>

<script>
export default {
    name: 'AppTextarea',
    props: {
        /** 双向绑定值（v-model） */
        modelValue: { type: [String, Number], default: '' },
        label: { type: String, default: '' },
        placeholder: { type: String, default: '' },
        /** 常驻提示（error 存在时被错误文案替代） */
        hint: { type: String, default: '' },
        /** 即时校验错误文案 */
        error: { type: String, default: '' },
        /** 字数上限（S1-B §14.2：健康文本字段 ≤2000 字） */
        maxlength: { type: Number, default: 2000 },
        disabled: { type: Boolean, default: false },
        required: { type: Boolean, default: false },
        cursorSpacing: { type: Number, default: 24 }
    },
    emits: ['update:modelValue', 'input', 'focus', 'blur'],
    data: function () {
        return {
            focused: false
        }
    },
    computed: {
        displayValue: function () {
            return this.modelValue === null || this.modelValue === undefined ? '' : String(this.modelValue)
        },
        /** 规格固定文案：`已填 N / 上限 M`（DESIGN.md §8.2 逐字） */
        countText: function () {
            return '已填 ' + this.displayValue.length + ' / 上限 ' + this.maxlength
        }
    },
    methods: {
        handleInput: function (event) {
            const value = event && event.detail ? event.detail.value : ''
            this.$emit('update:modelValue', value)
            this.$emit('input', value)
        },
        handleFocus: function () {
            this.focused = true
            this.$emit('focus')
        },
        handleBlur: function () {
            this.focused = false
            this.$emit('blur')
        }
    }
}
</script>

<style scoped lang="scss">
.app-textarea {
    width: 100%;
}

.app-textarea__label-row {
    display: flex;
    flex-direction: row;
    align-items: center;
    margin-bottom: var(--sp-3);
}

.app-textarea__label {
    font-size: var(--fs-sub);
    line-height: $lh-sub;
    color: var(--t-2);
    letter-spacing: 0;
}

.app-textarea__required {
    font-size: var(--fs-sub);
    line-height: $lh-sub;
    color: var(--c-danger);
    margin-left: var(--sp-1);
}

.app-textarea__box {
    padding: var(--sp-4) var(--sp-5);
    border-radius: var(--r-sm);
    background-color: var(--s-card);
    border: 1rpx solid var(--b-border);
    transition: border-color var(--d-fast) var(--ease-std);
}

.app-textarea__box--focus {
    border: 1rpx solid var(--b-focus);
}

.app-textarea__box--error {
    border: 1rpx solid var(--c-danger);
}

.app-textarea--disabled .app-textarea__box {
    background-color: var(--s-sunken);
    border: 1rpx solid var(--s-sunken);
}

/* 多行输入区：高度由 --tap-min 推导（不写裸高度值） */
.app-textarea__field {
    width: 100%;
    height: calc(var(--tap-min) * 4);
    font-size: var(--fs-body);
    line-height: $lh-body;
    color: var(--t-1);
    letter-spacing: 0;
}

.app-textarea--disabled .app-textarea__field {
    color: var(--t-4);
}

/* 底部：左提示 / 右计数 —— 两行结构对长提示更稳（提示不与计数抢同一行） */
.app-textarea__foot {
    display: flex;
    flex-direction: row;
    align-items: flex-start;
    justify-content: space-between;
    margin-top: var(--sp-2);
}

.app-textarea__error {
    flex: 1;
    font-size: var(--fs-caption);
    line-height: $lh-caption;
    color: var(--t-danger);
    letter-spacing: 0;
}

.app-textarea__hint {
    flex: 1;
    font-size: var(--fs-caption);
    line-height: $lh-caption;
    color: var(--t-3);
    letter-spacing: 0;
}

.app-textarea__count {
    flex-shrink: 0;
    padding-left: var(--sp-4);
    font-size: var(--fs-caption);
    line-height: $lh-caption;
    color: var(--t-3);
    letter-spacing: 0;
    font-variant-numeric: tabular-nums;
}
</style>
