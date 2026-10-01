<template>
    <!--
      C-18 AppValidateBar（G8 软提示条 / G9 硬拦截条）
      规格：level = soft（黄，可继续保存）/ block（红，阻止保存）；
            文案固定「数值超出常见范围，请确认是否输错」（DESIGN.md §12，不得改写）。
      八态：default / error（block 态）/ disabled·loading·success·empty·pressed·offline —— **N/A**（纯提示条，无交互）。
      本批用途：SC-05 建档引导的数值越界提示（身高 / 体重 / 目标值）。
    -->
    <view v-if="visible" class="vbar" :class="'vbar--' + level">
        <view class="vbar__mark"></view>
        <text class="vbar__text">{{ message }}</text>
    </view>
</template>

<script>
import { RANGE_TEXT } from '../utils/validate'

export default {
    name: 'AppValidateBar',
    props: {
        visible: { type: Boolean, default: false },
        level: { type: String, default: 'soft' },
        /** 默认即 DESIGN.md §12 固定文案；如需覆盖，必须仍为中性技术文案 */
        text: { type: String, default: '' }
    },
    computed: {
        message: function () {
            return this.text ? this.text : RANGE_TEXT
        }
    }
}
</script>

<style scoped lang="scss">
.vbar {
    display: flex;
    flex-direction: row;
    align-items: flex-start;
    padding: var(--sp-4) var(--sp-5);
    border-radius: var(--r-sm);
}

.vbar--soft {
    background-color: var(--c-warning-bg);
}

.vbar--block {
    background-color: var(--c-danger-bg);
}

.vbar__mark {
    width: 8rpx;
    height: 8rpx;
    border-radius: var(--r-full);
    margin-top: var(--sp-3);
    margin-right: var(--sp-3);
}

.vbar--soft .vbar__mark {
    background-color: var(--c-warning);
}

.vbar--block .vbar__mark {
    background-color: var(--c-danger);
}

.vbar__text {
    flex: 1;
    font-size: var(--fs-caption);
    line-height: $lh-caption;
    letter-spacing: 0;
}

.vbar--soft .vbar__text {
    color: var(--c-warning);
}

.vbar--block .vbar__text {
    color: var(--t-danger);
}
</style>
