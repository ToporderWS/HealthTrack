/**
 * 用户 / 会话状态（Pinia 2.x，S1-D 冻结）。
 *
 * 职责边界：
 *   - **只承载登录态与会话相关状态**：Token、用户信息、建档标记；
 *   - 本地读写统一经 `utils/auth.js`（→ `utils/storage.js`），本 store 不直接碰存储 API；
 *   - **不缓存密码明文**、不缓存健康数值（S1-B 禁缓存 10 项）。
 *
 * 与后端契约的关系：
 *   - A-02 登录响应 `data = { user, profile_initialized, tokens }`；
 *   - A-01 注册响应 `data = { user, tokens }`（`auto_login=true` 时）；注册后档案必然未建档 → `false`；
 *   - A-06 `GET /users/me` 返回 `profile_initialized`（用于会话恢复时刷新建档标记）。
 */
import { defineStore } from 'pinia'
import * as session from '../utils/auth'
import * as authApi from '../api/auth'

export const useUserStore = defineStore('user', {
    state: function () {
        return {
            /** Access Token（JWT HS256，2h） */
            accessToken: null,
            /** Refresh Token（不透明随机串，30d，单次使用即轮换） */
            refreshToken: null,
            /** 当前用户（仅 user_id / username，服务端不下发敏感字段） */
            user: null,
            /** 是否已建档（F-009 客户端流程判定依据）；null = 未知 */
            profileInitialized: null,
            /** 是否已从本地存储恢复过状态 */
            hydrated: false
        }
    },
    getters: {
        isLoggedIn: function (state) {
            return !!(state.accessToken || state.refreshToken)
        },
        username: function (state) {
            return state.user && state.user.username ? String(state.user.username) : ''
        }
    },
    actions: {
        /** 从本地存储恢复登录态（App 启动 / 页面进入时调用；**不发网络请求**） */
        hydrate: function () {
            this.accessToken = session.getAccessToken()
            this.refreshToken = session.getRefreshToken()
            this.user = session.getCachedUser()
            this.profileInitialized = session.getCachedProfileInitialized()
            this.hydrated = true
        },

        /** 写入登录态（登录 / 注册成功后） */
        applySession: function (payload) {
            session.saveSession(payload)
            this.hydrate()
        },

        /** 清空登录态（登出 / 注销 / 会话失效） */
        clearSession: function () {
            session.clearSession()
            this.hydrate()
        },

        /** 清空登录态 + 全部登录态相关缓存（对应 S1-B 四触发：登出 / 注销 / 401 / 改密） */
        clearSessionAndCache: function () {
            session.clearSessionAndCache()
            this.hydrate()
        },

        /** 仅更新令牌（A-03 刷新成功后） */
        applyTokens: function (tokens) {
            session.updateTokens(tokens)
            this.hydrate()
        },

        /** 更新建档标记（P-02 保存成功后置 true） */
        setProfileInitialized: function (value) {
            session.saveSession({ profileInitialized: value === true })
            this.profileInitialized = value === true
        },

        /**
         * A-02 登录：成功后写入登录态。
         * @returns {Promise<object>} 统一响应体
         */
        login: function (payload, idempotencyKey) {
            const self = this
            return authApi.login(payload, idempotencyKey).then(function (res) {
                const data = res.data || {}
                self.applySession({
                    tokens: data.tokens,
                    user: data.user,
                    profileInitialized: data.profile_initialized
                })
                return res
            })
        },

        /**
         * A-01 注册：`auto_login=true` 时响应内含 tokens（服务端契约）。
         * 注册后档案必然未建档 → 建档标记置 false（SC-04 → SC-05）。
         * @returns {Promise<object>} 统一响应体
         */
        register: function (payload, idempotencyKey) {
            const self = this
            return authApi.register(payload, idempotencyKey).then(function (res) {
                const data = res.data || {}
                if (data.tokens) {
                    self.applySession({
                        tokens: data.tokens,
                        user: data.user,
                        profileInitialized: false
                    })
                }
                return res
            })
        },

        /** A-06 刷新当前用户与建档标记（会话恢复 / SC-05 保存后） */
        refreshMe: function () {
            const self = this
            return authApi.fetchMe().then(function (res) {
                const data = res.data || {}
                self.applySession({
                    user: { user_id: data.user_id, username: data.username },
                    profileInitialized: data.profile_initialized
                })
                return res
            })
        }
    }
})
