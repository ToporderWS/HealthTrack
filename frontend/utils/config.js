/**
 * 前端运行时配置（**非设计令牌**，故不含任何视觉取值）。
 *
 * 依据：
 *   - S1-D §5：前端以 `uni.request` 自研封装访问 `/api/v1`；
 *   - S1-D §5.5：本机 / 局域网部署（App 优先，Android 真机）；
 *   - S1-B §3.11：写类接口可携带 `Idempotency-Key`（8–128 字符）。
 *
 * ⚠️ 待需求方裁定项（S3-1 不阻塞页面开发，但阻塞联调）：
 *   `API_BASE_URL` 的 dev / test 真实地址（本机 127.0.0.1 仅对模拟器与 H5 预览有效；
 *   真机调试必须改为开发机的**局域网 IP**，例如 http://192.168.x.x:5000/api/v1）。
 */

/** 应用版本（与 manifest.json versionName 保持一致） */
export const APP_VERSION = '0.1.0'

/**
 * 协议版本号（A-01 注册时随 `agreement_version` 上报，服务端留痕）。
 * 取值 = S1-B 接口示例与 S1-B 第三批协议草案所用版本号。
 */
export const AGREEMENT_VERSION = 'v1.0'

/**
 * 服务端基地址（含 `/api/v1` 前缀）。
 * ★ S3-9 3.3 真机联调：已改为开发机局域网 IP（真机不能用 127.0.0.1）；
 *   仅 development 联调用，正式部署须按部署环境改回。
 */
export const API_BASE_URL = 'http://192.168.2.219:5000/api/v1'

/** 请求超时（毫秒）。超时中断并给出明确提示（S1-D §5：超时中断 + 明确提示） */
export const REQUEST_TIMEOUT = 15000

/** `Idempotency-Key` 长度约束（S1-B §3.11 冻结：8–128） */
export const IDEMPOTENCY_KEY_LEN = 32

/** 启动页最短展示时长（避免"明显空白闪屏"，S1-C SC-01 ⑨：1.5 秒内完成判断） */
export const LAUNCH_MIN_SHOW_MS = 600

/** 启动页兜底超时（S1-C SC-01 ⑪：最长停留 3 秒，超时按未登录处理） */
export const LAUNCH_TIMEOUT_MS = 3000

/**
 * Toast 停留时长（毫秒）。
 * ★ 与 DESIGN.md §7 的 `--d-toast`（2000ms）**必须同值**：CSS 令牌无法在 JS 中读取，
 *   因此此处为同值常量；若调整 `--d-toast`，必须同步本常量。
 */
export const TOAST_DURATION_MS = 2000

/** 表单草稿保留期（S1-B 第三批 C6：单份 ≤32KB、≤5 份、保留 7 天） */
export const DRAFT_TTL_MS = 7 * 24 * 60 * 60 * 1000

/** 表单草稿单份容量上限（字符数），对齐 C6 的 32KB 口径 */
export const DRAFT_MAX_CHARS = 32 * 1024

/** 表单草稿最多保留份数（S3-1 只有 SC-05 一份建档草稿） */
export const DRAFT_MAX_COUNT = 5

/**
 * 网络恢复横幅的展示时长（毫秒）。
 * 依据：DESIGN.md §8.2 C-17「网络横幅（离线 / 恢复，3s）」—— 3 秒后由页面撤下。
 */
export const NETWORK_BANNER_MS = 3000

/**
 * 「仍在加载，请稍候」的追加阈值（毫秒）。
 * 依据：DESIGN.md §7④「加载：首屏**骨架屏**（禁整页白屏）；**> 8s** 追加『仍在加载，请稍候』」。
 */
export const SLOW_LOADING_MS = 8000
