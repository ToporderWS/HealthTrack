<template>
    <!--
      C-19 AppSwitch（开关；DESIGN.md §8.2 已登记）
      规格：开关；**变化立即生效 + Toast**。

      ★ 职责边界（"立即生效 + Toast" 落在哪一层）：
        本组件**只负责把用户意图交出去**（`update:modelValue` + `change`），
        「立即生效」= 宿主页收到 `change` 后落本地配置；「Toast」由宿主页调用 C-13 轻提示
        （`AppToast` 是**页面级宿主**，组件内无法自持）⇒ 组件内**不弹 Toast**，避免
        出现无人接管的提示或重复提示。

      八态（DESIGN.md §8 总则）：
        default / pressed（按下 → 轨道 scale + opacity，`--d-fast`）/ disabled（不可点、用"凹陷底 + 禁用色"表达，不用透明度）
        loading · error · success —— **N/A**：开关本身不承载请求与校验结果，
          其结果由宿主页以 Toast / 说明文本表达（与 §8 "不为凑状态造 UI" 一致）
        empty —— **N/A**：开关没有"无内容"语义（`modelValue` 是布尔）
        offline —— **N/A**：提醒是**纯本地能力**，离线完全可用（S1-C SC-14 ⑭）

      用途（S3-6）：SC-14 「全部提醒」全局总开关 + 每条提醒的单条开关。

      颜色取值（全部为已登记 Token，见 DESIGN.md §2.3 / §2.4）：
        轨道 关 = `--s-sunken` + 1rpx `--b-border`；
        轨道 开 = `--c-success-bg`（§2.3 已登记用途："开关已开轨道"）+ 1rpx `--c-success`（§2.3 已登记用途含"开关已开"）
        —— 只加"边框色差"而**不新增任何色值**，否则浅绿底与浅灰底亮度接近，开/关难以分辨。
    -->
    <view
        class="sw"
        :class="{ 'sw--disabled': disabled }"
        :hover-class="hoverClass"
        :hover-start-time="0"
        :hover-stay-time="80"
        @tap="handleTap"
    >
        <view class="sw__track" :class="{ 'sw__track--on': isOn }">
            <view class="sw__knob" :class="{ 'sw__knob--on': isOn }"></view>
        </view>
    </view>
</template>

<script>
export default {
    name: 'AppSwitch',
    props: {
        /** 开关值（v-model） */
        modelValue: { type: Boolean, default: false },
        /** 不可点（呈禁用观感且**不派发任何事件**） */
        disabled: { type: Boolean, default: false }
    },
    emits: ['update:modelValue', 'change'],
    computed: {
        isOn: function () {
            return this.modelValue === true
        },
        hoverClass: function () {
            return this.disabled ? 'none' : 'sw--press'
        }
    },
    methods: {
        handleTap: function () {
            // 禁用态不派发事件：宿主页无需再自行判一次（与 §八态 disabled 的口径一致）
            if (this.disabled) {
                return
            }
            const next = !this.isOn
            this.$emit('update:modelValue', next)
            this.$emit('change', next)
        }
    }
}
</script>

<style scoped lang="scss">
/* 外层 = 触摸区（保证 ≥ --tap-min，满足 DESIGN.md §4 的最小触摸目标） */
.sw {
    display: flex;
    flex-direction: row;
    align-items: center;
    justify-content: center;
    min-width: var(--tap-min);
    min-height: var(--tap-min);
}

/* 轨道 */
.sw__track {
    width: 88rpx;
    height: 48rpx;
    padding: var(--sp-2);
    border-radius: var(--r-full);
    border: 1rpx solid var(--b-border);
    background-color: var(--s-sunken);
    display: flex;
    flex-direction: row;
    align-items: center;
    transition: background-color var(--d-fast) var(--ease-std),
        border-color var(--d-fast) var(--ease-std),
        transform var(--d-fast) var(--ease-std),
        opacity var(--d-fast) var(--ease-std);
}

.sw__track--on {
    background-color: var(--c-success-bg);
    border-color: var(--c-success);
}

/* 按下反馈（DESIGN.md §7①：scale + opacity，时长 --d-fast） */
.sw--press .sw__track {
    transform: scale(var(--press-scale));
    opacity: var(--press-opacity);
}

/* 滑块 */
.sw__knob {
    width: 32rpx;
    height: 32rpx;
    border-radius: var(--r-full);
    background-color: var(--c-n-0);
    border: 1rpx solid var(--b-border);
    transition: transform var(--d-base) var(--ease-std),
        border-color var(--d-base) var(--ease-std);
}

/* 滑动距离 = 轨道宽 − 左右内边距 − 滑块宽 = 88 − 8 − 8 − 32 = 40rpx */
.sw__knob--on {
    transform: translateX(40rpx);
    border-color: var(--c-success);
}

/* 禁用：凹陷底 + 禁用色（不透明度表达在 §2.1 明确不用于禁用态） */
.sw--disabled .sw__track {
    background-color: var(--s-sunken);
    border-color: var(--b-line);
}

.sw--disabled .sw__knob {
    background-color: var(--c-n-200);
    border-color: var(--b-line);
}
</style>
