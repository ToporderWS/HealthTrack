<template>
    <!--
      C-13 AppToast（G10 轻提示）
      规格：success / error / info；**同一时刻最多 1 条**；`--d-toast` 后自动消失；不阻塞交互。
      八态：default（显示中）/ pressed·disabled·loading·error·success·empty·offline —— 本组件为消息载体，
           类型由 type 表达，其余交互态 **N/A**。
      用法：每个会产生提示的页面放一个 `<AppToast />`；任何位置调用 `utils/toast.js` 的 showToast()。
    -->
    <view v-if="visible" class="toast-wrap">
        <view class="toast" :class="'toast--' + type">
            <view class="toast__dot"></view>
            <text class="toast__text">{{ text }}</text>
        </view>
    </view>
</template>

<script>
import { registerToastHandler, unregisterToastHandler } from '../utils/toast'
import { TOAST_DURATION_MS } from '../utils/config'

export default {
    name: 'AppToast',
    data: function () {
        return {
            visible: false,
            type: 'info',
            text: ''
        }
    },
    mounted: function () {
        const self = this
        // 注册为当前页面的 Toast 宿主（同一时刻仅 1 条：新消息直接覆盖旧消息并重置计时）
        this.handler = function (type, text) {
            self.show(type, text)
        }
        registerToastHandler(this.handler)
    },
    beforeUnmount: function () {
        if (this.handler) {
            unregisterToastHandler(this.handler)
        }
        if (this.timer) {
            clearTimeout(this.timer)
            this.timer = null
        }
    },
    methods: {
        show: function (type, text) {
            const self = this
            this.type = type
            this.text = text
            this.visible = true
            // 同一时刻仅 1 条：新消息覆盖旧消息并重置计时
            if (this.timer) {
                clearTimeout(this.timer)
            }
            // 停留 --d-toast（2000ms）后自动消失；不阻塞任何交互
            this.timer = setTimeout(function () {
                self.visible = false
                self.timer = null
            }, TOAST_DURATION_MS)
        }
    }
}
</script>

<style scoped lang="scss">
.toast-wrap {
    position: fixed;
    left: 0;
    right: 0;
    bottom: calc(var(--safe-b) + var(--sp-10));
    /*
     * ★ 层级契约（H-34，2026-09-20）：必须**高于**封板组件 C-12 `AppModal` 根节点 `.modal`（z-index: 100）。
     *   原值 90 ⇒ 弹层打开期间提示被弹层遮罩与底部抽屉面板**完全盖住**（元素存在、用户看不到
     *   ⇒ 失败静默；A-07 注销输入错误密码被正确拒绝却毫无反馈，根因即此）。
     *   取值同时须**低于**开发工具 DevPagePreviewer（900/960/1000），避免提示压住开发面板。
     *   两者同处一个层叠上下文（`uni-page-wrapper`，position: relative / z-index: auto）⇒ 比较有效。
     */
    z-index: 110;
    display: flex;
    flex-direction: row;
    justify-content: center;
    pointer-events: none;
}

.toast {
    display: flex;
    flex-direction: row;
    align-items: center;
    max-width: calc(100% - 2 * var(--gutter));
    padding: var(--sp-4) var(--sp-6);
    border-radius: var(--r-md);
    box-shadow: var(--el-3);
    animation: toast-in var(--d-base) var(--ease-out);
}

.toast--success {
    background-color: var(--c-success-bg);
}

.toast--error {
    background-color: var(--c-danger-bg);
}

.toast--info {
    background-color: var(--c-info-bg);
}

.toast__dot {
    width: 12rpx;
    height: 12rpx;
    border-radius: var(--r-full);
    margin-right: var(--sp-3);
}

.toast--success .toast__dot {
    background-color: var(--c-success);
}

.toast--error .toast__dot {
    background-color: var(--c-danger);
}

.toast--info .toast__dot {
    background-color: var(--c-info);
}

.toast__text {
    font-size: var(--fs-body);
    line-height: $lh-body;
    color: var(--t-1);
    letter-spacing: 0;
}

@keyframes toast-in {
    from {
        opacity: 0;
        transform: translateY(var(--sp-3));
    }
    to {
        opacity: 1;
        transform: translateY(0);
    }
}
</style>
