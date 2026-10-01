<template>
    <!--
      SC-21 数据导出页（pages/data/export）
      依据：S1-C §二 SC-21（结构 ①~⑩ / ⑨~⑰ 状态与接口 / 红线）｜S1-C-UIUX §5 空状态、§6 P1 边界
            ｜DESIGN.md §2.3（令牌登记用途）/ §8（C-01/C-03/C-06/C-08/C-12/C-14/C-17/C-19/C-20）/ §11 / §12 / §13
      顶栏：**A 类系统导航栏**（DESIGN.md §10.3：B 类自绘顶栏名单 = SC-01~06/11/18，不含 SC-21）——
            标题「数据导出」由 `pages.json` 在**子项 3.4 接线**时指定；本页**不调用** `uni.setNavigationBarTitle`
            （未接线前无页面对应，自行设标题会产生两份真相）。

      结构（与 S1-C SC-21 逐项对应）：
        [① 顶部栏] 系统导航栏
        [② 时间范围] 近 7 天 / 近 30 天 / 近 90 天 / 自定义 / 全部（**5 段**，C-08 `AppSegmented`）
                     ★「全部」= **不传 `range_start` / `range_end`**（后端 `null` 即不限时间）
                     ★「自定义」= C-06 `AppDatePicker`×2 抽屉，半开区间（结束日 **+1 天**，绝不拼 23:59:59）
        [③ 指标选择] 8 类多选（**默认全选**）+ [全选/清空]
                     **B-1 裁定**：C-20 `#tail` 槽 + C-19 `AppSwitch`，**不新增组件编号**
                     ★ 行本身 `arrow = false` ⇒ `tapEnabled = !disabled && arrow = false` ⇒ 组件**不派发 `tap`**：
                       不出现"假入口"箭头，开关是唯一交互点
        [④ 格式选择] CSV / JSON（C-08 两段；默认 **CSV**，S-6）
        [⑤ 生成按钮] 「生成文件」（C-01 主按钮）
        [⑥ 二次验密弹窗] **每次导出必弹，不可豁免**（C-12）：「为保护你的数据，请输入登录密码确认」
                     + 说明「仅导出你自己的数据」+ [取消] [确认导出]；连续错 3 次 → 服务端 `429` 中止本次导出
        [⑦ 进行态] **页内自绘进度条**（B-2：纯 CSS 走令牌，**不新增组件编号**）+「生成中…」+ 按钮置灰
        [⑧ 生成成功] 「下载 / 保存」→ **B-3**：H5 降级为**浏览器下载**；**B-4**：「分享 / 打开」**不渲染**
        [⑨ 历史任务] `E-04` 最近导出任务：[下载]（10 分钟内有效）
                     ★ 任务行 `arrow = false`（同 ③ 口径）⇒ 唯一交互点是行尾 [下载] 按钮
        [⑩ 页脚说明] 「导出文件为临时文件，生成后 10 分钟内可下载；用户主动另存到系统目录的文件不受本应用管理」

      ★★ 四条硬口径（本页安全与诚实边界，验收必看）：
        ① **每次导出必二次验密、无豁免**（`S1-A §4`：**不因数据范围小而豁免**）⇒ 生成按钮**永远**先开验密弹窗，
           页面里**不存在**任何"跳过验密直接生成"的调用路径；
        ② **`file_token` 用完即弃、绝不落盘**（SC-21 红线③）⇒ 凭证只作为**局部变量**在下载调用链中短暂存在，
           既**不写入 `storage`**、也**不放进 `data`**（`data` 中找不到任何 token 字段），页面卸载即随内存消失；
        ③ **必须在线**：离线 ⇒ 生成按钮置灰 + 离线条「当前网络不可用」；历史任务的下载项显示「需联网下载」且按钮置灰；
        ④ **不臆造数据**：`E-04` **不返回任何 range 字段**（`export_service.job_view()`，见登记 **G-11**）⇒
           历史任务行**不显示"范围"**（规格 ⑨ 要求但**接口无数据来源**），改为如实显示「格式 · 条数 · 状态」，
           **不猜测、不拼接、不为它改后端**。

      ★★ 平台与文案口径（H5 实测事实 + 已下裁定）：
        · **B-3**：H5 **无沙盒落盘**（`uni.saveFile` → `fail: not supported`；`getFileSystemManager` ＝ `undefined`），
          故导出**降级为浏览器下载**；成功提示**逐字**「文件已开始下载，请在浏览器下载目录查看。」
          —— 规格 ⑯ 的「已保存到 <位置>」**不采用**（H5 拿不到系统路径，写出来就是假信息）；
        · **B-4**：`uni.share` ＝ `undefined`、`uni.openDocument` 为**假成功**（回调 ok 但什么都不做）⇒
          「分享 / 打开」**不渲染**（渲染了必然点不动或假成功）；
        · **进度条为"不确定进度"**：后端 `E-01` 是**同步生成**（成功即 `ready`）、**无进度接口** ⇒
          进度条只表达"正在进行"，**不伪造百分比、也不为了凑时长加延迟**（与"不造假"铁律一致，登记 **G-14**）；
        · **文件名由前端按同规则推导**：H5 开发期 CORS 只暴露 `X-Request-Id`
          （`backend/app/core/cors.py#DEV_CORS_EXPOSE_HEADERS`）⇒ **读不到 `Content-Disposition`** ⇒
          用 `api/exports.js#exportFileName()` 按服务端 `download_filename()` 的**同一条规则**生成（登记 **G-15**）。

      状态覆盖（S1-C ⑨~⑰ 逐项映射）：
        正常 ✅ 选范围 / 指标 / 格式 → 验密 → 生成 → 下载 → Toast
        空态 ✅ 「暂无可导出的数据」+ [返回]；**生成按钮置灰**（判据 = `D-01` 的 `total_records === 0`）
        加载 ✅ 生成中：进度条 + 「生成中…」+ 按钮 `loading + disabled`（不可重复发起）
        失败 ✅ 密码错 → 「密码不正确」（弹窗内联，**重回验密步骤、不清空已选条件**）
              `EXPORT_IN_PROGRESS` → 「已有导出任务进行中，请稍后」（并顺带刷新历史任务，说明"进行中"的那条是谁）
              `SESSION_VERIFY_ABORTED` → 服务端文案「验证失败次数过多，请重新发起」+ **需重新发起**
              其他失败 → 「导出失败，请重试」+ **页内重试入口**（重试仍**必须再次验密**）
              下载超时/凭证过期（`410`）→ 「下载链接已过期，请重新生成」
        未登录 ✅ 守卫 → SC-03
        离线 ✅ 离线条 + 生成按钮置灰；历史下载项「需联网下载」；**不进入验密流程**
        401 ✅ 统一请求层（单次 refresh + replay；失败清栈回 SC-03）
        提交防重 ✅ `generating` ⇒ 按钮 `loading + disabled`；`downloadingId` ⇒ 单任务下载互斥
        高风险确认 ✅ 每次生成必验密（**无豁免**）+ 弹窗说明"仅导出你自己的数据"

      ★ 返回拦截铁律（S3-2 实测，必须遵守）：本页**不实现 `onBackPress`** ——
        返回箭头走系统导航栏、无需自绘返回；未写该钩子即不存在"自我拦截 → `navigateBack:fail`"风险。
      ★ **不实现 `onShow`**：本页**无子页面**（导出进行态是页内状态、不新增页面）⇒ 不存在"从子页返回需刷新"的场景。

      ★ 未接线（**如实登记**，非漏做）：`pages.json` / `utils/route.js` / `DevPagePreviewer` 的注册属
        **子项 3.4**，本子项**未改一行** ⇒ 本页当前**不可 URL 直达**，故本子项**无 H5 端到端**（与 3.1/3.2 同口径）。
      ★ 本页**不含任何破坏性操作**（导出是只读导出 + 写"任务记录"，不删、不改业务数据），
        故与 SC-22 不同，本页**不使用 `--c-danger`**（其登记用途为"危险操作警示"）。
    -->
    <view class="epage">
        <view class="epage__body">
            <view class="epage__inner">
                <!-- ⑭ 离线标记条（文案逐字取自 S1-C SC-21 ⑭） -->
                <view v-if="offline" class="epage__block">
                    <AppOfflineBar variant="offline" text="当前网络不可用" />
                </view>

                <!-- 网络恢复横幅（3s 后自行撤下，DESIGN.md §8.2 C-17） -->
                <view v-if="restoredVisible" class="epage__block">
                    <AppOfflineBar variant="restored" text="网络已恢复" />
                </view>

                <!-- ⑩ 空态：「暂无可导出的数据」+ 返回（生成按钮仍渲染但置灰，见下方 ⑤） -->
                <view v-if="noData" class="epage__block">
                    <AppEmpty
                        variant="common"
                        text="暂无可导出的数据"
                        action-text="返回"
                        @action="onBack"
                    />
                </view>

                <!-- ══════════ ② 时间范围 + ③ 指标选择 ══════════ -->
                <view class="epage__block">
                    <AppCard title="导出范围">
                        <!-- 说明：范围是**导出条件**（不是查询预览），故不显示"将导出 N 条"——条数由服务端在生成时确定 -->
                        <AppSegmented
                            :model-value="rangeMode"
                            :options="rangeOptions"
                            :disabled="generating"
                            @change="onRangeChange"
                        />
                        <text v-if="rangeHint" class="epage__hint">{{ rangeHint }}</text>

                        <!-- ③ 指标多选（B-1：C-20 `#tail` 槽 + C-19；行不设 arrow ⇒ 不派发 tap ⇒ 无假入口） -->
                        <view class="epage__metrics-head">
                            <text class="epage__metrics-title">指标</text>
                            <AppButton
                                :label="metricToggleLabel"
                                type="text"
                                size="s"
                                :disabled="generating"
                                @tap="onMetricToggleAll"
                            />
                        </view>
                        <AppListRow
                            v-for="(row, index) in metricRows"
                            :key="row.type"
                            :icon="row.icon"
                            :title="row.title"
                            :last="index === metricRows.length - 1"
                        >
                            <template #tail>
                                <AppSwitch
                                    :model-value="row.checked"
                                    @change="onToggleMetric(row.type)"
                                />
                            </template>
                        </AppListRow>

                        <!-- 一个都没选时给出说明（置灰的按钮必须说明原因，**不静默无反应**） -->
                        <text v-if="selectionHint" class="epage__hint">{{ selectionHint }}</text>
                    </AppCard>
                </view>

                <!-- ══════════ ④ 格式 + ⑤ 生成 + ⑦ 进行态 + ⑧ 生成结果 ══════════ -->
                <view class="epage__block">
                    <AppCard title="导出格式">
                        <AppSegmented
                            :model-value="formatMode"
                            :options="formatOptions"
                            :disabled="generating"
                            @change="onFormatChange"
                        />

                        <!-- ⑦ 进行态：页内自绘进度条（不确定进度）+「生成中…」+ 按钮置灰 -->
                        <view v-if="generating" class="epage__progress-wrap">
                            <view class="epage__progress">
                                <view class="epage__progress-bar"></view>
                            </view>
                            <text class="epage__progress-text">生成中…</text>
                        </view>

                        <view class="epage__action">
                            <AppButton
                                label="生成文件"
                                block
                                :disabled="generateDisabled"
                                :loading="generating"
                                @tap="onGenerate"
                            />
                        </view>

                        <!-- ⑫③ 生成失败：明确提示 + **重试入口**（不可静默失败；重试仍必须先验密） -->
                        <view v-if="genError" class="epage__feedback">
                            <text class="epage__feedback-text">{{ genError }}</text>
                            <AppButton
                                label="重试"
                                type="secondary"
                                size="s"
                                :disabled="generating || offline"
                                @tap="onRetryGenerate"
                            />
                        </view>

                        <!-- ⑧ 生成成功 →「下载 / 保存」（B-3 浏览器下载；**不渲染**分享 / 打开） -->
                        <view v-if="generatedReady" class="epage__result">
                            <text class="epage__result-title">文件已生成</text>
                            <text class="epage__result-meta">{{ generatedMeta }}</text>
                            <text class="epage__result-meta">有效期至 {{ generatedExpireText }}</text>
                            <view class="epage__action">
                                <AppButton
                                    label="下载文件"
                                    type="secondary"
                                    block
                                    :disabled="downloadDisabled"
                                    :loading="generatedDownloading"
                                    @tap="onDownloadGenerated"
                                />
                            </view>
                        </view>
                    </AppCard>
                </view>

                <!-- ══════════ ⑨ 历史任务（E-04） ══════════ -->
                <view class="epage__block">
                    <AppCard title="最近导出任务">
                        <!-- 离线缓存只读 ⇒ **必须标注更新时间**（S1-C §四 网络与离线行为矩阵） -->
                        <text v-if="historyFromCache && historyStamp" class="epage__hint">
                            离线数据 · 更新于 {{ historyStamp }}
                        </text>

                        <text v-if="historyLoading && !historyItems.length" class="epage__hint">加载中…</text>
                        <text v-else-if="historyError" class="epage__error-text">{{ historyError }}</text>
                        <AppEmpty
                            v-else-if="!historyItems.length"
                            variant="common"
                            text="还没有导出任务"
                            :show-action="false"
                        />
                        <template v-else>
                            <!-- ★ 行不设 arrow ⇒ tapEnabled=false ⇒ 唯一交互点是行尾 [下载] -->
                            <!-- ★ 不显示"范围"：E-04 不含任何 range 字段（G-11）⇒ 如实显示「格式 · 条数 · 状态」 -->
                            <AppListRow
                                v-for="(row, index) in historyRows"
                                :key="row.export_id"
                                :title="row.time"
                                :subtitle="row.meta"
                                :last="index === historyRows.length - 1 && !historyHasMore"
                            >
                                <template #tail>
                                    <AppButton
                                        label="下载"
                                        type="secondary"
                                        size="s"
                                        :disabled="!row.canDownload"
                                        :loading="row.loading"
                                        @tap="onDownload(row)"
                                    />
                                </template>
                            </AppListRow>
                            <view v-if="historyHasMore" class="epage__action">
                                <AppButton
                                    label="加载更多"
                                    type="text"
                                    size="s"
                                    :disabled="historyLoading || offline"
                                    :loading="historyLoading"
                                    @tap="loadMoreHistory"
                                />
                            </view>
                        </template>
                    </AppCard>
                </view>

                <!-- ⑩ 页脚说明（逐字；用户可见的"10 分钟"口径只出现在这里与任务行有效期） -->
                <text class="epage__footer">{{ footerNote }}</text>
            </view>
        </view>

        <!-- ⑥ 二次验密弹窗（C-12；**每次导出必弹、不可豁免**；非破坏性操作 ⇒ 用默认 info 模式） -->
        <AppModal
            :show="pwdVisible"
            title="验证登录密码"
            confirm-text="确认导出"
            cancel-text="取消"
            :confirm-disabled="!pwdValue"
            @confirm="onPwdConfirm"
            @cancel="onPwdCancel"
        >
            <view class="epage__modal-text">为保护你的数据，请输入登录密码确认</view>
            <view class="epage__modal-text">仅导出你自己的数据</view>
            <view class="epage__field">
                <AppInput
                    v-model="pwdValue"
                    label="登录密码"
                    placeholder="请输入登录密码"
                    password
                    :maxlength="64"
                    :error="pwdError"
                />
            </view>
        </AppModal>

        <!-- 自定义时间范围（C-12 抽屉 + 两把 C-06 日期选择器，**不新增范围组件**） -->
        <AppModal
            :show="rangeVisible"
            title="自定义时间范围"
            confirm-text="确定"
            cancel-text="取消"
            @confirm="onRangeConfirm"
            @cancel="onRangeCancel"
        >
            <view class="epage__field">
                <AppDatePicker
                    v-model="draftStart"
                    mode="date"
                    label="开始日期"
                    placeholder="请选择开始日期"
                    :end="today"
                />
            </view>
            <view class="epage__field">
                <AppDatePicker
                    v-model="draftEnd"
                    mode="date"
                    label="结束日期"
                    placeholder="请选择结束日期"
                    :end="today"
                />
            </view>
            <text class="epage__hint">按所选日期范围导出（含首尾两天）</text>
        </AppModal>

        <!-- 轻提示宿主（生成成功 / 下载 / 各类失败经此渲染） -->
        <AppToast />

        <!-- 开发期页面预览入口（第 21 项 SC-21 的 ready 开关属子项 3.4） -->
        <DevPagePreviewer />
    </view>
</template>

<script>
import AppCard from '../../components/AppCard.vue'
import AppListRow from '../../components/AppListRow.vue'
import AppSwitch from '../../components/AppSwitch.vue'
import AppSegmented from '../../components/AppSegmented.vue'
import AppDatePicker from '../../components/AppDatePicker.vue'
import AppModal from '../../components/AppModal.vue'
import AppInput from '../../components/AppInput.vue'
import AppButton from '../../components/AppButton.vue'
import AppEmpty from '../../components/AppEmpty.vue'
import AppOfflineBar from '../../components/AppOfflineBar.vue'
import AppToast from '../../components/AppToast.vue'
import DevPagePreviewer from '../../components/DevPagePreviewer.vue'

import { navigateBack, requireLogin } from '../../utils/route'
import { showToast } from '../../utils/toast'
import { errorText, newIdempotencyKey } from '../../utils/request'
import { isOnline, OFFLINE_SUBMIT_TEXT } from '../../utils/network'
import { getAccessToken } from '../../utils/auth'
import { loadCache, saveCache } from '../../utils/cache'
import { METRIC_TYPES, metricLabel } from '../../utils/metrics'
import { NETWORK_BANNER_MS } from '../../utils/config'
import { fetchDataSummary } from '../../api/data'
import {
    createExport,
    fetchExport,
    fetchExports,
    exportDownloadUrl,
    exportFileName
} from '../../api/exports'

/** 时间范围默认值（近 30 天；与 SC-10 / SC-22 默认值一致） */
const DEFAULT_RANGE = '30'

/** 时间范围**五段**（S1-C SC-21 ② 逐字，顺序即展示顺序；「全部」= 不限时间） */
const RANGE_OPTIONS = [
    { value: '7', label: '近 7 天' },
    { value: '30', label: '近 30 天' },
    { value: '90', label: '近 90 天' },
    { value: 'custom', label: '自定义' },
    { value: 'all', label: '全部' }
]

/** 格式两段（S1-C SC-21 ④ 逐字顺序「CSV / JSON」；S-6 默认取首项 CSV） */
const FORMAT_OPTIONS = [
    { value: 'csv', label: 'CSV' },
    { value: 'json', label: 'JSON' }
]
const DEFAULT_FORMAT = 'csv'

/** 历史任务每页条数（S-10：进页即请求 `E-04`，`limit=20`，**仅展示、不自动下载**） */
const HISTORY_LIMIT = 20

/**
 * 历史任务缓存键（**页内常量**）。
 * ★ 沿用 G-6 / S-1 先例：不登记进 `utils/cache.js#CACHE_KEYS`（S3-5 已封板资产），
 *   `loadCache` / `saveCache` 按 key 字符串工作，行为与登记完全一致；
 *   待需求方授权一次性治理 G-6 时把它迁入 `CACHE_KEYS` 即可（本页只需改这一行）。
 * ★ **该缓存不含 `file_token`**：`E-04` 本身就不返回凭证（见 `api/exports.js` 头注）
 *   ⇒ 缓存它**不违反**「`file_token` 用完即弃、不持久缓存」红线。
 */
const HISTORY_CACHE_KEY = 'cache.export_history'

/** ⑩ 页脚说明（S1-C SC-21 ⑩ 逐字，**不得改写**） */
const FOOTER_NOTE = '导出文件为临时文件，生成后 10 分钟内可下载；用户主动另存到系统目录的文件不受本应用管理'

/** ⑧ 下载成功提示（**B-3 裁定逐字**；替代规格 ⑯ 的「已保存到 <位置>」） */
const DOWNLOAD_DONE_TEXT = '文件已开始下载，请在浏览器下载目录查看。'

/** ⑯ 生成成功（S1-C SC-21 ⑯ 逐字） */
const GENERATED_TEXT = '文件已生成'

/** ⑫① 密码错（与后端 `ERROR_MESSAGE[PASSWORD_INVALID]` 逐字同值） */
const PASSWORD_TEXT = '密码不正确'

/** ⑫② 进行中（与后端 `ERROR_MESSAGE[EXPORT_IN_PROGRESS]` 逐字同值） */
const IN_PROGRESS_TEXT = '已有导出任务进行中，请稍后'

/** ⑫③ 生成失败（S1-C SC-21 ⑫ 逐字） */
const FAIL_TEXT = '导出失败，请重试'

/** ⑫④ 下载超时 / 凭证过期（S1-C SC-21 ⑫ 逐字；与后端 `ERROR_MESSAGE[EXPORT_EXPIRED]` 同义） */
const EXPIRED_TEXT = '下载链接已过期，请重新生成'

/** ⑭ 离线时历史下载项的标注（S1-C SC-21 ⑭ 逐字） */
const NEED_NETWORK_TEXT = '需联网下载'

/** ⑩ 空态（S1-C SC-21 ⑩ 逐字；亦用于"点了置灰按钮"时的原因提示） */
const NO_DATA_TEXT = '暂无可导出的数据'

/** 一个指标都没选时的说明 */
const NO_SELECT_TEXT = '请至少选择一个指标'

/** 当前平台不支持文件下载时的如实提示（**不伪造成功**） */
const UNSUPPORTED_TEXT = '当前运行环境不支持文件下载'

/** 任务状态 → 界面文案（E-04 的 `status` 全集：pending/ready/downloaded/expired/purged/failed） */
function statusText(status) {
    if (status === 'pending') {
        return '生成中'
    }
    if (status === 'ready') {
        return '可下载'
    }
    if (status === 'downloaded') {
        return '已下载'
    }
    if (status === 'expired') {
        return '已过期'
    }
    if (status === 'purged') {
        return '已清理'
    }
    if (status === 'failed') {
        return '生成失败'
    }
    return '未知状态'
}

/** 两位补零 */
function pad2(value) {
    return value < 10 ? '0' + value : String(value)
}

/** `Date` → `YYYY-MM-DD`（本地墙上时间，S1-D D-4） */
function dayString(date) {
    return String(date.getFullYear()) + '-' + pad2(date.getMonth() + 1) + '-' + pad2(date.getDate())
}

/** 今天 ± N 天的 `YYYY-MM-DD`（N 为负即往前） */
function shiftDay(days) {
    const d = new Date()
    d.setDate(d.getDate() + days)
    return dayString(d)
}

/** `YYYY-MM-DD` 偏移 N 天（把「结束日期」变成半开区间的开区端点） */
function addDays(dayText, days) {
    const parts = String(dayText || '').split('-')
    if (parts.length !== 3) {
        return ''
    }
    const d = new Date(Number(parts[0]), Number(parts[1]) - 1, Number(parts[2]))
    d.setDate(d.getDate() + days)
    return dayString(d)
}

/** 可下载状态（与后端 `export_service.DOWNLOADABLE_STATUSES` 同值） */
function isDownloadable(status) {
    return status === 'ready' || status === 'downloaded'
}

export default {
    components: {
        AppCard: AppCard,
        AppListRow: AppListRow,
        AppSwitch: AppSwitch,
        AppSegmented: AppSegmented,
        AppDatePicker: AppDatePicker,
        AppModal: AppModal,
        AppInput: AppInput,
        AppButton: AppButton,
        AppEmpty: AppEmpty,
        AppOfflineBar: AppOfflineBar,
        AppToast: AppToast,
        DevPagePreviewer: DevPagePreviewer
    },
    data: function () {
        return {
            /* ── ① 数据存在性（D-01；用于 ⑩ 空态与生成按钮置灰） ── */
            /** 是否已拿到 `D-01` 结论（拿不到时**不擅自判空**，避免把"请求失败"渲染成"没有数据"） */
            dataChecked: false,
            hasData: true,

            /* ── ② 时间范围 ── */
            /** '7' | '30' | '90' | 'custom' | 'all' */
            rangeMode: DEFAULT_RANGE,
            /** 自定义范围的**已生效**取值（`YYYY-MM-DD`） */
            customStart: '',
            customEnd: '',
            /** 自定义抽屉的**草稿**值（确认后才生效，取消即丢弃） */
            draftStart: '',
            draftEnd: '',
            rangeVisible: false,

            /* ── ③ 指标多选（**默认全选 8 类**，S-7） ── */
            metricSelection: METRIC_TYPES.slice(),

            /* ── ④ 格式 ── */
            formatMode: DEFAULT_FORMAT,

            /* ── ⑥ 验密弹窗（每次导出必弹，无豁免） ── */
            pwdVisible: false,
            pwdValue: '',
            pwdError: '',

            /* ── ⑤⑦⑧ 生成与下载 ── */
            generating: false,
            /** 最近一次生成成功的任务视图（`E-01` 响应 `data`；**不含 `file_token`**） */
            generated: null,
            genError: '',
            /** 正在下载的任务 id（0 = 空闲）—— 用于单任务互斥与行内 loading */
            downloadingId: 0,

            /* ── ⑨ 历史任务（E-04） ── */
            historyItems: [],
            historyCursor: '',
            historyHasMore: false,
            historyLoading: false,
            historyError: '',
            /** 离线缓存读取标记 + 缓存写入时刻（**必须标注更新时间**） */
            historyFromCache: false,
            historyStamp: '',

            /* ── 网络 ── */
            offline: false,
            restoredVisible: false,
            networkHandler: null,
            bannerTimer: null,

            /* ── 静态选项（放在 data 里以保持模板取值路径稳定） ── */
            rangeOptions: RANGE_OPTIONS,
            formatOptions: FORMAT_OPTIONS,
            footerNote: FOOTER_NOTE
        }
    },
    computed: {
        /** 指标多选行（顺序 = `METRIC_TYPES` 固定序；8 类均有 C-20 内建几何图标） */
        metricRows: function () {
            const rows = []
            for (let i = 0; i < METRIC_TYPES.length; i++) {
                const type = METRIC_TYPES[i]
                rows.push({
                    type: type,
                    icon: type,
                    title: metricLabel(type),
                    checked: this.metricSelection.indexOf(type) >= 0
                })
            }
            return rows
        },
        /** 是否已全选 8 类（全选 ⇒ 请求传 `metric_types: null`，即"全部指标"） */
        allMetricsSelected: function () {
            return this.metricSelection.length === METRIC_TYPES.length
        },
        /** [全选/清空] 一键切换：未全选时显示「全选」，已全选时显示「清空」 */
        metricToggleLabel: function () {
            return this.allMetricsSelected ? '清空' : '全选'
        },
        /** 一个指标都没选时的说明（开关是唯一交互点，故需要文字解释置灰原因） */
        selectionHint: function () {
            return this.metricSelection.length === 0 ? NO_SELECT_TEXT : ''
        },
        /** 请求用的指标数组（按 `METRIC_TYPES` 固定序，**与开关点击顺序无关**，保证确定性） */
        selectedMetricTypes: function () {
            const picked = []
            for (let i = 0; i < METRIC_TYPES.length; i++) {
                if (this.metricSelection.indexOf(METRIC_TYPES[i]) >= 0) {
                    picked.push(METRIC_TYPES[i])
                }
            }
            return picked
        },
        /** 今天的 `YYYY-MM-DD`（日期选择器上界：记录不可能发生在未来） */
        today: function () {
            return dayString(new Date())
        },
        /**
         * 请求窗口（**半开区间 `[start, end)`**，与 SC-10 / SC-22 完全同先例）。
         *   · 「全部」  ⇒ `{start: '', end: ''}` ⇒ 请求**不传** `range_start` / `range_end`（服务端不限时间）；
         *   · 近 N 天（含今天）：`start = 今天−(N−1)`、`end = 明天`；
         *   · 自定义：`start = 开始日期`、`end = 结束日期 + 1 天`（**不拼 23:59:59**）。
         */
        windowRange: function () {
            if (this.rangeMode === 'all') {
                return { start: '', end: '' }
            }
            if (this.rangeMode === 'custom') {
                return {
                    start: this.customStart,
                    end: this.customEnd ? addDays(this.customEnd, 1) : ''
                }
            }
            const days = Number(this.rangeMode) || 30
            return {
                start: shiftDay(1 - days),
                end: shiftDay(1)
            }
        },
        /** 自定义范围已生效时的展示串（**事实展示**，非文案创作） */
        rangeHint: function () {
            if (this.rangeMode !== 'custom') {
                return ''
            }
            if (!this.customStart || !this.customEnd) {
                return ''
            }
            return this.customStart + ' ~ ' + this.customEnd
        },
        /** ⑩ 空态（**仅在 `D-01` 明确返回 0 条时成立**；请求失败不算） */
        noData: function () {
            return this.dataChecked && !this.hasData
        },
        /** [生成文件] 是否不可点（离线 / 生成中 / 无数据 / 未选指标）—— ⑩ 空态置灰、⑭ 离线置灰 */
        generateDisabled: function () {
            return this.offline || this.generating || this.noData || this.metricSelection.length === 0
        },
        /** ⑧ 是否展示"生成成功"区块（`E-01` 成功即 `ready`；`downloaded` 仍可重复下载） */
        generatedReady: function () {
            return !!(this.generated && isDownloadable(String(this.generated.status)))
        },
        /** ⑧ 结果摘要（格式 · 条数；**E-01 视图里没有 range，故不展示范围**） */
        generatedMeta: function () {
            if (!this.generated) {
                return ''
            }
            const name = String(this.generated.format || '').toUpperCase()
            const raw = Number(this.generated.record_count)
            return name + ' · ' + (isNaN(raw) ? '--' : String(raw) + ' 条')
        },
        /** ⑧ 可下载窗口（`download_expires_at` = 生成 + 10 分钟） */
        generatedExpireText: function () {
            return this.generated ? String(this.generated.download_expires_at || '') : ''
        },
        /** ⑧ 最近生成任务是否正在下载 */
        generatedDownloading: function () {
            return !!(this.generated && this.downloadingId === this.generated.export_id)
        },
        /** ⑧ [下载文件] 是否不可点（离线 / 下载中） */
        downloadDisabled: function () {
            return this.offline || this.generatedDownloading
        },
        /** ⑨ 历史任务行视图（**不含 file_token**；离线时不可下载并标注「需联网下载」） */
        historyRows: function () {
            const rows = []
            for (let i = 0; i < this.historyItems.length; i++) {
                const item = this.historyItems[i] || {}
                const status = String(item.status || '')
                const downloadable = isDownloadable(status)
                const raw = Number(item.record_count)
                let meta = String(item.format || '').toUpperCase() + ' · '
                meta += isNaN(raw) ? '--' : String(raw) + ' 条'
                meta += ' · ' + statusText(status)
                if (this.offline && downloadable) {
                    meta += ' · ' + NEED_NETWORK_TEXT
                }
                rows.push({
                    export_id: item.export_id,
                    time: String(item.created_at || ''),
                    meta: meta,
                    // 离线不可下载（⑭）；且必须处于可下载状态（服务端口径：ready / downloaded）
                    canDownload: downloadable && !this.offline,
                    loading: this.downloadingId === item.export_id
                })
            }
            return rows
        }
    },
    onLoad: function () {
        // 未登录守卫（S1-C ⑬：需登录）
        if (!requireLogin()) {
            return
        }

        // 本页首个动作（生成）之前就可能有请求，故**进入即判一次网络**
        // （与只读页"靠请求失败反推离线"不同：生成按钮必须**先**置灰，不能等失败）
        const self = this
        isOnline().then(function (online) {
            self.offline = !online
        })

        // 网络监听（**必须在 onLoad 注册**，S3-2 时序纪律）
        this.networkHandler = function (res) {
            self.handleNetworkChange(res)
        }
        uni.onNetworkStatusChange(this.networkHandler)

        // ⑩ 空态判据（`D-01`：`total_records === 0`）+ ⑨ 历史任务首屏（`E-04`，S-10）
        this.loadSummary()
        this.loadHistory()
    },
    onUnload: function () {
        this.clearBanner()
        if (this.networkHandler) {
            uni.offNetworkStatusChange(this.networkHandler)
            this.networkHandler = null
        }
    },
    onHide: function () {
        // 空实现：本页无后台任务、无计时型业务（`E-01` 为**同步生成**，不存在"离开页面后仍在生成"）
    },
    methods: {
        /* ───────────── ① 数据存在性（D-01，只读） ───────────── */

        /**
         * 判定「有没有可导出的数据」（S1-C SC-21 ⑩）。
         * ★ 只在**明确拿到 0 条**时判空；请求失败时 `dataChecked` 保持 `false` ⇒ 不置灰生成按钮
         *   （否则会把"网络抖了"渲染成"你没有数据"，属误导）。
         */
        loadSummary: function () {
            const self = this
            return fetchDataSummary().then(function (res) {
                const data = res && res.data ? res.data : {}
                const raw = Number(data.total_records)
                self.dataChecked = true
                self.hasData = !(raw === 0)
            }, function (err) {
                if (err && err.isNetwork) {
                    self.offline = true
                }
                // 失败 ⇒ 不判空（保持 dataChecked = false）
            })
        },

        /* ───────────── ②③④ 条件 ───────────── */

        /**
         * 指标开关（③ 的唯一交互点）。
         * ★ 与 SC-22 不同：**筛选条件变更不作废已生成的文件** —— 导出文件是**生成时刻的快照**，
         *   不存在"拿旧范围的 N 去删新范围数据"那类正确性问题（该铁律属 SC-22 的删除语义）。
         */
        onToggleMetric: function (type) {
            if (this.generating) {
                return
            }
            const next = []
            let removed = false
            for (let i = 0; i < this.metricSelection.length; i++) {
                if (this.metricSelection[i] === type) {
                    removed = true
                } else {
                    next.push(this.metricSelection[i])
                }
            }
            if (!removed) {
                next.push(type)
            }
            this.metricSelection = next
        },
        /** [全选/清空] 一键切换（③ 规格要求） */
        onMetricToggleAll: function () {
            if (this.generating) {
                return
            }
            this.metricSelection = this.allMetricsSelected ? [] : METRIC_TYPES.slice()
        },
        /** 时间范围切换（「自定义」= 开抽屉的动作 ⇒ **不改变 `rangeMode`**，取消即回原选项） */
        onRangeChange: function (next) {
            if (this.generating) {
                return
            }
            if (next === 'custom') {
                this.draftStart = this.customStart
                this.draftEnd = this.customEnd
                this.rangeVisible = true
                return
            }
            if (next === this.rangeMode) {
                return
            }
            this.rangeMode = next
        },
        onRangeConfirm: function () {
            this.customStart = this.draftStart
            this.customEnd = this.draftEnd
            this.rangeMode = 'custom'
            this.rangeVisible = false
        },
        onRangeCancel: function () {
            this.rangeVisible = false
        },
        /** 格式切换（④；纯枚举值，重复点击无副作用） */
        onFormatChange: function (next) {
            if (this.generating) {
                return
            }
            if (next === this.formatMode) {
                return
            }
            this.formatMode = next
        },

        /* ───────────── ⑤⑥⑦⑧ 生成（E-01，破坏性最低但必须验密） ───────────── */

        /**
         * [生成文件] ⇒ **先开验密弹窗**（⑥ 每次必弹、不可豁免）。
         * ★ 按钮置灰时必须给出**原因提示**（不静默无反应）。
         */
        onGenerate: function () {
            if (this.generateDisabled) {
                if (this.offline) {
                    showToast('error', OFFLINE_SUBMIT_TEXT)
                    return
                }
                if (this.noData) {
                    showToast('error', NO_DATA_TEXT)
                    return
                }
                if (this.metricSelection.length === 0) {
                    showToast('error', NO_SELECT_TEXT)
                    return
                }
                return
            }
            this.pwdValue = ''
            this.pwdError = ''
            this.pwdVisible = true
        },
        onPwdCancel: function () {
            this.pwdVisible = false
            this.pwdValue = ''
            this.pwdError = ''
        },
        onPwdConfirm: function () {
            if (!this.pwdValue) {
                this.pwdError = '请输入登录密码'
                return
            }
            this.pwdVisible = false
            this.doCreate(this.pwdValue)
        },
        /** ⑫③ 重试入口：清掉失败提示后**重新走一遍**（仍必须先验密 ⇒ 调 `onGenerate`） */
        onRetryGenerate: function () {
            this.genError = ''
            this.onGenerate()
        },
        /**
         * 执行生成（`E-01`）。
         * ★ 每个请求**各用一个全新 `Idempotency-Key`**（该接口消费幂等头；同 key + 异 body → `409`）。
         * ★ `metric_types`：全选 ⇒ `null`（= 全部指标）；部分选 ⇒ 按固定序的数组（**不可传空数组**，服务端 400）。
         * ★ 时间：「全部」⇒ `range_start` / `range_end` 传 `null`（服务端不限时间）。
         */
        doCreate: function (password) {
            const self = this
            const range = this.windowRange
            this.generating = true
            this.genError = ''
            this.pwdError = ''

            const payload = {
                format: this.formatMode,
                metric_types: this.allMetricsSelected ? null : this.selectedMetricTypes,
                range_start: range.start ? range.start : null,
                range_end: range.end ? range.end : null,
                password: password
            }

            return createExport(payload, newIdempotencyKey()).then(function (res) {
                self.generating = false
                self.pwdValue = ''
                self.generated = res && res.data ? res.data : null
                // ⑯ 生成成功（逐字）
                showToast('success', GENERATED_TEXT)
                // 顺带刷新历史任务（新任务应立刻出现在 ⑨ 里）
                self.loadHistory(true)
            }, function (err) {
                self.generating = false
                self.pwdValue = ''
                if (err && err.isNetwork) {
                    self.offline = true
                    showToast('error', errorText(err))
                    return
                }
                if (err && err.code === 'PASSWORD_INVALID') {
                    // ⑫① 密码错：**重回验密步骤**，已选范围 / 指标 / 格式保持不变
                    self.pwdError = PASSWORD_TEXT
                    self.pwdVisible = true
                    return
                }
                if (err && err.code === 'SESSION_VERIFY_ABORTED') {
                    // 连错 3 次：服务端中止本次导出（**不纳入登录锁定**）⇒ 需用户**重新发起**
                    showToast('error', errorText(err))
                    return
                }
                if (err && err.code === 'EXPORT_IN_PROGRESS') {
                    // ⑫② 进行中冲突：顺带刷新历史任务，让用户看到"进行中的是哪一条"
                    showToast('error', IN_PROGRESS_TEXT)
                    self.loadHistory(true)
                    return
                }
                // ⑫③ 其他失败：明确提示 + 重试入口（不可静默失败）
                self.genError = FAIL_TEXT
                showToast('error', FAIL_TEXT)
            })
        },

        /* ───────────── ⑧⑨ 下载（E-02 取凭证 → E-03 文件流 → B-3 浏览器下载） ───────────── */

        /** ⑧ 下载"最近生成"的那个文件 */
        onDownloadGenerated: function () {
            if (!this.generated) {
                return
            }
            this.onDownload({
                export_id: this.generated.export_id,
                canDownload: !this.offline
            })
        },
        /**
         * 下载一个任务。
         * ★ 流程：**先 `E-02` 取 `file_token`**（`E-04` / `E-01` 的响应都**不含**凭证）⇒
         *   再 `uni.downloadFile`（带 `Authorization`）⇒ 交给浏览器下载。
         * ★ `file_token` 只作为**本方法的局部变量**存在：不写 `storage`、不写 `cache`、不进 `data`。
         */
        onDownload: function (row) {
            const self = this
            if (this.offline) {
                showToast('error', NEED_NETWORK_TEXT)
                return
            }
            if (!row || !row.canDownload || this.downloadingId) {
                return
            }
            this.downloadingId = row.export_id

            fetchExport(row.export_id).then(function (res) {
                const data = res && res.data ? res.data : {}
                const token = data.file_token
                if (!token) {
                    // 服务端只在 `ready` / `downloaded` 时给凭证 ⇒ 拿不到就是窗口已过
                    self.downloadingId = 0
                    showToast('error', EXPIRED_TEXT)
                    self.loadHistory(true)
                    return
                }
                const url = exportDownloadUrl(row.export_id, token)
                const filename = exportFileName(data.format, data.created_at)
                self.runDownload(url, filename)
            }, function (err) {
                self.downloadingId = 0
                self.handleDownloadError(err)
            })
        },
        /** 下载失败统一处置（`E-02` 的 JSON 错误走这里） */
        handleDownloadError: function (err) {
            if (err && err.isNetwork) {
                this.offline = true
                showToast('error', errorText(err))
                return
            }
            if (err && err.code === 'EXPORT_EXPIRED') {
                showToast('error', EXPIRED_TEXT)
                this.loadHistory(true)
                return
            }
            showToast('error', errorText(err))
        },
        /**
         * `E-03` 取文件流（**不走 `utils/request.js`**：该接口返回文件流而非 JSON 信封）。
         * ★ 非 200 按**状态码**映射文案（`410` 过期 / `404` 不存在）—— 不解析错误体，
         *   因为它不是统一信封的可靠读取路径（如实登记于交付报告 §五）。
         */
        runDownload: function (url, filename) {
            const self = this
            const header = {}
            const accessToken = getAccessToken()
            if (accessToken) {
                header.Authorization = 'Bearer ' + accessToken
            }
            uni.downloadFile({
                url: url,
                header: header,
                success: function (res) {
                    const status = res ? res.statusCode : 0
                    self.downloadingId = 0
                    if (status === 200 && res && res.tempFilePath) {
                        if (self.triggerBrowserDownload(res.tempFilePath, filename)) {
                            // ★ B-3 裁定：成功提示**逐字**（H5 拿不到系统保存路径，故不写「已保存到 <位置>」）
                            showToast('success', DOWNLOAD_DONE_TEXT)
                            self.loadHistory(true)
                        } else {
                            showToast('error', UNSUPPORTED_TEXT)
                        }
                        return
                    }
                    if (status === 410) {
                        showToast('error', EXPIRED_TEXT)
                        self.loadHistory(true)
                        return
                    }
                    if (status === 404) {
                        showToast('error', '内容不存在或已被删除')
                        return
                    }
                    showToast('error', FAIL_TEXT)
                },
                fail: function () {
                    self.downloadingId = 0
                    self.offline = true
                    showToast('error', OFFLINE_SUBMIT_TEXT)
                }
            })
        },
        /**
         * ★ H5 降级专线（**B-3**）：把 `uni.downloadFile` 取回的 blob 交给浏览器原生下载。
         *
         * 为什么是浏览器而不是沙盒：H5 **无沙盒落盘**（实测 `uni.saveFile` → `fail: not supported`、
         * `getFileSystemManager` ＝ `undefined`）⇒ 规格 ⑧/⑰ 的「保存到沙盒 / 用户选择目录」
         * **在 H5 无实现**，只能由浏览器下载（用户在浏览器的"下载目录"里找文件）。
         *
         * 非 H5 运行环境（无 `document`）**如实返回 false**，由调用方提示"不支持"，
         * **绝不伪造成功**（与 `uni.openDocument` 的"假成功"陷阱相对）。
         *
         * @returns {boolean} 是否已触发浏览器下载
         */
        triggerBrowserDownload: function (href, filename) {
            if (typeof document === 'undefined' || typeof document.createElement !== 'function' || !document.body) {
                return false
            }
            try {
                const link = document.createElement('a')
                link.href = href
                link.download = filename
                link.rel = 'noopener'
                document.body.appendChild(link)
                link.click()
                document.body.removeChild(link)
                return true
            } catch (e) {
                return false
            }
        },

        /* ───────────── ⑨ 历史任务（E-04，只读） ───────────── */

        /**
         * 拉取历史任务（S-10：进页即请求，`limit=20`，仅展示）。
         * ★ 成功即写缓存（**E-04 响应本身不含 `file_token`** ⇒ 缓存它不违反"凭证不落盘"）。
         * ★ 离线 ⇒ 直接读缓存（并标注更新时间）；缓存也没有 ⇒ 空列表，**不假装"没有任务"以外的东西**。
         */
        loadHistory: function (silent) {
            const self = this
            if (this.offline) {
                this.loadHistoryFromCache()
                return Promise.resolve()
            }
            if (!silent) {
                this.historyLoading = true
            }
            this.historyError = ''
            return fetchExports({ limit: HISTORY_LIMIT }).then(function (res) {
                const data = res && res.data ? res.data : {}
                const items = data.items || []
                self.historyItems = items
                self.historyCursor = data.next_cursor || ''
                self.historyHasMore = !!data.has_more
                self.historyLoading = false
                self.historyFromCache = false
                self.historyStamp = ''
                saveCache(HISTORY_CACHE_KEY, { items: items })
            }, function (err) {
                self.historyLoading = false
                if (err && err.isNetwork) {
                    self.offline = true
                    self.loadHistoryFromCache()
                    return
                }
                self.historyError = errorText(err)
            })
        },
        /** 离线：读历史任务缓存（**必须标注更新时间**，不把陈旧数据冒充实时） */
        loadHistoryFromCache: function () {
            const cached = loadCache(HISTORY_CACHE_KEY)
            if (!cached || !cached.data || !cached.data.items) {
                this.historyItems = []
                this.historyFromCache = false
                this.historyStamp = ''
                return
            }
            this.historyItems = cached.data.items
            this.historyFromCache = true
            this.historyStamp = cached.savedAt
        },
        /** ⑨ 加载更多（游标分页；`E-04` 无 `total`，故以 `has_more` + `next_cursor` 驱动） */
        loadMoreHistory: function () {
            const self = this
            if (this.offline || !this.historyHasMore || this.historyLoading) {
                return
            }
            this.historyLoading = true
            return fetchExports({ limit: HISTORY_LIMIT, cursor: this.historyCursor }).then(function (res) {
                const data = res && res.data ? res.data : {}
                const more = data.items || []
                self.historyItems = self.historyItems.concat(more)
                self.historyCursor = data.next_cursor || ''
                self.historyHasMore = !!data.has_more
                self.historyLoading = false
                saveCache(HISTORY_CACHE_KEY, { items: self.historyItems })
            }, function (err) {
                self.historyLoading = false
                self.historyError = errorText(err)
            })
        },

        /* ───────────── 导航 / 网络 ───────────── */

        /** ⑩ 空态的 [返回]（出口 = 回到 SC-20 数据管理页） */
        onBack: function () {
            navigateBack()
        },
        handleNetworkChange: function (res) {
            const online = !!(res && res.isConnected)
            if (!online) {
                this.offline = true
                return
            }
            this.offline = false
            this.showRestoredBanner()
            // 恢复网络：重刷本页**只读**数据（`D-01` 存在性 + `E-04` 历史）；
            // **绝不自动重放写操作**（`E-01` 需验密 ⇒ 不重发，符合 S1-D §5）
            this.loadSummary()
            this.loadHistory(true)
        },
        showRestoredBanner: function () {
            const self = this
            this.clearBanner()
            this.restoredVisible = true
            this.bannerTimer = setTimeout(function () {
                self.restoredVisible = false
                self.bannerTimer = null
            }, NETWORK_BANNER_MS)
        },
        clearBanner: function () {
            if (this.bannerTimer) {
                clearTimeout(this.bannerTimer)
                this.bannerTimer = null
            }
        }
    }
}
</script>

<style scoped lang="scss">
.epage {
    min-height: 100vh;
    background-color: var(--s-page);
}

/* A 类系统导航栏的占位由平台负责，此处只留内容区节奏 */
.epage__body {
    padding-top: var(--page-pad-t);
    padding-bottom: var(--page-pad-b);
}

/* 内容最大宽居中（DESIGN.md §10.4③）+ 唯一水平边距来源 --gutter */
.epage__inner {
    max-width: var(--content-max);
    margin-left: auto;
    margin-right: auto;
    padding-left: var(--gutter);
    padding-right: var(--gutter);
}

/* 区块节奏：卡片之间统一走 --card-gap */
.epage__block {
    margin-bottom: var(--card-gap);
}

/* 说明类小字（自定义范围已生效串 / 未选指标 / 缓存更新时间 / 抽屉内范围说明） */
.epage__hint {
    display: block;
    margin-top: var(--sp-4);
    font-size: var(--fs-caption);
    line-height: $lh-caption;
    color: var(--t-3);
    letter-spacing: 0;
}

/* 错误类小字（历史任务加载失败） */
.epage__error-text {
    display: block;
    margin-top: var(--sp-4);
    font-size: var(--fs-caption);
    line-height: $lh-caption;
    color: var(--t-danger);
    letter-spacing: 0;
}

/* ③ 指标区标题行：左标题 + 右 [全选/清空] */
.epage__metrics-head {
    display: flex;
    flex-direction: row;
    align-items: center;
    justify-content: space-between;
    margin-top: var(--sp-5);
    margin-bottom: var(--sp-2);
}

.epage__metrics-title {
    font-size: var(--fs-body);
    line-height: $lh-body;
    font-weight: $fw-medium;
    color: var(--t-2);
    letter-spacing: 0;
}

/* ⑦ 进度条（**B-2 页内自绘**：纯 CSS 走令牌，**不新增组件编号**）。
   高度取 `--sp-2`（8rpx）以保持"全部长度走令牌"，颜色取品牌主色 + 中性凹陷底。 */
.epage__progress-wrap {
    margin-top: var(--sp-5);
}

.epage__progress {
    height: var(--sp-2);
    border-radius: var(--r-full);
    background-color: var(--c-n-100);
    overflow: hidden;
}

/* 不确定进度：后端 `E-01` 为**同步生成**、无进度接口，故只表达"正在进行"，**不伪造百分比** */
.epage__progress-bar {
    width: 40%;
    height: 100%;
    border-radius: var(--r-full);
    background-color: var(--c-p-600);
    animation: epage-progress-slide var(--d-slow) var(--ease-std) infinite;
}

@keyframes epage-progress-slide {
    0% {
        transform: translateX(-100%);
    }
    100% {
        transform: translateX(250%);
    }
}

.epage__progress-text {
    display: block;
    margin-top: var(--sp-3);
    font-size: var(--fs-caption);
    line-height: $lh-caption;
    color: var(--t-3);
    letter-spacing: 0;
}

/* 主行动按钮与上方内容的间距 */
.epage__action {
    margin-top: var(--sp-6);
}

/* ⑫③ 失败行：文案（可收缩侧）+ [重试] 按钮。
   文本侧 `flex: 1` **且 `min-width: 0`** ⇒ 长文案不会把按钮压没
   （09-17 宽度分配缺陷铁律：不可收缩区不得承载长文本）。 */
.epage__feedback {
    display: flex;
    flex-direction: row;
    align-items: center;
    margin-top: var(--sp-5);
}

.epage__feedback-text {
    flex: 1;
    min-width: 0;
    font-size: var(--fs-caption);
    line-height: $lh-caption;
    color: var(--t-danger);
    letter-spacing: 0;
}

/* ⑧ 生成结果区块（品牌软底；**非危险语义**，故不用 --c-danger / --c-warning 系） */
.epage__result {
    margin-top: var(--sp-6);
    padding: var(--sp-5);
    border-radius: var(--r-md);
    background-color: var(--s-brand-soft);
}

.epage__result-title {
    display: block;
    font-size: var(--fs-body);
    line-height: $lh-body;
    font-weight: $fw-semibold;
    color: var(--t-1);
    letter-spacing: 0;
}

.epage__result-meta {
    display: block;
    margin-top: var(--sp-2);
    font-size: var(--fs-caption);
    line-height: $lh-caption;
    color: var(--t-2);
    letter-spacing: 0;
}

/* 弹窗正文（⑥ 验密说明两行） */
.epage__modal-text {
    display: block;
    font-size: var(--fs-body);
    line-height: $lh-body;
    color: var(--t-2);
    letter-spacing: 0;
}

.epage__modal-text + .epage__modal-text {
    margin-top: var(--sp-2);
}

/* 表单与弹窗正文的节奏 */
.epage__field {
    margin-top: var(--sp-5);
}

/* ⑩ 页脚说明（**逐字**冻结文案） */
.epage__footer {
    display: block;
    font-size: var(--fs-caption);
    line-height: $lh-caption;
    color: var(--t-3);
    letter-spacing: 0;
}
</style>
