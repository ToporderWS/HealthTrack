<template>
    <!--
      C-30 NotifyPermissionBar（通知权限引导条；DESIGN.md §8.3 已登记）
      规格：通知权限引导条（`--c-warning-bg` + 「去设置」）。

      依据：S1-C §SC-14 ②（黄，未授权时）「通知权限未开启，提醒无法生效」[去设置]；
            §SC-14 ⑫「权限被拒 → 顶部黄条**常驻**」。

      ★ 「去设置」在部分平台没有落脚点，处理方式（**诚实降级，不假装能跳**）：
        H5 / 小程序内**不存在**系统通知设置页 ⇒ 由页面调用 `utils/notify.js#openSystemSettings()`
        取回真实结果；失败时页面给中性提示，**本组件不自行跳转、不伪装成功**。
        组件只把点击意图交出去（`action` 事件），跳转与提示均属宿主页职责。

      八态（DESIGN.md §8 总则）：
        default（未授权时显示）/ pressed（「去设置」按下 → scale + opacity，`--d-fast`）
        disabled —— 「去设置」不可用（如宿主判定无可跳转目标）时的观感
        empty —— **N/A**：本组件本身就是"条件渲染的空位"，`visible=false` 时整个不渲染
        loading —— **N/A**：本组件不承载异步请求（能力判定为同步读取）
        error / success / offline —— **N/A**：权限状态由宿主页判定并以文案表达；
          提醒是纯本地能力，离线完全可用（S1-C SC-14 ⑭）⇒ 无离线态

      颜色取值（DESIGN.md §2.3，**不新增色值**）：
        底 = `--c-warning-bg`（§2.3 登记用途："软提示条底 / 通知权限引导条底"）；
        文字与图标 = `--c-warning`（§2.3 登记用途："软提示 / 权限未开 / 提醒'未生效'"）。
    -->
    <view v-if="visible" class="npb">
        <!-- 图标：纯 CSS 几何（圆 + 竖条），与全工程"几何构成、不用 emoji、不引图标库"一致 -->
        <view class="npb__icon">
            <view class="npb__g npb__g--a"></view>
            <view class="npb__g npb__g--b"></view>
        </view>

        <text class="npb__text">{{ text }}</text>

        <view
            class="npb__action"
            :class="{ 'npb__action--disabled': disabled }"
            :hover-class="disabled ? 'none' : 'npb__action--press'"
            :hover-start-time="0"
            :hover-stay-time="80"
            @tap="handleAction"
        >
            <text class="npb__action-text">{{ actionText }}</text>
        </view>
    </view>
</template>

<script>
export default {
    name: 'NotifyPermissionBar',
    props: {
        /** 是否显示（权限未开 / 能力不可用 / 通知未生效时显示，由宿主页判定） */
        visible: { type: Boolean, default: false },
        /** 主文案（逐字取自 S1-C SC-14 ②，宿主页可覆盖） */
        text: { type: String, default: '通知权限未开启，提醒无法生效' },
        /** 右侧动作文案（S1-C SC-14 ② 冻结为「去设置」） */
        actionText: { type: String, default: '去设置' },
        /** 动作不可用（如宿主判定当前平台无可跳转的设置页） */
        disabled: { type: Boolean, default: false }
    },
    emits: ['action'],
    methods: {
        handleAction: function () {
            if (this.disabled) {
                return
            }
            this.$emit('action')
        }
    }
}
</script>

<style scoped lang="scss">
.npb {
    display: flex;
    flex-direction: row;
    align-items: center;
    min-height: var(--tap-min);
    padding: var(--sp-4) var(--card-pad);
    border-radius: var(--r-md);
    background-color: var(--c-warning-bg);
}

/* ── 图标：圆 + 竖条（警示几何） ── */
.npb__icon {
    width: 32rpx;
    height: 32rpx;
    border-radius: var(--r-full);
    border: 2rpx solid var(--c-warning);
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
    margin-right: var(--sp-3);
}

.npb__g {
    background-color: var(--c-warning);
    border-radius: var(--r-full);
}

.npb__g--a {
    width: 4rpx;
    height: 12rpx;
}

.npb__g--b {
    width: 4rpx;
    height: 4rpx;
    margin-top: var(--sp-1);
}

.npb__text {
    flex: 1;
    font-size: var(--fs-sub);
    line-height: $lh-sub;
    color: var(--c-warning);
    letter-spacing: 0;
    min-width: 0;
}

/* ── 右侧动作 ── */
.npb__action {
    display: flex;
    flex-direction: row;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
    margin-left: var(--sp-4);
    padding-left: var(--sp-3);
    padding-right: var(--sp-3);
    min-height: var(--tap-min);
    border-radius: var(--r-sm);
    background-color: var(--c-n-0);
    transition: transform var(--d-fast) var(--ease-std), opacity var(--d-fast) var(--ease-std);
}

.npb__action--press {
    transform: scale(var(--press-scale));
    opacity: var(--press-opacity);
}

.npb__action-text {
    font-size: var(--fs-btn-m);
    line-height: $lh-btn-m;
    font-weight: $fw-medium;
    color: var(--c-warning);
    letter-spacing: 0;
}

.npb__action--disabled .npb__action-text {
    color: var(--t-4);
}
</style>
