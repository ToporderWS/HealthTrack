/**
 * 康迹 HealthTrack · 法律主体信息**集中配置点**（S4-1 新增）
 *
 * 目的（需求方 2026-09-22 S4-1 裁定 §五）：
 *   1. 隐私政策（SC-23）/ 用户协议（SC-24）/ 关于（SC-25）中涉及**真实运营主体**的信息
 *      （主体名称 / 联系邮箱 / 其他联系方式 / 响应时限 / 备案信息 / 生效日期 / 争议解决）
 *      **一律不编造**，全部集中在本文件，**一处填写、三页生效**；
 *   2. 禁止在页面里散落硬编码这些字段（避免出现"三页各写一份、值还不一样"）。
 *
 * ★ 待填写机制（`LEGAL_TBD`）
 *   - 上表字段尚未提供的，取值 = `LEGAL_TBD`（当前为「待补充」）；
 *   - 这是**发布前待补**的占位，**不是**"已知但没有"的虚构内容；
 *   - 发布前把 `LEGAL_TBD` 逐项替换为真实值即可，**无需改任何页面代码**；
 *   - 对照清单：`.workbuddy/artifacts/S4-1-发布前待补法律主体信息清单.md`。
 *
 * ★ 与 DESIGN.md §12 的关系（如实登记）
 *   DESIGN.md §12 要求「协议/关于页保留【占位符：…】、不得改写为定稿、不得编造主体信息」。
 *   本文件把该"占位符"**集中化**并给出可读的占位文案（「待补充」），
 *   仍保留 `LEGAL_DRAFT_MARK` 草案标记 ⇒ **不编造、不定稿**两条硬约束不变。
 *   "占位符不再以【占位符：…】字面样式出现在页面"属**已登记的规格偏差**（见 S4-1 报告 §六），
 *   待需求方裁定是否回写 DESIGN.md。
 *
 * 依据：S1-B 第三批《隐私政策与用户协议技术草案》A1 / A16 / A18 / B15 / B16 ｜
 *       DESIGN.md §12（文案与红线）
 */

import { APP_VERSION, AGREEMENT_VERSION } from './config'

/**
 * 待填写哨兵（**唯一常量**）。
 * 页面只渲染本常量的值，不自行拼写"待配置"类文案 ⇒ 将来替换只需改这一行。
 */
export const LEGAL_TBD = '待补充'

/**
 * 草案标记（DESIGN.md §12 要求保留；**不得**改为"定稿"）。
 * 三页统一引用，避免各页写法不一。
 */
export const LEGAL_DRAFT_MARK = '技术实现草案 · 上线前需经法律/合规审核'

/** 待补充说明句（用户可见，用于解释占位；**不呈现工程字样**） */
export const LEGAL_PENDING_HINT = '上述信息将在正式发布前补充完整。'

/**
 * 隐私政策版本号（`PRIVACY_POLICY_VERSION`）：定义在 `LEGAL_ENTITY` **之后**
 * —— 它读取 `LEGAL_ENTITY.policyEffectiveDate`，必须晚于 `LEGAL_ENTITY` 的初始化，
 * 否则会触发 `ReferenceError: Cannot access 'LEGAL_ENTITY' before initialization`。
 * 详见本文件下方「隐私政策版本号（派生）」区块。
 */

/** 当前应用版本（**单一来源** = `utils/config.js`，与 `manifest.json.versionName` 同值） */
export const LEGAL_APP_VERSION = APP_VERSION

/**
 * 运营主体与联系信息（A16 / B15 / B16 / A18）。
 * ★ 部分字段已填真实值（operatorName / contactEmail / contactOther / responseTime /
 *   filingInfo / applicableLaw / disputeResolution），其余仍为 `LEGAL_TBD` 占位
 *   （policyEffectiveDate），**发布前必须逐项替换**。
 */
export const LEGAL_ENTITY = {
    /** 运营者 / 个人信息处理者名称（A16；个人开发者填姓名或主体名称） */
    operatorName: '赵元文',
    /** 联系邮箱（A16） */
    contactEmail: 'dw3024213118@gmail.com',
    /** 其他联系方式（可选：项目主页 / 反馈渠道；A16） */
    contactOther: '不适用',
    /** 联系响应时限（A16，待法律审核确认） */
    responseTime: '7 个工作日内',
    /** 备案 / ICP 信息（A16，如未来上架需填写） */
    filingInfo: '不适用',
    /** 政策生效日期（A1） */
    policyEffectiveDate: LEGAL_TBD,
    /** 适用法律（B15；V1.0 面向中国大陆 ⇒ 中华人民共和国法律） */
    applicableLaw: '中华人民共和国法律',
    /** 争议解决方式（B15；按既定法律语义表述：先协商、协商不成依法诉讼，由有管辖权的人民法院依法确定） */
    disputeResolution: '发生争议时，各方应先友好协商解决；协商不成的，任何一方均可依法向有管辖权的人民法院提起诉讼。'
}

/**
 * 隐私政策版本号（A1 / B15：政策版本号 = `<协议版本>-<发布日期>`，如 `v1.0-2026-10-01`）。
 *
 * ★ 单一数据源（Release-2 第二批收口，`R2PRE-03`）：发布日期**只**取
 *   `LEGAL_ENTITY.policyEffectiveDate` —— 不得在别处再维护一份发布日期字符串。
 *   填入合法日期后，本常量**自动**派生为 `<AGREEMENT_VERSION>-<日期>`，无需二次同步。
 *
 * ★ 未发布态（`policyEffectiveDate` 仍为 `LEGAL_TBD`）：
 *   返回明确的**未发布标记** `LEGAL_POLICY_VERSION_UNPUBLISHED`，**绝不**拼出
 *   `v1.0-待补充` / `v1.0-LEGAL_TBD` / `v1.0-undefined` / `v1.0-null` 之类畸形版本号，
 *   也**绝不**用任何自动时间（`new Date()` / 构建日期）冒充发布日期。
 *
 * ★ 位置约束：本区块**必须**位于 `LEGAL_ENTITY` 之后（见上方指针注释）。
 */
export const LEGAL_POLICY_VERSION_UNPUBLISHED = '未发布'

/** 合法发布日期格式（唯一格式规定来源：S4-1 待补清单 §二 ⇒ `YYYY-MM-DD`） */
const POLICY_DATE_RE = /^\d{4}-\d{2}-\d{2}$/

export const PRIVACY_POLICY_VERSION = POLICY_DATE_RE.test(LEGAL_ENTITY.policyEffectiveDate)
    ? AGREEMENT_VERSION + '-' + LEGAL_ENTITY.policyEffectiveDate
    : LEGAL_POLICY_VERSION_UNPUBLISHED

/**
 * 发布前待补字段清单（机器可读；供《S4-1 发布前待补法律主体信息清单》与静态自检核对）。
 * `key` 对应 `LEGAL_ENTITY` 的键。
 *
 * ★ 语义（Release-2 第二批收口，`R2B1-01`）：本清单**只描述当前真实待补字段** ——
 *   即取值为 `LEGAL_TBD` 的字段；**已填真实值的字段一律不得列入**。
 *   当前真实待补 = 1 项：`policyEffectiveDate`。
 */
export const LEGAL_PENDING_FIELDS = [
    { key: 'policyEffectiveDate', label: '隐私政策生效日期' }
]

/**
 * 联系维护者信息行（SC-23 / SC-24 / SC-25 共用同一数据源 ⇒ 三页**必然一致**）。
 * 依据 A16（2026-09-29 修订）：V1.0 提供基于已验证邮箱的自助找回；未绑定可验证邮箱的账号，账号 / 密码问题请通过以下渠道联系维护者。
 */
export function getContactRows() {
    return [
        { key: 'operatorName', label: '运营者', value: LEGAL_ENTITY.operatorName },
        { key: 'contactEmail', label: '联系邮箱', value: LEGAL_ENTITY.contactEmail },
        { key: 'contactOther', label: '其他联系方式', value: LEGAL_ENTITY.contactOther },
        { key: 'responseTime', label: '响应时限', value: LEGAL_ENTITY.responseTime }
    ]
}

/** 该字段是否仍为待补占位（发布前自检用） */
export function isPending(value) {
    return value === LEGAL_TBD
}
