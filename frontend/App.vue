<script>
/**
 * 应用级生命周期（DESIGN.md / S1-D）。
 *
 * 本批（S3-1）在 onLaunch 中**只做本地状态恢复**，不发起任何网络请求：
 *   - 恢复登录态与「首次引导 / 协议同意」标记（仅读本地存储）；
 *   - 启动分流（SC-01 → SC-02 / SC-03 / SC-05 / SC-06）由 **SC-01 启动页**负责。
 * 依据 S1-C SC-01 ⑰：启动阶段**不主动调用** A-03 刷新 Token，Token 有效性由首个业务接口的 401 裁决。
 */
import { useUserStore } from './store/user'
import { syncAll } from './utils/notify'
import { upcomingTriggers } from './utils/reminder'

/**
 * 回前台重排程的**节流窗口**（毫秒）：避免前后台频繁切换造成重复 / 高频重建。
 * 页面内的**配置变更**不受此节流影响（那条路径每次都必须真同步）。
 */
const RESYNC_THROTTLE_MS = 5 * 60 * 1000

export default {
    onLaunch() {
        try {
            const store = useUserStore()
            store.hydrate()
        } catch (e) {
            // 本地登录态读取异常 → 视为未登录（S1-C SC-01 ⑫：不弹错误弹窗、不阻塞用户）
            console.warn('[康迹] 启动本地状态恢复失败，按未登录处理')
        }
    },
    onShow() {
        // S3-9 第 11 步（H-29 · B1 档）：A-11 提醒兜底 —— App 启动 / **重新回到前台**时，
        // 按 24h 滚动窗口重新同步未来提醒（节流窗口内不重复重建）。
        // ★ 边界（**不得误读为"修复了 A1"**）：只恢复"重新进入 App 之后"的提醒；
        //   进程被划掉期间**已错过**的提醒**不补发** —— 不做后台保活、不接第三方推送。
        try {
            syncAll(upcomingTriggers(), RESYNC_THROTTLE_MS)
        } catch (e) {
            // 通知通道异常不得影响启动流程
        }
    },
    onHide() {
        // 空实现（S3-1 无后台任务）。
    }
}
</script>

<style lang="scss">
/**
 * 运行时层（DESIGN.md §1.1 ②）
 * ------------------------------------------------------------------
 * 职责：把 uni.scss（定义层）的 SCSS 变量**转写**为 CSS 自定义属性 + 提供全局重置。
 * 硬规则：本层**不写新字面值**，一律 --x 取值于同名 SCSS 变量（DESIGN.md §1.3 规则 1/3）。
 * 注意：注释内**不得出现**井号加花括号的插值写法 —— Dart Sass 会求值注释中的插值并报未定义变量。
 * 全局重置项：页面底色、字体栈、正文基线、tabular-nums、盒模型（DESIGN.md §3 强制项）。
 */

/* ── §2.1 中性阶 ── */
page,
:root {
    --c-n-0: #{$c-n-0};
    --c-n-25: #{$c-n-25};
    --c-n-50: #{$c-n-50};
    --c-n-100: #{$c-n-100};
    --c-n-200: #{$c-n-200};
    --c-n-300: #{$c-n-300};
    --c-n-400: #{$c-n-400};
    --c-n-500: #{$c-n-500};
    --c-n-600: #{$c-n-600};
    --c-n-700: #{$c-n-700};
    --c-n-800: #{$c-n-800};

    /* ── §2.2 品牌主色「康迹青」 ── */
    --c-p-50: #{$c-p-50};
    --c-p-100: #{$c-p-100};
    --c-p-200: #{$c-p-200};
    --c-p-300: #{$c-p-300};
    --c-p-400: #{$c-p-400};
    --c-p-500: #{$c-p-500};
    --c-p-600: #{$c-p-600};
    --c-p-700: #{$c-p-700};

    /* ── §2.3 语义色 ── */
    --c-success: #{$c-success};
    --c-success-bg: #{$c-success-bg};
    --c-warning: #{$c-warning};
    --c-warning-bg: #{$c-warning-bg};
    --c-danger: #{$c-danger};
    --c-danger-bg: #{$c-danger-bg};
    --c-info: #{$c-info};
    --c-info-bg: #{$c-info-bg};

    /* ── §2.4 文字 / 表面 / 边框 ── */
    --t-1: #{$t-1};
    --t-2: #{$t-2};
    --t-3: #{$t-3};
    --t-4: #{$t-4};
    --t-inverse: #{$t-inverse};
    --t-link: #{$t-link};
    --t-danger: #{$t-danger};
    --s-page: #{$s-page};
    --s-card: #{$s-card};
    --s-card-sub: #{$s-card-sub};
    --s-sunken: #{$s-sunken};
    --s-brand-soft: #{$s-brand-soft};
    --s-overlay: #{$s-overlay};
    --b-line: #{$b-line};
    --b-border: #{$b-border};
    --b-focus: #{$b-focus};

    /* ── §2.5 图表专用色（唯一色相） ── */
    --c-chart-main: #{$c-chart-main};
    --c-chart-a: #{$c-chart-a};
    --c-chart-b: #{$c-chart-b};
    --c-chart-goal: #{$c-chart-goal};
    --c-chart-grid: #{$c-chart-grid};
    --c-chart-area-top: #{$c-chart-area-top};
    --c-chart-area-bottom: #{$c-chart-area-bottom};
    --c-chart-point: #{$c-chart-point};
    --c-chart-point-ring: #{$c-chart-point-ring};

    /* ── §3 字体 ── */
    --font-sans: #{$font-sans};
    --font-num: #{$font-num};
    --fs-display: #{$fs-display};
    --fs-metric-xl: #{$fs-metric-xl};
    --fs-metric-l: #{$fs-metric-l};
    --fs-h1: #{$fs-h1};
    --fs-h2: #{$fs-h2};
    --fs-h3: #{$fs-h3};
    --fs-body: #{$fs-body};
    --fs-body-strong: #{$fs-body-strong};
    --fs-sub: #{$fs-sub};
    --fs-caption: #{$fs-caption};
    --fs-micro: #{$fs-micro};
    --fs-btn-l: #{$fs-btn-l};
    --fs-btn-m: #{$fs-btn-m};

    /* ── §4 间距与布局常量 ── */
    --sp-1: #{$sp-1};
    --sp-2: #{$sp-2};
    --sp-3: #{$sp-3};
    --sp-4: #{$sp-4};
    --sp-5: #{$sp-5};
    --sp-6: #{$sp-6};
    --sp-7: #{$sp-7};
    --sp-8: #{$sp-8};
    --sp-9: #{$sp-9};
    --sp-10: #{$sp-10};
    --gutter: #{$gutter};
    --card-pad: #{$card-pad};
    --card-gap: #{$card-gap};
    --section-gap: #{$section-gap};
    --row-h: #{$row-h};
    --row-pad-y: #{$row-pad-y};
    --tap-min: #{$tap-min};
    --tabbar-h: #{$tabbar-h};
    --navbar-h: #{$navbar-h};
    --content-max: #{$content-max};
    --safe-b: #{$safe-b};

    /* ── §5 圆角 ── */
    --r-xs: #{$r-xs};
    --r-sm: #{$r-sm};
    --r-md: #{$r-md};
    --r-lg: #{$r-lg};
    --r-xl: #{$r-xl};
    --r-full: #{$r-full};

    /* ── §6 阴影 ── */
    --el-0: #{$el-0};
    --el-1: #{$el-1};
    --el-2: #{$el-2};
    --el-3: #{$el-3};

    /* ── §7 动效 ── */
    --d-fast: #{$d-fast};
    --d-row: #{$d-row};
    --d-base: #{$d-base};
    --d-slow: #{$d-slow};
    --d-toast: #{$d-toast};
    --d-breathe: #{$d-breathe};
    --ease-std: #{$ease-std};
    --ease-out: #{$ease-out};
    --ease-in: #{$ease-in};
    --press-scale: #{$press-scale};
    --press-opacity: #{$press-opacity};
    --breathe-opacity: #{$breathe-opacity};

    /* ── §10.2 布局令牌 ── */
    --nav-total-h: #{$nav-total-h};
    --tabbar-total-h: #{$tabbar-total-h};
    --page-pad-x: #{$page-pad-x};
    --page-pad-t: #{$page-pad-t};
    --page-pad-b: #{$page-pad-b};
    --chart-w: #{$chart-w};
    --chart-h: #{$chart-h};
}

/* ── 全局重置（唯一豁免文件内的样式仅限本段：不留任何页面级样式） ── */
page {
    background-color: var(--s-page);
    color: var(--t-1);
    font-family: var(--font-sans);
    font-size: var(--fs-body);
    line-height: $lh-body;
    letter-spacing: 0;
    font-variant-numeric: tabular-nums;
    font-feature-settings: "tnum" 1;
    -webkit-font-smoothing: antialiased;
}

view,
text,
input,
textarea,
scroll-view,
swiper,
picker,
button {
    box-sizing: border-box;
}
</style>
