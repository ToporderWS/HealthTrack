/**
 * 路由常量与统一跳转 / 守卫。
 *
 * 依据：
 *   - DESIGN.md §11（25 页路径冻结）与 §10.3（顶栏策略）；
 *   - DESIGN.md §13：未登录 → 路由守卫 → SC-03（保留已填草稿）；
 *     SC-23/24/25 与 SC-01/02/03/04 放行；
 *   - DESIGN.md §13：401 / 改密 / 注销成功 → **清栈 `reLaunch` 到 SC-03**（不允许返回已登出页面）。
 *
 * ⚠️ 只写入**已实现页面**的路径；未实现页面的路径**不写入本文件**，避免出现指向不存在页面的死链接。
 *    - S3-1：本批 5 页 + SC-23/24/25 路径占位常量；
 *    - S3-2 第二批：新增 SC-07 `RECORD` 与 SC-08 `RECORD_ADD`（两页与 `pages.json` 注册同步落地）。
 *    - S3-3：新增 SC-09 `RECORD_DETAIL` 与 SC-10 `RECORD_HISTORY`（两页与 `pages.json` 注册同步落地）。
 *    - S3-4：新增 SC-11 `TREND`（与 `pages.json` 注册同步落地）。
 *    - S3-5：新增 SC-12 `GOAL` 与 SC-13 `GOAL_EDIT`（两页与 `pages.json` 注册同步落地）。
 *    - S3-6：新增 SC-14 `REMINDER` 与 SC-15 `REMINDER_EDIT`（两页与 `pages.json` 注册同步落地）。
 *    - S3-7：新增 SC-16 `PROFILE` / SC-17 `PROFILE_EDIT`（A 类系统导航栏）、
 *      SC-18 `MINE`（tabBar ④，**B 类自绘顶栏** ⇒ `pages.json` 已加 `navigationStyle: custom`）、
 *      SC-19 `PASSWORD`（A 类系统导航栏）（四页与 `pages.json` 注册同步落地）。
 *    - S3-8：新增 SC-20 `DATA` / SC-21 `DATA_EXPORT` / SC-22 `DATA_DELETE`
 *      （三页均为 **A 类系统导航栏** ⇒ `pages.json` **不加** `navigationStyle: custom`）；
 *      三页与 `pages.json` 注册同步落地。
 *    - **S4-1**：新增 SC-23 `PRIVACY` / SC-24 `TERMS` / SC-25 `ABOUT`
 *      （三页均为 **A 类系统导航栏** ⇒ `pages.json` **不加** `navigationStyle: custom`）。
 *      ★ 这三页本就是冻结 25 页清单的第 23/24/25 页（DESIGN.md §11 / S1-C §三），
 *        故 `pages.json` 由 22 → **25** 为"恢复冻结口径的完整落地"，**不是**新增第 26 页。
 *      ★ 三页**对访客放行、离线完全可读**（DESIGN.md §13；S1-C §5.1），故页面内**不做登录守卫**。
 */
import { hasSession, getCachedProfileInitialized } from './auth'

/** 页面路径（与 DESIGN.md §11 冻结清单逐字一致） */
export const ROUTES = {
    LAUNCH: '/pages/launch/index',                 // SC-01
    ONBOARDING: '/pages/onboarding/index',         // SC-02
    LOGIN: '/pages/auth/login',                    // SC-03
    REGISTER: '/pages/auth/register',              // SC-04
    PROFILE_SETUP: '/pages/onboarding/profile-setup', // SC-05
    HOME: '/pages/index/index',                     // SC-06（S3-2 实现真实首页；S3-1 为工程占位页）
    RECORD: '/pages/record/index',                  // SC-07 记录中心（S3-2 第二批）
    RECORD_ADD: '/pages/record/add',                // SC-08 通用录入页（S3-2 第二批，需带 ?type=；S3-3 起支持 &id= 编辑）
    RECORD_DETAIL: '/pages/record/detail',          // SC-09 记录详情页（S3-3，需带 ?id=&type=）
    RECORD_HISTORY: '/pages/record/history',        // SC-10 记录历史列表（S3-3，需带 ?type=）
    TREND: '/pages/trend/index',                    // SC-11 趋势页（S3-4，tabBar ③；可选 ?type=）
    GOAL: '/pages/goal/index',                      // SC-12 目标页（S3-5，A 类系统导航栏）
    GOAL_EDIT: '/pages/goal/edit',                  // SC-13 目标编辑页（S3-5，A 类；需带 ?type= 4 类之一）
    REMINDER: '/pages/reminder/index',              // SC-14 提醒列表页（S3-6，A 类系统导航栏）
    REMINDER_EDIT: '/pages/reminder/edit',          // SC-15 提醒编辑页（S3-6，A 类；可选 ?id=，无则新建）
    PROFILE: '/pages/profile/index',                // SC-16 健康档案页（S3-7，A 类系统导航栏）
    PROFILE_EDIT: '/pages/profile/edit',            // SC-17 档案编辑页（S3-7，A 类系统导航栏）
    MINE: '/pages/mine/index',                      // SC-18 我的页（S3-7，tabBar ④，B 类自绘顶栏）
    PASSWORD: '/pages/mine/password',               // SC-19 修改密码页（S3-7，A 类系统导航栏）
    DATA: '/pages/data/index',                      // SC-20 数据管理页（S3-8，A 类系统导航栏）
    DATA_EXPORT: '/pages/data/export',              // SC-21 数据导出页（S3-8，A 类系统导航栏）
    DATA_DELETE: '/pages/data/delete',              // SC-22 数据删除页（S3-8，A 类系统导航栏）
    PRIVACY: '/pages/mine/privacy',                 // SC-23 隐私政策页（S4-1，A 类系统导航栏；访客可读）
    TERMS: '/pages/mine/terms',                     // SC-24 用户协议页（S4-1，A 类系统导航栏；访客可读）
    ABOUT: '/pages/mine/about'                      // SC-25 关于页（S4-1，A 类系统导航栏；访客可读）
}

/** 保留当前页面的跳转（用于 SC-03 ⇄ SC-04 这类可返回的流转） */
export function navigateTo(url) {
    uni.navigateTo({
        url: url,
        fail: function () {
            uni.reLaunch({ url: url })
        }
    })
}

/** 清栈跳转（登录成功 / 建档完成 / 会话失效 —— 不允许回退到上一页） */
export function reLaunch(url) {
    uni.reLaunch({ url: url })
}

/** 返回上一页（栈底时静默失败） */
export function navigateBack() {
    const pages = getCurrentPages()
    if (pages && pages.length > 1) {
        uni.navigateBack({ delta: 1 })
    }
}

/** 去登录页（清栈 —— 用于未登录守卫与会话失效） */
export function goLogin() {
    reLaunch(ROUTES.LOGIN)
}

/** 去注册页（保留返回栈，便于回到登录页） */
export function goRegister() {
    navigateTo(ROUTES.REGISTER)
}

/** 去首页（清栈） */
export function goHome() {
    reLaunch(ROUTES.HOME)
}

/** 去建档引导（清栈） */
export function goProfileSetup() {
    reLaunch(ROUTES.PROFILE_SETUP)
}

/** 去首次引导（清栈） */
export function goOnboarding() {
    reLaunch(ROUTES.ONBOARDING)
}

/**
 * 登录成功 / 已登录状态下的落点。
 * 依据 S1-C SC-03 ⑦：成功 → 已建档 **SC-06**、未建档 **SC-05**。
 * @param {boolean|null} profileInitialized 服务端或本地缓存的建档标记
 */
export function resolveAfterAuth(profileInitialized) {
    if (profileInitialized === false) {
        return ROUTES.PROFILE_SETUP
    }
    return ROUTES.HOME
}

/**
 * 未登录守卫：需登录页面的 `onLoad` 首行调用。
 * @returns {boolean} true = 已登录可继续；false = 已跳转登录页（调用方应 return）
 */
export function requireLogin() {
    if (hasSession()) {
        return true
    }
    goLogin()
    return false
}

/**
 * 已登录时不应逗留的页面（SC-03 / SC-04）的守卫。
 * @returns {boolean} true = 应离开（已跳转）；false = 可继续
 */
export function leaveIfLoggedIn() {
    if (!hasSession()) {
        return false
    }
    const initialized = getCachedProfileInitialized()
    reLaunch(resolveAfterAuth(initialized))
    return true
}

/**
 * 启动分流（SC-01 专用，**纯本地状态判断，不依赖网络**）。
 *
 * 依据 S1-C SC-01 ⑦：
 *   未登录 → SC-02（首次安装且未同意过协议）/ SC-03（已同意过协议）；
 *   已登录未建档 → SC-05；
 *   已登录已建档 → SC-06。
 *
 * @param {boolean} agreementAccepted 本地是否已同意协议
 * @returns {string} 目标路径
 */
export function resolveStartupRoute(agreementAccepted) {
    if (hasSession()) {
        const initialized = getCachedProfileInitialized()
        return initialized === false ? ROUTES.PROFILE_SETUP : ROUTES.HOME
    }
    return agreementAccepted ? ROUTES.LOGIN : ROUTES.ONBOARDING
}
