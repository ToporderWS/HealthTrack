<template>
    <!--
      SC-01 启动页 / 闪屏（pages/launch/index）
      依据：S1-C §二 SC-01 ｜ DESIGN.md §11 / §10.3（B 类：自绘顶栏，本页无顶栏）
      · ① 品牌区 ② 加载指示 ③ 底部版本号小字（内部测试版） ④ **无任何可点击入口**
      · 本页自身即加载态；在 LAUNCH_MIN_SHOW_MS（600ms）后完成本地登录态判断并分发；
        兜底 LAUNCH_TIMEOUT_MS（3 秒）超时按"未登录"处理（S1-C SC-01 ⑨⑪）
      · 分流为**纯本地状态判断**，不发起任何网络请求；**不弹 Toast**（闪屏期不弹提示）
    -->
    <view class="launch">
        <view class="launch__body">
            <!-- 品牌标识：纯 CSS 几何构成（不引入图标库 / 不使用 emoji） -->
            <view class="launch__mark">
                <view class="launch__bar launch__bar--1"></view>
                <view class="launch__bar launch__bar--2"></view>
                <view class="launch__bar launch__bar--3"></view>
            </view>
            <text class="launch__name">康迹 HealthTrack</text>
            <text class="launch__slogan">个人健康记录与趋势查看</text>
            <text class="launch__tentative">产品名称暂定</text>
        </view>

        <view class="launch__foot">
            <view class="launch__loading">
                <view class="launch__ring"></view>
                <text class="launch__loading-text">正在启动</text>
            </view>
            <text class="launch__version">v{{ version }} · 内部测试版</text>
        </view>
    </view>
</template>

<script>
import { resolveStartupRoute, ROUTES } from '../../utils/route'
import { isAgreementAccepted } from '../../utils/auth'
import { APP_VERSION, LAUNCH_MIN_SHOW_MS, LAUNCH_TIMEOUT_MS } from '../../utils/config'

export default {
    data: function () {
        return {
            version: APP_VERSION,
            startAt: 0,
            dispatched: false,
            timer: null
        }
    },
    onLoad: function () {
        this.startAt = Date.now()
        this.startWatchdog()
        this.dispatch()
    },
    onUnload: function () {
        if (this.timer) {
            clearTimeout(this.timer)
            this.timer = null
        }
    },
    methods: {
        /** 兜底：最长停留 LAUNCH_TIMEOUT_MS，超时按"未登录"处理（不无限等待） */
        startWatchdog: function () {
            const self = this
            this.timer = setTimeout(function () {
                if (!self.dispatched) {
                    self.go(ROUTES.LOGIN)
                }
            }, LAUNCH_TIMEOUT_MS)
        },
        /** 本地登录态判断 → 目标页（失败一律视为未登录，不弹错误弹窗） */
        dispatch: function () {
            let target = ROUTES.LOGIN
            try {
                target = resolveStartupRoute(isAgreementAccepted())
            } catch (e) {
                target = ROUTES.LOGIN
            }

            const self = this
            const elapsed = Date.now() - this.startAt
            const wait = LAUNCH_MIN_SHOW_MS - elapsed
            if (wait > 0) {
                // 最短展示时长：避免"明显空白闪屏"
                setTimeout(function () {
                    self.go(target)
                }, wait)
            } else {
                this.go(target)
            }
        },
        go: function (target) {
            if (this.dispatched) {
                return
            }
            this.dispatched = true
            if (this.timer) {
                clearTimeout(this.timer)
                this.timer = null
            }
            // 清栈跳转：启动页不可被返回
            uni.reLaunch({ url: target })
        }
    }
}
</script>

<style scoped lang="scss">
.launch {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: space-between;
    min-height: 100vh;
    padding-top: var(--sp-10);
    padding-bottom: calc(var(--safe-b) + var(--sp-8));
    padding-left: var(--gutter);
    padding-right: var(--gutter);
    background-color: var(--s-page);
}

.launch__body {
    flex: 1;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
}

/* 品牌标识：品牌色底 + 三根递增白色竖条（"记录 + 趋势"的抽象几何，非医学符号） */
.launch__mark {
    width: 132rpx;
    height: 132rpx;
    border-radius: var(--r-lg);
    background-color: var(--c-p-600);
    display: flex;
    flex-direction: row;
    align-items: flex-end;
    justify-content: center;
    padding-bottom: var(--sp-6);
    box-shadow: var(--el-1);
}

.launch__bar {
    width: 14rpx;
    border-radius: var(--r-full);
    background-color: var(--t-inverse);
    margin-left: var(--sp-1);
    margin-right: var(--sp-1);
}

.launch__bar--1 {
    height: 22rpx;
}

.launch__bar--2 {
    height: 42rpx;
}

.launch__bar--3 {
    height: 64rpx;
}

.launch__name {
    margin-top: var(--sp-8);
    font-size: var(--fs-h1);
    line-height: $lh-h1;
    font-weight: $fw-semibold;
    color: var(--t-1);
    letter-spacing: 0;
}

.launch__slogan {
    margin-top: var(--sp-3);
    font-size: var(--fs-sub);
    line-height: $lh-sub;
    color: var(--t-2);
    letter-spacing: 0;
}

.launch__tentative {
    margin-top: var(--sp-2);
    font-size: var(--fs-micro);
    line-height: $lh-micro;
    color: var(--t-4);
    letter-spacing: 0;
}

.launch__foot {
    display: flex;
    flex-direction: column;
    align-items: center;
}

.launch__loading {
    display: flex;
    flex-direction: row;
    align-items: center;
}

/* 极简进度指示（不显示百分比）；旋转周期复用 §7 的 --d-breathe */
.launch__ring {
    width: 28rpx;
    height: 28rpx;
    border: 3rpx solid var(--b-border);
    border-top-color: var(--c-p-600);
    border-radius: var(--r-full);
    animation: launch-spin var(--d-breathe) linear infinite;
    margin-right: var(--sp-3);
}

.launch__loading-text {
    font-size: var(--fs-caption);
    line-height: $lh-caption;
    color: var(--t-3);
    letter-spacing: 0;
}

.launch__version {
    margin-top: var(--sp-4);
    font-size: var(--fs-micro);
    line-height: $lh-micro;
    color: var(--t-4);
    letter-spacing: 0;
}

@keyframes launch-spin {
    from {
        transform: rotate(0deg);
    }
    to {
        transform: rotate(360deg);
    }
}
</style>
