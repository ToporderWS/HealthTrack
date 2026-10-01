<template>
    <!--
      SC-25 关于页（pages/mine/about）
      依据：S1-C §二 SC-25（F-067）｜S1-C §八 第 9 条（非医疗器械声明必备）
            ｜DESIGN.md §10.3（**A 类系统导航栏**）/ §11 / §12 / §13

      顶栏：**A 类系统导航栏**（B 类自绘顶栏名单 = SC-01~06/11/18，**不含** SC-25）
            ⇒ 标题「关于」由 `pages.json` 指定；本页**不加** `navigationStyle: custom`。

      结构：
        [① 品牌区] 康迹 / HealthTrack ＋ Slogan「记录 + 趋势」＋ 产品定位 ＋ 版本（单一来源 config）
        [② 非医疗声明] **完整展示**（DESIGN.md §12：SC-25 必备）
        [③ 内链] 用户协议 → SC-24 ／ 隐私政策 → SC-23
                 ★ 需求方 2026-09-22 **A-3 裁定**：SC-25 增加指向 SC-23 / SC-24 的内部入口。
                   原 S1-C §4.2 口径为「SC-23/24/25 无出口跳转」⇒ 本页属**已登记的范围增量**
                   （见 S4-1 报告；SC-23 / SC-24 自身仍保持无出口跳转）。
        [④ 联系维护者] 运营者 / 邮箱 / 其他联系方式 / 响应时限 —— 全部取自 `utils/legal.js`
                       集中配置；**未提供的一律显示占位，绝不编造**（S4-1 裁定 §五）。
        [⑤ 页脚] 草案标记（DESIGN.md §12 要求保留）

      访问态：**访客放行**（DESIGN.md §13）⇒ **不做登录守卫**；**离线完全可读**。
      状态覆盖：正常 ✅ ｜ 空/加载/失败/401/防重/高风险 **N/A**（纯静态只读页、零请求、零写操作）
        ｜ 未登录 ✅ **放行** ｜ 离线 ✅ 可读。

      ★ 品牌视觉：纯 CSS 几何（无插画库、无 WebFont、无 emoji），全部走设计令牌；
        仅用 `--s-brand-soft` 浅底 + `--c-p-*` 品牌阶表达品牌感，**不破坏**整体设计系统。
      ★ 版本：只从 `utils/config.js`（与 `manifest.json.versionName` 同值）读取，
        **不在本页硬编码**任何版本号（避免"多页版本不一致"）。
    -->
    <view class="about">
        <view class="about__body">
            <view class="about__inner">
                <!-- ① 品牌区 -->
                <AppCard variant="brand-soft" class="about__card">
                    <view class="about__brand">
                        <!-- 品牌标记：三级品牌阶柱状（记录 → 趋势 的几何隐喻，纯 CSS） -->
                        <view class="about__mark">
                            <view class="about__bar about__bar--a"></view>
                            <view class="about__bar about__bar--b"></view>
                            <view class="about__bar about__bar--c"></view>
                        </view>

                        <text class="about__name">康迹</text>
                        <text class="about__en">HealthTrack</text>
                        <text class="about__slogan">记录 + 趋势</text>
                    </view>

                    <text class="about__desc">个人健康数据记录与趋势管理工具</text>
                    <text class="about__version">{{ versionText }}</text>
                </AppCard>

                <!-- ② 非医疗声明（完整展示） -->
                <AppCard title="非医疗声明" class="about__card">
                    <text
                        v-for="(line, i) in medicalNotice"
                        :key="'mn-' + i"
                        class="about__p"
                    >{{ line }}</text>
                </AppCard>

                <!-- ③ 内链（A-3 裁定：SC-25 → SC-24 / SC-23） -->
                <AppCard class="about__card">
                    <AppListRow title="用户协议" :arrow="true" @tap="goTerms" />
                    <AppListRow title="隐私政策" :arrow="true" last @tap="goPrivacy" />
                </AppCard>

                <!-- ④ 联系维护者（集中配置；未提供则显示占位，不编造） -->
                <AppCard title="联系维护者" class="about__card">
                    <AppListRow
                        v-for="(row, i) in contactRows"
                        :key="row.key"
                        :last="i === contactRows.length - 1"
                    >
                        <view class="about__row">
                            <text class="about__row-k">{{ row.label }}</text>
                            <view class="about__row-v-wrap">
                                <text class="about__row-v">{{ row.value }}</text>
                            </view>
                        </view>
                    </AppListRow>

                    <text class="about__note">{{ pendingHint }}</text>
                </AppCard>

                <!-- ⑤ 页脚：草案标记 -->
                <text class="about__draft">{{ draftMark }}</text>
            </view>
        </view>

        <DevPagePreviewer />
    </view>
</template>

<script>
import AppCard from '../../components/AppCard.vue'
import AppListRow from '../../components/AppListRow.vue'
import DevPagePreviewer from '../../components/DevPagePreviewer.vue'

import { navigateTo, ROUTES } from '../../utils/route'
import { MEDICAL_DISCLAIMER } from '../../utils/legalContent'
import {
    LEGAL_APP_VERSION,
    LEGAL_DRAFT_MARK,
    LEGAL_PENDING_HINT,
    getContactRows
} from '../../utils/legal'

export default {
    components: {
        AppCard: AppCard,
        AppListRow: AppListRow,
        DevPagePreviewer: DevPagePreviewer
    },
    data: function () {
        return {
            /** 非医疗声明（完整展示；取自草案 A12，逐条渲染） */
            medicalNotice: MEDICAL_DISCLAIMER,
            /** 联系维护者信息行（集中配置；未提供 → 占位） */
            contactRows: getContactRows(),
            draftMark: LEGAL_DRAFT_MARK,
            pendingHint: LEGAL_PENDING_HINT
        }
    },
    computed: {
        /** 版本文案（**单一来源** = `utils/config.js`；本页不硬编码） */
        versionText: function () {
            return '版本 ' + LEGAL_APP_VERSION
        }
    },
    onLoad: function () {
        // 纯静态页：无加载、无请求；★ 不设登录守卫（S1-C §5.1：SC-25 按需放行）。
    },
    onUnload: function () {
        // 空实现：本页无定时器、无网络监听、无草稿
    },
    methods: {
        /* 内置入口（无载荷组件裸写 @tap 是正确写法：C-20 `$emit('tap')` 不带参数） */
        goTerms: function () {
            navigateTo(ROUTES.TERMS)
        },
        goPrivacy: function () {
            navigateTo(ROUTES.PRIVACY)
        }
    }
}
</script>

<style scoped lang="scss">
.about {
    min-height: 100vh;
    background-color: var(--s-page);
}

.about__body {
    padding-top: var(--page-pad-t);
    padding-bottom: calc(var(--safe-b) + var(--section-gap));
}

.about__inner {
    max-width: var(--content-max);
    margin-left: auto;
    margin-right: auto;
    padding-left: var(--gutter);
    padding-right: var(--gutter);
}

.about__card {
    margin-bottom: var(--card-gap);
}

/* ── ① 品牌区 ── */
.about__brand {
    display: flex;
    flex-direction: column;
    align-items: center;
}

/* 品牌标记：三根递增柱体（底对齐，横排；只用令牌间距与品牌阶） */
.about__mark {
    display: flex;
    flex-direction: row;
    align-items: flex-end;
    justify-content: center;
    margin-bottom: var(--sp-6);
}

.about__bar {
    width: var(--sp-3);
    border-radius: var(--r-xs);
}

.about__bar + .about__bar {
    margin-left: var(--sp-2);
}

.about__bar--a {
    height: var(--sp-4);
    background-color: var(--c-p-200);
}

.about__bar--b {
    height: var(--sp-7);
    background-color: var(--c-p-400);
}

.about__bar--c {
    height: var(--sp-10);
    background-color: var(--c-p-600);
}

.about__name {
    font-size: var(--fs-h1);
    line-height: $lh-h1;
    font-weight: $fw-semibold;
    color: var(--t-1);
    letter-spacing: 0;
}

.about__en {
    margin-top: var(--sp-1);
    font-size: var(--fs-sub);
    line-height: $lh-sub;
    font-weight: $fw-medium;
    color: var(--t-3);
    letter-spacing: 0;
}

.about__slogan {
    margin-top: var(--sp-4);
    font-size: var(--fs-body);
    line-height: $lh-body;
    font-weight: $fw-medium;
    color: var(--c-p-600);
    letter-spacing: 0;
}

.about__desc {
    display: block;
    margin-top: var(--sp-7);
    font-size: var(--fs-body);
    line-height: $lh-reading;
    color: var(--t-2);
    text-align: center;
    letter-spacing: 0;
}

.about__version {
    display: block;
    margin-top: var(--sp-3);
    font-size: var(--fs-caption);
    line-height: $lh-caption;
    color: var(--t-3);
    text-align: center;
    letter-spacing: 0;
    font-variant-numeric: tabular-nums;
    font-feature-settings: "tnum" 1;
}

/* ── ② 非医疗声明正文（与 SC-23/24 同一长文本口径） ── */
.about__p {
    display: block;
    font-size: var(--fs-body);
    line-height: $lh-reading;
    color: var(--t-2);
    letter-spacing: 0;
}

.about__p + .about__p {
    margin-top: var(--sp-4);
}

/* ── ④ 联系维护者：信息行（左字段名 + 右值；值可收缩单行省略） ──
   与 SC-18 资料区同一口径：值不交给 C-20 的 `value` 位（该位 `flex-shrink: 0`，
   长值会把左侧字段名压到 0 宽后溢出绘制）⇒ 值放进默认插槽（`flex: 1 + min-width: 0`）。 */
.about__row {
    display: flex;
    flex-direction: row;
    align-items: center;
    min-width: 0;
}

.about__row-k {
    flex-shrink: 0;
    font-size: var(--fs-body);
    line-height: $lh-body;
    color: var(--t-2);
    letter-spacing: 0;
}

.about__row-v-wrap {
    flex: 1;
    min-width: 0;
    margin-left: var(--sp-5);
    overflow: hidden;
}

.about__row-v {
    display: block;
    font-size: var(--fs-body);
    line-height: $lh-body;
    font-weight: $fw-medium;
    color: var(--t-1);
    letter-spacing: 0;
    text-align: right;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}

/* 联系区占位说明（用户可见的诚实表述，不呈现工程字样） */
.about__note {
    display: block;
    margin-top: var(--sp-5);
    font-size: var(--fs-caption);
    line-height: $lh-caption;
    color: var(--t-3);
    letter-spacing: 0;
}

/* ── ⑤ 页脚：草案标记 ── */
.about__draft {
    display: block;
    padding-left: var(--sp-2);
    padding-right: var(--sp-2);
    font-size: var(--fs-micro);
    line-height: $lh-micro;
    color: var(--t-4);
    letter-spacing: 0;
}
</style>
