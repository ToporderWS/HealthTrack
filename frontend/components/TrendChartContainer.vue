<template>
    <!--
      C-23 TrendChartContainer（趋势图表容器 / 状态宿主；DESIGN.md §8.3 已登记）

      规格（DESIGN.md §8.3 + §9 + §10.2 + S1-C SC-11 ④⑩⑪⑫⑭）：
        宽 = `var(--chart-w)`、高 = `var(--chart-h)`；**禁写死 px 宽**（§9）。
        状态宿主：正常 / 加载 / 空 / `<2 条` / 失败 / 离线命中 / 离线未命中
                + **切换中（保留旧图 + 淡加载）**。

      ★ 本组件只做「画什么 / 画成什么样」，**不发起任何请求**：
        数据与状态由宿主页 SC-11 持有并传入（这样"切换时保留旧图"才成立 ——
        旧图来自页面持有的旧载荷，而不是本组件的内部缓存）。

      ★ 颜色纪律（DESIGN.md §2.5 / §9）：
        全部 8 类指标共用同一色相；**按指标换色 = 违规**；**不存在第 9 个图表颜色**。
        色值一律由 `utils/chartTheme.js` 从运行时令牌（`App.vue` 的 `--x`）读取，
        本组件与 `chartTheme.js` **都不写任何字面色值**。

      ★ 令牌通道（S3-9 3.3 第4步 建立 → **第5步 真机复测后修正**）：
        App 逻辑层**没有 DOM**，`getComputedStyle` 读不到令牌 ⇒ 真机上 uCharts 收到空色值，
        而 canvas 的 `fillStyle`/`strokeStyle` **赋空串是 no-op**（保留上一个成功设定的值）
        ⇒ 真机表现为「柱体残留轴文字色 `#666666`、血压双线残留到**完全不可见**」
        —— 这才是真机「偏深灰 / 掉线」的真因，**不是配色选错**。
        ⇒ 本组件用 **renderjs** 在**视图层**点名读取 CSS 自定义属性并回传
          （见文件末 `chartTokenBridge`），由 `chartTheme.readToken(name, snapshot)` 兜底。
          **单一真相源不变**（仍是 `App.vue` 的 `:root`），不复制任何色值、不新增颜色体系。
        ★★ 真机教训（勿回退）：**「什么时候触发」与「能不能读到」同等重要** ——
          逻辑层 `mounted()` 早于视图层首帧；在那里直接置标记，会让视图层"首帧就带着标记"，
          对它而言该值从未变化 ⇒ `:change:tokenProbe` **永不触发** ⇒ 桥静默失效
          （第4步真机上整图零变化的直接原因）。现改为**视图层就绪回调主触发 + 兜底时刻**。
        ★ H5 不受影响：逻辑层 DOM 直读成功 ⇒ `raiseProbe()` 直接返回，`.tchart` 上的标记恒为空串，
          `:change:` 不触发，取值来源与绘制次数与改动前完全一致。

      ★ 数据诚实性（DESIGN.md §9①②）：
        缺失日期由 `chartTheme.buildChartData` 填 `null`（不补 0 / 不插值），
        折线在 `connectNulls: false` 下**真实断开**；柱状图遇 `null` **不画零高柱**。

      ★ 第三方图表库：`qiun-data-charts`（uCharts）—— DESIGN.md §9 冻结的唯一图表库，
        S3-4 批次以 `uni_modules` 形式安装。**未启用 ECharts 渲染分支**
        （不传 `echartsH5` / `echartsApp`），故不会加载其 `static/**/echarts.min.js`。

      ★ 离线态的分工（如实登记，避免重复语义）：
        「离线数据 · 更新于 <时间>」离线条按 DESIGN.md §10.1 页面骨架由**宿主页**渲染；
        本组件负责"离线时画什么"：命中缓存 → 正常只读渲染；未命中 → `state = 'empty'`
        （由页面判定并传入，本组件不自行探测缓存）。

      八态：default（正常）/ loading（骨架，慢加载追加一行提示）/ empty（「该时间段还没有记录」）/
            error（失败 + 重试）/ offline（由 empty 承载：缓存未命中）/
            pressed · disabled · success —— **N/A**
            （本组件是只读图表宿主，无按下 / 禁用 / 成功语义；
             「切换中」以 `switching` 表达，属 loading 的持续态而非独立状态。）
    -->
    <view class="tchart" :tokenProbe="tokenProbe" :change:tokenProbe="chartTokenBridge.onProbe">
        <!-- 失败：图表区失败组件 + 重试入口（**不清空指标切换器**由页面保证） -->
        <view v-if="state === 'error'" class="tchart__state">
            <AppErrorState
                variant="inline"
                :text="errorText"
                retry-text="重试"
                @retry="onRetry"
            />
        </view>

        <!-- 首屏加载：图表区骨架（禁整页白屏） -->
        <view v-else-if="state === 'loading'" class="tchart__state">
            <AppSkeleton variant="chart" />
            <!-- DESIGN.md §7④：> 8s 追加「仍在加载，请稍候」 -->
            <text v-if="slowLoading" class="tchart__slow">{{ SLOW_TEXT }}</text>
        </view>

        <!-- 该时间段无记录 -->
        <view v-else-if="state === 'empty'" class="tchart__state">
            <AppEmpty variant="common" :text="emptyText" :show-action="false" />
        </view>

        <!-- 记录数 < 2：只提示，不画不存在的趋势 -->
        <view v-else-if="state === 'insufficient'" class="tchart__state">
            <AppEmpty variant="common" :text="insufficientText" :show-action="false" />
        </view>

        <!-- 正常 / 切换中 -->
        <view v-else class="tchart__canvas">
            <qiun-data-charts
                :type="chartType"
                :chart-data="chartData"
                :opts="chartOpts"
                :background="backgroundColor"
                :error-show="true"
            />

            <!-- 切换中：保留旧图 + 淡加载指示（避免闪白） -->
            <view v-if="switching" class="tchart__switching">
                <view class="tchart__spinner"></view>
                <text class="tchart__switching-text">{{ switchingText }}</text>
            </view>
        </view>
    </view>
</template>

<script>
import AppSkeleton from './AppSkeleton.vue'
import AppEmpty from './AppEmpty.vue'
import AppErrorState from './AppErrorState.vue'

// 第三方图表库（DESIGN.md §9 冻结；uni_modules 形式，按相对路径显式引入以避免歧义）
import qiunDataCharts from '../uni_modules/qiun-data-charts/components/qiun-data-charts/qiun-data-charts.vue'

import {
    CHART_TOKEN,
    buildChartData,
    buildChartOpts,
    captionFontPx,
    chartTokens,
    paletteOf,
    uchartsType
} from '../utils/chartTheme'

/** 空状态文案（DESIGN.md §12 / S1-C SC-11 ⑩②，**逐字冻结**） */
const EMPTY_TEXT = '该时间段还没有记录'

/** `<2 条` 提示文案（DESIGN.md §12 / S1-C SC-11 ⑩③，**逐字冻结**） */
const INSUFFICIENT_TEXT = '至少需要 2 条记录才能画出趋势'

/** 慢加载提示文案（DESIGN.md §7④，**逐字冻结**，与 SC-06 首页同口径） */
const SLOW_TEXT = '仍在加载，请稍候'

/** 切换中的淡加载文案（S1-C SC-11 ⑪） */
const SWITCHING_TEXT = '加载中'

/**
 * 令牌桥请求标记前缀（`':change:tokenProbe'` 的比较值以此开头）。
 * ★ 必须与文件末 renderjs 模块内的 `TOKEN_FLAG` **逐字一致**。
 */
const TOKEN_PROBE_FLAG = 'need'

/**
 * 视图层需要读取的令牌名（**只写名字，不写任何色值**）。
 *
 * ★ 为什么把名字随标记一起传过去，而不是让视图层"枚举全部自定义属性"（真机教训）：
 *   枚举依赖 `CSSStyleDeclaration.length` 是否把 `--x` 计入 —— 该行为随 WebView 实现而异，
 *   真机上不可假设。改为"点名读取"后，视图层只用 `getPropertyValue(name)`，与枚举能力无关。
 *   名字的唯一出处仍是 `chartTheme.CHART_TOKEN` —— **没有第二份定义**。
 */
const TOKEN_PROBE_NAMES = [
    CHART_TOKEN.main,
    CHART_TOKEN.a,
    CHART_TOKEN.b,
    CHART_TOKEN.goal,
    CHART_TOKEN.grid,
    CHART_TOKEN.axisText,
    CHART_TOKEN.bubbleBg,
    CHART_TOKEN.bubbleText,
    CHART_TOKEN.surface,
    CHART_TOKEN.fsCaption
]

/** 传给视图层的标记值：`need|<name>,<name>,…`（名字随标记一起过去，避免依赖枚举） */
const TOKEN_PROBE_VALUE = TOKEN_PROBE_FLAG + '|' + TOKEN_PROBE_NAMES.join(',')

/**
 * 兜底重探时刻（ms，自组件 mounted 起算）。
 * ★ 主通道是视图层就绪回调 `onBridgeReady`（见 `mounted`），这里只兜"回调丢失"；
 *   每个时刻都会先复位再置起 ⇒ 无论视图层何时就绪，都必然产生一次值变化。
 */
const PROBE_RAISE_MS = [700, 1600, 2800, 4500]

/**
 * 令牌桥诊断日志开关（**临时**：真机没有本地调试器，由「运行到手机」的控制台回传现场）。
 * 只写日志、不改任何绘制行为；真机验证通过后应改回 `false`。
 */
const TOKEN_BRIDGE_DEBUG = true

export default {
    name: 'TrendChartContainer',
    components: {
        AppSkeleton: AppSkeleton,
        AppEmpty: AppEmpty,
        AppErrorState: AppErrorState,
        qiunDataCharts: qiunDataCharts
    },
    props: {
        /** 当前指标（8 类之一；决定取值字段与系列色） */
        metricType: { type: String, default: '' },
        /**
         * 图表区状态：
         *   `loading`（首屏）/ `normal`（有图可画）/ `empty`（该时间段无记录）/
         *   `insufficient`（记录数 < 2）/ `error`（请求失败）
         * ★ 由宿主页依据**当前展示的载荷**判定，本组件不自行推断。
         */
        state: { type: String, default: 'loading' },
        /** S-02 的 `data`（`points` / `window` / `chart` / `target_line` …）；无 → null */
        chartPayload: { type: Object, default: null },
        /** 切换中（指标或窗口切换、且**旧图仍在展示**）：淡加载指示 */
        switching: { type: Boolean, default: false },
        /** > 8s 仍未返回 → 在骨架 / 淡加载指示上追加「仍在加载，请稍候」（DESIGN.md §7④） */
        slowLoading: { type: Boolean, default: false },
        /** 失败文案（由宿主页依据统一错误口径给出） */
        errorText: { type: String, default: '加载失败，点击重试' }
    },
    emits: ['retry'],
    data: function () {
        /*
         * ★ 文案常量必须经 `data` 暴露给模板：
         *   本工程使用 Options API 的 `<script>`（**非 `<script setup>`**），
         *   模板只能访问实例上的 `data` / `computed` / `methods` / props，
         *   模块级 `const` 不在实例上 ⇒ 直接写进模板会取到 `undefined`（文案空白）。
         */
        return {
            /** 空状态文案（来自模块级冻结常量） */
            emptyText: EMPTY_TEXT,
            /** `<2 条` 提示文案 */
            insufficientText: INSUFFICIENT_TEXT,
            /** 慢加载提示文案 */
            SLOW_TEXT: SLOW_TEXT,
            /** 视图层回传的令牌快照（App 端兜底色源；H5 恒为 null ⇒ 不影响既有取值链） */
            viewTokens: null,
            /**
             * 令牌桥请求标记（值 = `TOKEN_PROBE_VALUE`，其中携带待读的令牌名）。
             * ★ 只在**视图层首帧渲染完成之后**才从 `''` 置起 —— 见 `mounted()` 的说明。
             */
            tokenProbe: ''
        }
    },
    computed: {
        /** 运行时令牌（读取失败时各项为空串 → 图表降级，但**不伪造颜色**） */
        tokens: function () {
            /*
             * 传入视图层快照：① App 端它是唯一可用色源；② 同时**建立响应式依赖** ——
             * 快照到达时必须重算本计算属性（否则会一直停在首次读到的空值上）。
             * H5 下 `viewTokens` 恒为 null，取值链与改动前**完全一致**。
             */
            return chartTokens(this.viewTokens).values
        },
        /** 坐标轴字号（由 `--fs-caption` 按 750 设计稿基准换算；取不到 → 0 = 沿用库默认） */
        captionPx: function () {
            return captionFontPx(this.viewTokens)
        },
        /** uCharts 组件 `type`（由后端 `chart` 字段驱动：`line` / `column`） */
        chartType: function () {
            return uchartsType(this.chartPayload && this.chartPayload.chart)
        },
        /**
         * 图表底色：取 `--c-n-0`（= `--s-card`）。
         * 令牌未解析时返回 `undefined` ⇒ Vue 使用组件默认值，由库回退其内置白底，
         * **我方不写任何色值**。
         */
        backgroundColor: function () {
            const value = this.tokens.surface
            return value ? value : undefined
        },
        /** uCharts `chartData`：类别轴按服务端窗口铺开，缺失日期为 `null` */
        chartData: function () {
            if (!this.chartPayload) {
                return { categories: [], series: [] }
            }
            return buildChartData(this.metricType, this.chartPayload, paletteOf(this.metricType, this.tokens))
        },
        /** uCharts `opts`（部分覆盖，未给出项沿用库模板） */
        chartOpts: function () {
            return buildChartOpts(this.metricType, this.chartPayload, this.tokens, this.captionPx)
        },
        /** 切换中文案：慢加载时改用「仍在加载，请稍候」，与骨架态同一口径 */
        switchingText: function () {
            return this.slowLoading ? SLOW_TEXT : SWITCHING_TEXT
        }
    },
    mounted: function () {
        /*
         * ★ 令牌桥触发（S3-9 3.3 第5步，**真机复测后修正**）
         *
         * ⛔ 旧写法（真机实测完全无效，勿改回）：在 `mounted()` 里直接
         *    `this.tokenProbe = 'need'`。逻辑层 `mounted()` 早于**视图层首帧**，
         *    于是视图层"第一次渲染"时该值就已经是 `'need'` ⇒ 对它而言**从未变化**
         *    ⇒ `:change:tokenProbe` 永不触发 ⇒ 桥静默失效。
         *    （现象：真机与改动前逐像素相同 —— 柱状仍 `#666666`、血压双线仍不可见。）
         *
         * ✅ 现做法（与第三方 `qiun-data-charts` 解决同一问题的 `getRenderType` 握手同构）：
         *    主通道 = 视图层 renderjs `mounted()` 回调 `onBridgeReady()`（必然晚于首帧）；
         *    兜底 = `PROBE_RAISE_MS` 各时刻"先复位再置起"，保证一定产生一次变化。
         *
         * ★ H5 零代价：`chartTokens(null).ok === true` ⇒ `raiseProbe()` 立即返回，
         *   标记恒为空串，`:change:` 不触发（取值链与改动前同源）。
         */
        this._probeTimers = []
        const self = this
        for (let i = 0; i < PROBE_RAISE_MS.length; i++) {
            this._probeTimers.push(setTimeout(function () {
                self.raiseProbe()
            }, PROBE_RAISE_MS[i]))
        }
    },
    beforeUnmount: function () {
        /* 清理兜底定时器（避免卸载后仍向已销毁实例写响应式字段） */
        const timers = this._probeTimers
        if (timers && timers.length) {
            for (let i = 0; i < timers.length; i++) {
                clearTimeout(timers[i])
            }
        }
        this._probeTimers = []
    },
    methods: {
        onRetry: function () {
            this.$emit('retry')
        },
        /**
         * 视图层就绪回调（renderjs `mounted()` → `callMethod('onBridgeReady')`）。
         * ★ 这是令牌桥的**主触发通道**：由它置标记，才能保证变化发生在视图层首帧之后。
         */
        onBridgeReady: function () {
            this.logBridge('bridge-ready')
            this.raiseProbe()
        },
        /**
         * 置起（先复位再置起）令牌桥标记，确保视图层一定观察到一次变化。
         * ★ 已拿到快照、或本平台可 DOM 直读（H5）⇒ 直接返回，不再打扰视图层。
         */
        raiseProbe: function () {
            if (chartTokens(null).ok) {
                return
            }
            if (this.viewTokens) {
                return
            }
            const self = this
            this.logBridge('raise')
            this.tokenProbe = ''
            this.$nextTick(function () {
                self.tokenProbe = TOKEN_PROBE_VALUE
            })
        },
        /** 诊断日志（**临时**；集中一处便于验证后整体关闭） */
        logBridge: function (stage, extra) {
            if (!TOKEN_BRIDGE_DEBUG) {
                return
            }
            console.log('[SC11-TOKENS] ' + stage + (extra ? ' ' + extra : ''))
        },
        /**
         * 令牌桥失败诊断回调（视图层重试耗尽仍读不到令牌时调用）。
         * ★ 只记日志、不改行为 —— 真机没有本地调试器，这是唯一的失败现场证据。
         */
        onBridgeDiag: function (reason) {
            this.logBridge('bridge-fail', String(reason || ''))
        },
        /**
         * 视图层令牌快照回传（renderjs `callMethod` 的唯一落点）。
         *
         * ★ 接受闸门：**本平台 DOM 直读已成功（H5）时一律忽略** ——
         *   保证 H5 的令牌来源、绘制次数与改动前完全一致，不引入多余重绘。
         *   App 端读不到（`ok === false`）才采用快照；取值优先级仍由 `readToken` 保证
         *   「DOM 优先、快照兜底」。
         */
        onTokensFromView: function (value) {
            if (!value || typeof value !== 'object') {
                return
            }
            if (chartTokens(null).ok) {
                return
            }
            let count = 0
            const next = {}
            for (const name in value) {
                if (Object.prototype.hasOwnProperty.call(value, name) && value[name]) {
                    next[name] = String(value[name])
                    count += 1
                }
            }
            if (!count) {
                return
            }
            this.logBridge('tokens-received', count + ' names')
            this.viewTokens = next
        }
    }
}
</script>

<style scoped lang="scss">
.tchart {
    /* 宽 = var(--chart-w)（DESIGN.md §9 / §10.2：内容宽 = 视口 − 两侧 gutter）
       ★ 本组件由页面放在「最大宽容器」内，故此处 auto 居中即与页面内容左右边缘对齐 */
    width: var(--chart-w);
    margin-left: auto;
    margin-right: auto;
}

/* 状态区（加载 / 空 / <2 条 / 失败）：占满图表高，避免状态切换时页面跳动 */
.tchart__state {
    display: flex;
    flex-direction: column;
    justify-content: center;
    min-height: var(--chart-h);
    padding: var(--card-pad);
    border-radius: var(--r-md);
    background-color: var(--s-card);
    border: 1rpx solid var(--b-line);
    box-shadow: var(--el-0);
}

/* 慢加载提示（DESIGN.md §7④：> 8s 追加一行中性提示） */
.tchart__slow {
    margin-top: var(--sp-4);
    font-size: var(--fs-caption);
    line-height: $lh-caption;
    color: var(--t-3);
    text-align: center;
    letter-spacing: 0;
}

/* 图表区：库组件内部为 width/height:100%，故此处必须给出确定高度 */
.tchart__canvas {
    position: relative;
    width: 100%;
    height: var(--chart-h);
    border-radius: var(--r-md);
    background-color: var(--s-card);
    border: 1rpx solid var(--b-line);
    box-shadow: var(--el-0);
    overflow: hidden;
}

/* 切换中的淡加载指示（覆盖层，不遮挡指标 / 窗口切换器 —— 它们由页面持有） */
.tchart__switching {
    position: absolute;
    top: var(--sp-4);
    right: var(--sp-4);
    display: flex;
    flex-direction: row;
    align-items: center;
    padding: var(--sp-1) var(--sp-3);
    border-radius: var(--r-full);
    background-color: var(--s-card-sub);
    border: 1rpx solid var(--b-line);
}

/* 加载指示：旋转圆环（DESIGN.md §7：加载指示旋转周期走 --d-breathe） */
.tchart__spinner {
    width: 24rpx;
    height: 24rpx;
    border-radius: var(--r-full);
    border: 4rpx solid var(--c-n-200);
    border-top-color: var(--c-p-600);
    animation: tchart-spin var(--d-breathe) linear infinite;
}

.tchart__switching-text {
    margin-left: var(--sp-2);
    font-size: var(--fs-caption);
    line-height: $lh-caption;
    color: var(--t-3);
    letter-spacing: 0;
}

@keyframes tchart-spin {
    from {
        transform: rotate(0deg);
    }

    to {
        transform: rotate(360deg);
    }
}
</style>

<!--
  视图层令牌桥（renderjs）—— App 端 SC-11 配色的唯一可行通道
  （S3-9 3.3 第4步 建立 → **第5步 真机复测未通过后修正**）

  ★ 为什么必须是 renderjs：
    App（app-plus / vue3）的**逻辑层没有 DOM**，`getComputedStyle` 不存在
    ⇒ `chartTheme.readToken()` 在真机上一律读空 ⇒ uCharts 收到空色值
    ⇒ 而 canvas 的 `fillStyle` / `strokeStyle` **赋空串是 no-op**（保留上一个成功设定的值）
    ⇒ 真机表现为「柱体残留轴文字色 `#666666`、折线残留到不可见」。
    而**视图层**（本脚本所在层）是带真 DOM 与 `app.css` 的 WebView ——
    第三方 `qiun-data-charts` 的绘制本身也跑在这一层
    （其 `ucinit()` 里 `document.getElementById(cid).children[0].getContext('2d')`）。
    本模块把令牌值读出后经 `callMethod` 回传逻辑层
    ⇒ **色值仍只有 `App.vue` 的 `:root` 一处真相源**，不复制色值、不新增颜色体系。

  ★ 相对第4步版本的三处修正（真机教训，勿改回）：
    ① **新增 `mounted()` → `callMethod('onBridgeReady')` 握手**。
       第4步由逻辑层 `mounted()` 主动置标记，但那一刻早于视图层首帧 ⇒
       视图层"首帧就带着标记" ⇒ 对它而言从未变化 ⇒ `:change:` 永不触发 ⇒ 桥静默失效。
       握手让逻辑层在"视图层已就绪"之后才置标记。
       （第三方库解决同类问题时用的正是同一模式：其 renderjs `mounted()` 会
        `this.$ownerInstance.callMethod('getRenderType')`。）
    ② 由"枚举 `CSSStyleDeclaration.length` 里的 `--x`"改为**点名读取** ——
       待读的令牌名随标记字符串一起传过来，只用 `getPropertyValue(name)`，
       不再依赖 WebView 的枚举能力（该能力随实现而异，真机不可假设）。
    ③ 重试耗尽仍读不到时回调 `onBridgeDiag` 上报原因，供真机取证。

  ★ 只读、不写：只读 `getComputedStyle` 的自定义属性；不改样式、不请求网络、不产生绘制。
-->
<script module="chartTokenBridge" lang="renderjs">
/** 与逻辑层 `TOKEN_PROBE_FLAG` 逐字一致（此处按前缀匹配） */
const TOKEN_FLAG = 'need'
/** 重试间隔（ms）：首轮可能早于 `app.css` 生效，最多再试这么多轮 */
const RETRY_MS = [90, 180, 360, 720, 1400, 2400]
/** 优先读取的元素（CSS 自定义属性会继承 ⇒ 任一处命中即可） */
const ROOT_SELECTOR = '.tchart'
/** 视图层诊断日志开关（临时；与逻辑层各自独立，便于分辨"桥没醒来"还是"读不到值"） */
const DEBUG = true

/** 诊断日志 */
function log(message) {
    if (DEBUG) {
        console.log('[SC11-TOKENS/renderjs] ' + message)
    }
}

/** 从标记字符串里解析出要读的令牌名：`need|--a,--b` → `['--a','--b']` */
function parseNames(value) {
    const text = String(value == null ? '' : value)
    const i = text.indexOf('|')
    if (i < 0) {
        return []
    }
    const parts = text.slice(i + 1).split(',')
    const out = []
    for (let k = 0; k < parts.length; k++) {
        const name = parts[k] ? String(parts[k]).trim() : ''
        if (name) {
            out.push(name)
        }
    }
    return out
}

/**
 * 候选元素（自定义属性会继承 ⇒ 越靠前的"实际元素"越可靠，取到即止）。
 * @returns {Element[]}
 */
function candidateEls(instance) {
    const list = []
    if (instance && instance.$el) {
        list.push(instance.$el)
    }
    const query = function (sel) {
        try {
            return document.querySelector(sel)
        } catch (e) {
            return null
        }
    }
    const canvasEl = query(ROOT_SELECTOR + ' canvas')
    if (canvasEl) {
        list.push(canvasEl)
    }
    const rootEl = query(ROOT_SELECTOR)
    if (rootEl) {
        list.push(rootEl)
    }
    if (document.body) {
        list.push(document.body)
    }
    if (document.documentElement) {
        list.push(document.documentElement)
    }
    return list
}

/**
 * **点名读取**令牌（不依赖枚举）。
 * @returns {{values: object, hit: number, probed: number}}
 */
function readTokens(names, instance) {
    const values = {}
    if (typeof document === 'undefined' || typeof window === 'undefined'
        || typeof window.getComputedStyle !== 'function') {
        return { values: values, hit: 0, probed: names.length }
    }
    const els = candidateEls(instance)
    let hit = 0
    for (let i = 0; i < names.length; i++) {
        const name = names[i]
        for (let j = 0; j < els.length; j++) {
            let value = ''
            try {
                value = window.getComputedStyle(els[j]).getPropertyValue(name)
            } catch (e) {
                value = ''
            }
            value = value ? String(value).trim() : ''
            if (value) {
                values[name] = value
                hit += 1
                break
            }
        }
    }
    return { values: values, hit: hit, probed: names.length }
}

export default {
    mounted: function () {
        /*
         * ★ 握手：告诉逻辑层"视图层已就绪"。
         *   逻辑层据此才置 `tokenProbe` ⇒ 该变化必然发生在**首帧之后** ⇒ `:change:` 必触发。
         */
        const owner = this.$ownerInstance
        const call = function (name, arg) {
            if (!owner || typeof owner.callMethod !== 'function') {
                return false
            }
            try {
                if (arg === undefined) {
                    owner.callMethod(name)
                } else {
                    owner.callMethod(name, arg)
                }
                return true
            } catch (e) {
                return false
            }
        }
        if (call('onBridgeReady')) {
            log('bridge-ready 已通知逻辑层')
            return
        }
        log('bridge-ready 通知失败（ownerInstance 不可达）')
        call('onBridgeDiag', 'no-owner-ready')
    },
    methods: {
        /**
         * `:change:tokenProbe` 落点：读取并回传令牌（带重试）。
         * @param {string} value 逻辑层写入的标记（形如 `need|--a,--b`）
         * @param {string} oldValue 上一次的值
         * @param {object} ownerInstance 逻辑层组件实例代理（`callMethod` 宿主）
         * @param {object} instance 本 renderjs 实例
         */
        onProbe: function (value, oldValue, ownerInstance, instance) {
            if (String(value == null ? '' : value).indexOf(TOKEN_FLAG) !== 0) {
                return
            }
            const names = parseNames(value)
            if (!names.length) {
                log('probe 收到但未解析出令牌名')
                return
            }
            const owner = ownerInstance || this.$ownerInstance
            const self = this
            let round = 0
            const run = function () {
                const done = self.publish(owner, instance, names)
                round += 1
                if (!done && round <= RETRY_MS.length) {
                    setTimeout(run, RETRY_MS[round - 1])
                } else if (!done) {
                    log('probe 重试耗尽，仍未读到任何令牌')
                    self.report(owner, 'no-token-resolved')
                }
            }
            run()
        },
        /**
         * 读取并回传令牌。
         * @returns {boolean} 是否已成功送达（false ⇒ 调用方决定是否重试）
         */
        publish: function (owner, instance, names) {
            const result = readTokens(names, instance)
            if (!result.hit) {
                return false
            }
            log('已读到 ' + result.hit + '/' + result.probed + ' 个令牌')
            try {
                if (owner && typeof owner.callMethod === 'function') {
                    owner.callMethod('onTokensFromView', result.values)
                    return true
                }
            } catch (e) {
                /* 逻辑层暂不可达：交给下一步重试 */
            }
            return false
        },
        /** 失败上报（真机取证用；不改变任何行为） */
        report: function (owner, reason) {
            try {
                if (owner && typeof owner.callMethod === 'function') {
                    owner.callMethod('onBridgeDiag', reason)
                }
            } catch (e) {
                /* 忽略 */
            }
        }
    }
}
</script>
