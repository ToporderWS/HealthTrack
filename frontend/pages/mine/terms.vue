<template>
    <!--
      SC-24 用户协议页（pages/mine/terms）
      依据：S1-C §二 SC-24（F-066）｜S1-B 第三批《隐私政策与用户协议技术草案》B 部分（B1~B16）
            ｜DESIGN.md §10.3（**A 类系统导航栏**）/ §11 / §12 / §13 / §3（长文本页）

      顶栏：**A 类系统导航栏**（B 类自绘顶栏名单 = SC-01~06/11/18，**不含** SC-24）
            ⇒ 标题「用户协议」由 `pages.json` 指定；本页**不加** `navigationStyle: custom`。

      内容：`utils/legalContent.js#TERMS_SECTIONS` —— 纯静态数据，取自 S1-B 第三批技术草案 B 部分。
        产品边界（S1-C §八 第 3/4/5/7 条 + DESIGN.md §12 红线）在本页**逐条保持**：
        本应用是个人健康数据记录与趋势管理工具，不是医疗机构 / 医生 / 诊断系统 / 治疗系统 /
        用药建议系统 / 疾病风险评估系统；**不出现**诊断结论、治疗建议、用药建议、医学风险评分、
        健康好坏判定。

      访问态：**访客放行**（DESIGN.md §13）⇒ **不做登录守卫**；**离线完全可读**。

      长文本排版：同 SC-23（`--fs-body` + `$lh-reading` 48rpx + 分节卡片 + `--section-gap`）。

      状态覆盖：正常 ✅ ｜ 空/加载/失败/401/防重/高风险 **N/A**（纯静态只读页、零请求、零写操作）
        ｜ 未登录 ✅ **放行** ｜ 离线 ✅ 可读。

      ★ 本页**无出口跳转**（S1-C §4.2 原口径保持不变）；跨页内链仅在 SC-25 按 A-3 裁定落地。
    -->
    <view class="legal">
        <view class="legal__body">
            <view class="legal__inner">
                <view class="legal__head">
                    <text
                        v-for="(line, i) in headLines"
                        :key="'head-' + i"
                        class="legal__head-line"
                    >{{ line }}</text>
                </view>

                <AppCard
                    v-for="sec in sections"
                    :key="sec.key"
                    :title="sec.title"
                    class="legal__sec"
                >
                    <template v-for="(blk, i) in sec.body" :key="sec.key + '-b' + i">
                        <text v-if="blk.t === 'p'" class="legal__p">{{ blk.text }}</text>

                        <view v-else-if="blk.t === 'kv'" class="legal__kv">
                            <text class="legal__kv-k">{{ blk.k }}</text>
                            <text class="legal__kv-v">{{ blk.v }}</text>
                        </view>

                        <view v-else-if="blk.t === 'li'" class="legal__li">
                            <view class="legal__li-mark">
                                <view class="legal__li-dot"></view>
                            </view>
                            <text class="legal__li-text">{{ blk.text }}</text>
                        </view>
                    </template>
                </AppCard>

                <text class="legal__note">{{ pendingHint }}</text>
                <text class="legal__draft">{{ draftMark }}</text>
            </view>
        </view>

        <DevPagePreviewer />
    </view>
</template>

<script>
import AppCard from '../../components/AppCard.vue'
import DevPagePreviewer from '../../components/DevPagePreviewer.vue'

import { TERMS_SECTIONS } from '../../utils/legalContent'
import { LEGAL_DRAFT_MARK, LEGAL_ENTITY, LEGAL_PENDING_HINT } from '../../utils/legal'
import { AGREEMENT_VERSION } from '../../utils/config'

export default {
    components: {
        AppCard: AppCard,
        DevPagePreviewer: DevPagePreviewer
    },
    data: function () {
        return {
            sections: TERMS_SECTIONS,
            draftMark: LEGAL_DRAFT_MARK,
            pendingHint: LEGAL_PENDING_HINT
        }
    },
    computed: {
        /** 页首信息行（版本 / 生效日期）—— 版本取 `utils/config.js` 的单一来源 */
        headLines: function () {
            return [
                '协议版本 ' + AGREEMENT_VERSION + '（草案）',
                '生效日期：' + LEGAL_ENTITY.policyEffectiveDate
            ]
        }
    },
    onLoad: function () {
        // 纯静态页：无加载、无请求；★ 不设登录守卫（S1-C §5.1：SC-24 对访客放行）。
    },
    onUnload: function () {
        // 空实现：本页无定时器、无网络监听、无草稿
    }
}
</script>

<style scoped lang="scss">
.legal {
    min-height: 100vh;
    background-color: var(--s-page);
}

.legal__body {
    padding-top: var(--page-pad-t);
    padding-bottom: calc(var(--safe-b) + var(--section-gap));
}

.legal__inner {
    max-width: var(--content-max);
    margin-left: auto;
    margin-right: auto;
    padding-left: var(--gutter);
    padding-right: var(--gutter);
}

.legal__head {
    display: flex;
    flex-direction: column;
    margin-bottom: var(--card-gap);
    padding-left: var(--sp-2);
    padding-right: var(--sp-2);
}

.legal__head-line {
    font-size: var(--fs-caption);
    line-height: $lh-caption;
    color: var(--t-3);
    letter-spacing: 0;
}

.legal__head-line + .legal__head-line {
    margin-top: var(--sp-1);
}

.legal__sec {
    margin-bottom: var(--card-gap);
}

.legal__p {
    display: block;
    font-size: var(--fs-body);
    line-height: $lh-reading;
    color: var(--t-2);
    letter-spacing: 0;
}

.legal__p + .legal__p,
.legal__p + .legal__kv,
.legal__p + .legal__li,
.legal__kv + .legal__p,
.legal__kv + .legal__kv,
.legal__li + .legal__li,
.legal__li + .legal__p {
    margin-top: var(--sp-4);
}

.legal__kv {
    display: flex;
    flex-direction: row;
    align-items: center;
    min-width: 0;
}

.legal__kv-k {
    flex-shrink: 0;
    font-size: var(--fs-body);
    line-height: $lh-reading;
    font-weight: $fw-regular;
    color: var(--t-3);
    letter-spacing: 0;
}

.legal__kv-v {
    flex: 1;
    min-width: 0;
    margin-left: var(--sp-5);
    display: block;
    font-size: var(--fs-body);
    line-height: $lh-reading;
    font-weight: $fw-medium;
    color: var(--t-1);
    letter-spacing: 0;
    text-align: right;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}

.legal__li {
    display: flex;
    flex-direction: row;
    align-items: flex-start;
}

.legal__li-mark {
    width: var(--sp-5);
    height: $lh-reading;
    display: flex;
    flex-direction: row;
    align-items: center;
    justify-content: flex-start;
    flex-shrink: 0;
}

.legal__li-dot {
    width: var(--sp-2);
    height: var(--sp-2);
    border-radius: var(--r-full);
    background-color: var(--c-p-400);
}

.legal__li-text {
    flex: 1;
    min-width: 0;
    font-size: var(--fs-body);
    line-height: $lh-reading;
    color: var(--t-2);
    letter-spacing: 0;
}

.legal__note {
    display: block;
    margin-bottom: var(--sp-5);
    padding-left: var(--sp-2);
    padding-right: var(--sp-2);
    font-size: var(--fs-caption);
    line-height: $lh-caption;
    color: var(--t-3);
    letter-spacing: 0;
}

.legal__draft {
    display: block;
    padding-left: var(--sp-2);
    padding-right: var(--sp-2);
    font-size: var(--fs-micro);
    line-height: $lh-micro;
    color: var(--t-4);
    letter-spacing: 0;
}
</style>
