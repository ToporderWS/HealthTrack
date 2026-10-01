<template>
    <!--
      C-03 AppInput（G13 表单项 + 即时校验提示）
      规格：label / unit / hint / error / maxlength / clearable / password（眼睛切换显隐）。
      八态：default（可输入）/ pressed（清除键按下）/ disabled（禁用）/ error（校验失败）
            / loading(N/A — 输入框自身无 loading 语义) / success(N/A — 成功由 Toast / 页面切换表达)
            / empty(N/A — 空输入即 default) / offline（由页面在提交前拦截，输入框保持可用）
    -->
    <view class="app-input" :class="{ 'app-input--disabled': disabled }">
        <view v-if="label" class="app-input__label-row">
            <text class="app-input__label">{{ label }}</text>
            <text v-if="required" class="app-input__required">*</text>
            <text v-if="unit" class="app-input__unit-label">{{ unit }}</text>
        </view>

        <view class="app-input__box" :class="{ 'app-input__box--error': !!error, 'app-input__box--focus': focused }">
            <input
                class="app-input__field"
                :value="displayValue"
                :type="inputType"
                :password="password && !visible"
                :disabled="disabled"
                :maxlength="maxlength"
                :placeholder="placeholder"
                :confirm-type="confirmType"
                :cursor-spacing="cursorSpacing"
                placeholder-style="color: var(--t-4)"
                @input="handleInput"
                @focus="handleFocus"
                @blur="handleBlur"
                @confirm="handleConfirm"
            />

            <text v-if="unit && unitInline" class="app-input__unit">{{ unit }}</text>

            <view
                v-if="clearable && hasValue && !disabled"
                class="app-input__action"
                hover-class="app-input__action--press"
                :hover-start-time="0"
                :hover-stay-time="80"
                @tap="handleClear"
            >
                <view class="app-input__clear"></view>
            </view>

            <!-- 密码显隐：纯 CSS 几何眼睛（不引入图标库；图标边长按 §10.4 例外取 px） -->
            <view
                v-if="password"
                class="app-input__action"
                hover-class="app-input__action--press"
                :hover-start-time="0"
                :hover-stay-time="80"
                @tap="toggleVisible"
            >
                <view class="app-input__eye">
                    <view class="app-input__eye-ball"></view>
                    <view v-if="!visible" class="app-input__eye-slash"></view>
                </view>
            </view>
        </view>

        <text v-if="error" class="app-input__error">{{ error }}</text>
        <text v-else-if="hint" class="app-input__hint">{{ hint }}</text>
    </view>
</template>

<script>
export default {
    name: 'AppInput',
    props: {
        /** 双向绑定值（v-model） */
        modelValue: { type: [String, Number], default: '' },
        label: { type: String, default: '' },
        placeholder: { type: String, default: '' },
        /** 单位（如 kg / cm / ml）；unitInline=true 时显示在输入框右侧 */
        unit: { type: String, default: '' },
        unitInline: { type: Boolean, default: true },
        /** 常驻提示（error 存在时被错误文案替代） */
        hint: { type: String, default: '' },
        /** 即时校验错误文案 */
        error: { type: String, default: '' },
        maxlength: { type: Number, default: 140 },
        clearable: { type: Boolean, default: false },
        password: { type: Boolean, default: false },
        disabled: { type: Boolean, default: false },
        required: { type: Boolean, default: false },
        /** text | digit | number | idcard —— 数值输入请用 digit */
        type: { type: String, default: 'text' },
        confirmType: { type: String, default: 'done' },
        cursorSpacing: { type: Number, default: 24 }
    },
    emits: ['update:modelValue', 'input', 'focus', 'blur', 'confirm'],
    data: function () {
        return {
            visible: false,
            focused: false
        }
    },
    computed: {
        displayValue: function () {
            return this.modelValue === null || this.modelValue === undefined ? '' : String(this.modelValue)
        },
        hasValue: function () {
            return this.displayValue.length > 0
        },
        inputType: function () {
            // 密码字段使用 text + password 属性（uni input 的 password 属性负责掩码）
            if (this.password) {
                return 'text'
            }
            return this.type
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
        },
        handleConfirm: function (event) {
            this.$emit('confirm', event && event.detail ? event.detail.value : '')
        },
        handleClear: function () {
            this.$emit('update:modelValue', '')
            this.$emit('input', '')
        },
        toggleVisible: function () {
            this.visible = !this.visible
        }
    }
}
</script>

<style scoped lang="scss">
.app-input {
    width: 100%;
}

.app-input__label-row {
    display: flex;
    flex-direction: row;
    align-items: center;
    margin-bottom: var(--sp-3);
}

.app-input__label {
    font-size: var(--fs-sub);
    line-height: $lh-sub;
    color: var(--t-2);
    letter-spacing: 0;
}

.app-input__required {
    font-size: var(--fs-sub);
    line-height: $lh-sub;
    color: var(--c-danger);
    margin-left: var(--sp-1);
}

.app-input__unit-label {
    font-size: var(--fs-caption);
    line-height: $lh-caption;
    color: var(--t-3);
    margin-left: var(--sp-2);
}

.app-input__box {
    display: flex;
    flex-direction: row;
    align-items: center;
    min-height: var(--tap-min);
    padding-left: var(--sp-5);
    border-radius: var(--r-sm);
    background-color: var(--s-card);
    border: 1rpx solid var(--b-border);
    transition: border-color var(--d-fast) var(--ease-std);
}

.app-input__box--focus {
    border: 1rpx solid var(--b-focus);
}

.app-input__box--error {
    border: 1rpx solid var(--c-danger);
}

.app-input--disabled .app-input__box {
    background-color: var(--s-sunken);
    border: 1rpx solid var(--s-sunken);
}

.app-input__field {
    flex: 1;
    height: var(--tap-min);
    font-size: var(--fs-body);
    color: var(--t-1);
    letter-spacing: 0;
    font-variant-numeric: tabular-nums;
}

.app-input--disabled .app-input__field {
    color: var(--t-4);
}

.app-input__unit {
    font-size: var(--fs-body);
    line-height: $lh-body;
    color: var(--t-3);
    margin-right: var(--sp-2);
}

/* 右侧动作热区 ≥ var(--tap-min)（图标边长按 §10.4 例外取 px） */
.app-input__action {
    width: var(--tap-min);
    height: var(--tap-min);
    display: flex;
    align-items: center;
    justify-content: center;
    transition: transform var(--d-fast) var(--ease-std), opacity var(--d-fast) var(--ease-std);
}

.app-input__action--press {
    transform: scale(var(--press-scale));
    opacity: var(--press-opacity);
}

/* 清除：两段 2px 线交叉成 × */
.app-input__clear {
    position: relative;
    width: 13px;
    height: 13px;
}

.app-input__clear::before,
.app-input__clear::after {
    content: '';
    position: absolute;
    left: 0;
    top: 5px;
    width: 13px;
    height: 2px;
    background-color: var(--t-4);
}

.app-input__clear::before {
    transform: rotate(45deg);
}

.app-input__clear::after {
    transform: rotate(-45deg);
}

/* 眼睛：椭圆轮廓 + 瞳孔 */
.app-input__eye {
    position: relative;
    width: 20px;
    height: 16px;
    display: flex;
    align-items: center;
    justify-content: center;
}

.app-input__eye-ball {
    width: 20px;
    height: 12px;
    border: 2px solid var(--t-3);
    border-radius: var(--r-full);
    display: flex;
    align-items: center;
    justify-content: center;
}

.app-input__eye-ball::after {
    content: '';
    width: 5px;
    height: 5px;
    border-radius: var(--r-full);
    background-color: var(--t-3);
}

.app-input__eye-slash {
    position: absolute;
    left: 0;
    top: 7px;
    width: 20px;
    height: 2px;
    background-color: var(--t-3);
    transform: rotate(-35deg);
}

.app-input__error {
    display: block;
    margin-top: var(--sp-2);
    font-size: var(--fs-caption);
    line-height: $lh-caption;
    color: var(--t-danger);
    letter-spacing: 0;
}

.app-input__hint {
    display: block;
    margin-top: var(--sp-2);
    font-size: var(--fs-caption);
    line-height: $lh-caption;
    color: var(--t-3);
    letter-spacing: 0;
}
</style>
