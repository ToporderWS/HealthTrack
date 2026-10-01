<template>
    <!--
      SC-23 隐私政策页（pages/mine/privacy）
      依据：S1-C §二 SC-23（F-065）｜S1-B 第三批《隐私政策与用户协议技术草案》A 部分（A1~A18）
            ｜DESIGN.md §10.3（**A 类系统导航栏**）/ §11 / §12 / §13 / §3（长文本页）

      顶栏：**A 类系统导航栏**（DESIGN.md §10.3 的 B 类自绘顶栏名单 = SC-01~06/11/18，**不含** SC-23）
            ⇒ 标题「隐私政策」由 `pages.json` 指定；本页**不加** `navigationStyle: custom`、
            **不调用** `uni.setNavigationBarTitle`（避免两份真相）。

      内容：`utils/legalContent.js#PRIVACY_SECTIONS` —— **纯静态数据**（随包发布，无服务端内容接口）。
        正文取自已封板的 S1-B 第三批技术草案 A 部分，**不自行重写法律承诺**；
        涉及运营主体的字段一律取自 `utils/legal.js` 集中配置（**不编造**）。

      访问态：**访客放行**（DESIGN.md §13：SC-23/24/25 与 SC-01/02/03/04 放行）
        ⇒ 本页**不做登录守卫**（首次引导页的协议弹窗可直接进入）；**离线完全可读**。

      长文本排版（DESIGN.md §3 长文本页口径 + §12「不做密密麻麻法律墙」）：
        · 正文 `--fs-body` + 行高 `$lh-reading`（48rpx）；
        · 分节用 C-02 `AppCard`（每节一个清晰小标题）⇒ 有层次、可扫读；
        · 节间 `--section-gap`、段间 `--sp-4`，条目用令牌间距悬挂圆点；
        · **不引入**新 UI 库 / WebFont / 插画 / 花哨背景。

      状态覆盖（DESIGN.md §13 底线清单，逐项说明 —— 本页为纯静态只读页）：
        正常 ✅ 全文本渲染；
        空 / 加载 / 失败 **N/A**（内容随包内置，无请求、无异步数据）；
        未登录 ✅ **放行**（本页对访客开放，不做守卫）；
        离线 ✅ 完全可读（无网络依赖）；
        401 **N/A**（本页不发任何请求）；
        提交防重 / 高风险确认 **N/A**（本页零写操作、零交互控件）。

      ★ 与 SC-25 / SC-24 的关系（S1-C §4.2 原为「无出口跳转」）：
        本页仍**无出口跳转**；仅 SC-25「关于」页按需求方 A-3 裁定增加指向本页与 SC-24 的内链。
    -->
    <view class="legal">
        <view class="legal__body">
            <view class="legal__inner">
                <!-- 页首：政策版本与生效日期（标题由系统导航栏承载，避免重复大标题） -->
                <view class="legal__head">
                    <text
                        v-for="(line, i) in headLines"
                        :key="'head-' + i"
                        class="legal__head-line"
                    >{{ line }}</text>
                </view>

                <!-- 分节正文（数据驱动；每节一张卡 + 清晰小标题） -->
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

                <!-- 占位说明（用户可见的诚实表述，不呈现工程字样） -->
                <text class="legal__note">{{ pendingHint }}</text>

                <!-- 草案标记（DESIGN.md §12：必须保留，不得改写为定稿） -->
                <text class="legal__draft">{{ draftMark }}</text>
            </view>
        </view>

        <!-- 开发环境页面预览器（仅 H5 非生产环境渲染；生产构建下为空节点，不影响正式功能） -->
        <DevPagePreviewer />
    </view>
</template>

<script>
import AppCard from '../../components/AppCard.vue'
import DevPagePreviewer from '../../components/DevPagePreviewer.vue'

import { PRIVACY_SECTIONS } from '../../utils/legalContent'
import {
    LEGAL_DRAFT_MARK,
    LEGAL_ENTITY,
    LEGAL_PENDING_HINT,
    PRIVACY_POLICY_VERSION
} from '../../utils/legal'

export default {
    components: {
        AppCard: AppCard,
        DevPagePreviewer: DevPagePreviewer
    },
    data: function () {
        return {
            /** 分节正文（**静态数据**：运行期不再变更 ⇒ 页面不发生重渲染） */
            sections: PRIVACY_SECTIONS,
            draftMark: LEGAL_DRAFT_MARK,
            pendingHint: LEGAL_PENDING_HINT
        }
    },
    computed: {
        /** 页首信息行（版本 / 生效日期）—— 均取自集中配置，**不硬编码** */
        headLines: function () {
            return [
                '政策版本 ' + PRIVACY_POLICY_VERSION + '（草案）',
                '生效日期：' + LEGAL_ENTITY.policyEffectiveDate
            ]
        }
    },
    onLoad: function () {
        // 无需加载：内容随包内置（纯静态页）。
        // ★ 不设登录守卫：S1-C §5.1 / DESIGN.md §13 明确 SC-23 对访客放行。
    },
    onUnload: function () {
        // 空实现：本页无定时器、无网络监听、无草稿（无资源需释放）
    }
}
</script>

<style scoped lang="scss">
.legal {
    min-height: 100vh;
    background-color: var(--s-page);
}

/* A 类系统导航栏：顶部留页面内边距；底部留安全区 */
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

/* ── 页首信息行（版本 / 生效日期） ── */
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

/* 节间节奏 */
.legal__sec {
    margin-bottom: var(--card-gap);
}

/* ── 段落 ── */
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

/* ── 键值行（左字段名 + 右值；值可收缩单行省略，不挤压字段名） ── */
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

/* ── 清单条目（悬挂圆点 + 正文；圆点居中于首行行高内） ── */
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

/* ── 页脚：占位说明 + 草案标记 ── */
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
