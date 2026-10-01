<template>
    <!--
      C-06 AppDatePicker（G13 表单项 · 封装 uni picker）
      规格：mode = date / datetime；**输出统一 `YYYY-MM-DD`（date）/ `YYYY-MM-DD HH:mm:ss`（datetime）**；
            默认当前时间（本组件仅在用户主动选择后回填，不自动写入）。
      平台差异（P-2 最小兼容补丁）：uni 的 picker **没有** `datetime` 这个 mode —— H5 运行时的
            mode 枚举只有 selector / multiSelector / time / date，未匹配的 mode 会让可选项数组为空。
            ⇒ `datetime` 统一由「日期 picker + 时间 picker」同行组合实现，
              **输出契约与 props / emit 契约均不变**。
      八态：default / pressed（按下）/ disabled / error / loading(N/A) / success(N/A) / empty（未选择 → placeholder）
            / offline（由页面在提交前拦截）
      用途：SC-05 建档引导「出生日期」（mode=date）；SC-08「入睡 / 起床时间」「测量时间」（mode=datetime）。
    -->
    <view class="app-date">
        <view v-if="label" class="app-date__label-row">
            <text class="app-date__label">{{ label }}</text>
            <text v-if="required" class="app-date__required">*</text>
        </view>

        <!--
          `datetime` 兼容分支（P-2 最小兼容补丁）：
          H5 / 小程序的 picker **不支持** `mode="datetime"` —— uni-h5 的 mode 枚举只有
          selector / multiSelector / time / date，未匹配的 mode 会让可选项数组返回空。
          ⇒ 统一拆为「日期 picker + 时间 picker」同行组合，合并后仍输出
          `YYYY-MM-DD HH:mm:ss`（输出契约不变）。
        -->
        <view
            v-if="isDatetime"
            class="app-date__box app-date__box--split"
            :class="{ 'app-date__box--error': !!error, 'app-date__box--disabled': disabled }"
        >
            <view class="app-date__part app-date__part--date">
                <!--
                  `fields="day"` 是**刻意**传的：
                  uni-h5 对 `mode="date"` 在桌面尺寸（window ≥ 500×500）会改用**原生 `<input type="date">`**
                  分支（无弹层、且点击点会被遮罩覆盖），与同一行的「时间半区」交互不一致。
                  显式给 `fields="day"` 可让 H5 恒走「年月日三列滚轮」路径，两端行为一致；
                  而 App / 小程序 的 `fields` 默认值本来就是 `day` ⇒ 对它们**零影响**。
                -->
                <picker
                    mode="date"
                    fields="day"
                    :value="datePickerValue"
                    :start="dateBoundStart"
                    :end="dateBoundEnd"
                    :disabled="disabled"
                    @change="handleDateChange"
                >
                    <view
                        class="app-date__part-inner"
                        :hover-class="disabled ? 'none' : 'app-date__part-inner--press'"
                        :hover-start-time="0"
                        :hover-stay-time="80"
                    >
                        <text class="app-date__value" :class="{ 'app-date__value--placeholder': !datePart }">
                            {{ datePart ? datePart : placeholder }}
                        </text>
                    </view>
                </picker>
            </view>
            <view class="app-date__part app-date__part--time">
                <picker
                    mode="time"
                    :value="timePickerValue"
                    :disabled="disabled"
                    @change="handleTimeChange"
                >
                    <view
                        class="app-date__part-inner"
                        :hover-class="disabled ? 'none' : 'app-date__part-inner--press'"
                        :hover-start-time="0"
                        :hover-stay-time="80"
                    >
                        <text class="app-date__value" :class="{ 'app-date__value--placeholder': !timePart }">
                            {{ timePart ? timePart : timePlaceholder }}
                        </text>
                    </view>
                </picker>
            </view>
            <view class="app-date__caret"></view>
        </view>

        <picker
            v-else
            :mode="mode"
            :value="pickerValue"
            :start="start"
            :end="end"
            :disabled="disabled"
            @change="handleChange"
        >
            <view
                class="app-date__box"
                :class="{ 'app-date__box--error': !!error, 'app-date__box--disabled': disabled }"
                :hover-class="disabled ? 'none' : 'app-date__box--press'"
                :hover-start-time="0"
                :hover-stay-time="80"
            >
                <text class="app-date__value" :class="{ 'app-date__value--placeholder': !display }">
                    {{ display ? display : placeholder }}
                </text>
                <view class="app-date__caret"></view>
            </view>
        </picker>

        <text v-if="error" class="app-date__error">{{ error }}</text>
        <text v-else-if="hint" class="app-date__hint">{{ hint }}</text>
    </view>
</template>

<script>
import { pad2, todayString } from '../utils/validate'

/** 时间半区未选择时的占位（中性技术占位，不代表任何取值） */
const TIME_PLACEHOLDER = '--:--'

/**
 * 当前墙上时间 `HH:mm`（口径：本地墙上时间，S1-D D-4）。
 * 仅用于两处：① 打开时间 picker 时的默认定位；② 用户只选了日期时补齐缺失的时间半区
 * （与组件既有约定「默认当前时间」一致，且选完即回填显示，用户可立即看到并继续调整）。
 */
function nowTime() {
    const d = new Date()
    return pad2(d.getHours()) + ':' + pad2(d.getMinutes())
}

export default {
    name: 'AppDatePicker',
    props: {
        /** date 模式：`YYYY-MM-DD`；datetime 模式：`YYYY-MM-DD HH:mm:ss` */
        modelValue: { type: String, default: '' },
        mode: { type: String, default: 'date' },
        label: { type: String, default: '' },
        placeholder: { type: String, default: '请选择日期' },
        start: { type: String, default: '' },
        end: { type: String, default: '' },
        error: { type: String, default: '' },
        hint: { type: String, default: '' },
        disabled: { type: Boolean, default: false },
        required: { type: Boolean, default: false }
    },
    emits: ['update:modelValue', 'change'],
    computed: {
        display: function () {
            return this.modelValue ? String(this.modelValue) : ''
        },
        pickerValue: function () {
            // uni picker 需要非空字符串；未选择时回落到今天（仅用于打开时的默认定位）
            if (this.modelValue) {
                return String(this.modelValue)
            }
            const d = new Date()
            return String(d.getFullYear()) + '-' + pad2(d.getMonth() + 1) + '-' + pad2(d.getDate())
        },

        /** `datetime`（拆分模式）判定；`date` 走原单 picker 路径，行为完全不变 */
        isDatetime: function () {
            return this.mode === 'datetime'
        },
        /** 日期半区取值 `YYYY-MM-DD`（从完整值前 10 位切出） */
        datePart: function () {
            const v = this.modelValue ? String(this.modelValue) : ''
            return v ? v.slice(0, 10) : ''
        },
        /** 时间半区取值 `HH:mm`（从完整值第 11~16 位切出） */
        timePart: function () {
            const v = this.modelValue ? String(this.modelValue) : ''
            return v.length >= 16 ? v.slice(11, 16) : ''
        },
        /** 日期 picker 的 value（未选择 → 今天，仅用于打开时的默认定位） */
        datePickerValue: function () {
            return this.datePart ? this.datePart : todayString()
        },
        /** 时间 picker 的 value（未选择 → 当前时刻，仅用于打开时的默认定位） */
        timePickerValue: function () {
            return this.timePart ? this.timePart : nowTime()
        },
        /** 日期上下界（统一裁剪为 `YYYY-MM-DD`，兼容未来传入完整 datetime 的调用方） */
        dateBoundStart: function () {
            return this.start ? String(this.start).slice(0, 10) : ''
        },
        dateBoundEnd: function () {
            return this.end ? String(this.end).slice(0, 10) : ''
        },
        timePlaceholder: function () {
            return TIME_PLACEHOLDER
        }
    },
    methods: {
        /** 单 picker 路径（`date` 模式）：直接透传 `YYYY-MM-DD` */
        handleChange: function (event) {
            const value = event && event.detail ? event.detail.value : ''
            if (!value) {
                return
            }
            if (this.mode === 'datetime') {
                // 兜底保留：若某平台恢复原生 datetime（返回 `YYYY-MM-DD HH:mm`），仍补齐秒
                const normalized = String(value).length === 16 ? String(value) + ':00' : String(value)
                this.$emit('update:modelValue', normalized)
                this.$emit('change', normalized)
                return
            }
            this.$emit('update:modelValue', String(value))
            this.$emit('change', String(value))
        },

        /** 日期半区变更 → 与现有（或默认）时间半区合并后输出 */
        handleDateChange: function (event) {
            const value = event && event.detail ? event.detail.value : ''
            if (!value) {
                return
            }
            const date = String(value).slice(0, 10)
            this.emitDatetime(date, this.timePart ? this.timePart : nowTime())
        },

        /** 时间半区变更 → 与现有（或默认）日期半区合并后输出 */
        handleTimeChange: function (event) {
            const value = event && event.detail ? event.detail.value : ''
            if (!value) {
                return
            }
            const time = String(value).slice(0, 5)
            this.emitDatetime(this.datePart ? this.datePart : todayString(), time)
        },

        /** 合并输出：恒为 `YYYY-MM-DD HH:mm:ss`（输出契约不变） */
        emitDatetime: function (date, time) {
            const normalized = date + ' ' + time + ':00'
            this.$emit('update:modelValue', normalized)
            this.$emit('change', normalized)
        }
    }
}
</script>

<style scoped lang="scss">
.app-date {
    width: 100%;
}

.app-date__label-row {
    display: flex;
    flex-direction: row;
    align-items: center;
    margin-bottom: var(--sp-3);
}

.app-date__label {
    font-size: var(--fs-sub);
    line-height: $lh-sub;
    color: var(--t-2);
    letter-spacing: 0;
}

.app-date__required {
    font-size: var(--fs-sub);
    line-height: $lh-sub;
    color: var(--c-danger);
    margin-left: var(--sp-1);
}

.app-date__box {
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

.app-date__box--press {
    transform: scale(var(--press-scale));
    opacity: var(--press-opacity);
}

.app-date__box--error {
    border: 1rpx solid var(--c-danger);
}

.app-date__box--disabled {
    background-color: var(--s-sunken);
    border: 1rpx solid var(--s-sunken);
}

/* ── datetime 拆分模式（P-2 兼容补丁）：日期 + 时间 同行，共用同一视觉盒 ── */
.app-date__box--split {
    padding-left: 0;
    padding-right: var(--sp-5);
}

.app-date__part--date {
    flex: 1;
}

.app-date__part--time {
    flex: 0 0 auto;
}

.app-date__part--time .app-date__value {
    flex: 0 0 auto;
}

.app-date__part-inner {
    display: flex;
    flex-direction: row;
    align-items: center;
    min-height: var(--tap-min);
    transition: transform var(--d-fast) var(--ease-std), opacity var(--d-fast) var(--ease-std);
}

.app-date__part--date .app-date__part-inner {
    padding-left: var(--sp-5);
    padding-right: var(--sp-3);
}

.app-date__part--time .app-date__part-inner {
    padding-left: var(--sp-3);
    padding-right: var(--sp-3);
}

.app-date__part-inner--press {
    transform: scale(var(--press-scale));
    opacity: var(--press-opacity);
}

.app-date__value {
    flex: 1;
    font-size: var(--fs-body);
    line-height: $lh-body;
    color: var(--t-1);
    letter-spacing: 0;
    font-variant-numeric: tabular-nums;
}

.app-date__value--placeholder {
    color: var(--t-4);
}

/* 右侧指示（图标边长按 §10.4 例外取 px） */
.app-date__caret {
    width: 9px;
    height: 9px;
    border-right: 2px solid var(--t-3);
    border-bottom: 2px solid var(--t-3);
    transform: rotate(45deg);
    margin-left: var(--sp-3);
}

.app-date__error {
    display: block;
    margin-top: var(--sp-2);
    font-size: var(--fs-caption);
    line-height: $lh-caption;
    color: var(--t-danger);
    letter-spacing: 0;
}

.app-date__hint {
    display: block;
    margin-top: var(--sp-2);
    font-size: var(--fs-caption);
    line-height: $lh-caption;
    color: var(--t-3);
    letter-spacing: 0;
}
</style>
